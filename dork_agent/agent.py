from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import urllib.parse

from .config import (
    AGENT_MEMORY_FILE,
    DEFAULT_MAX_RESULTS,
    GOOGLE_SEARCH_URL,
    REVIEW_FILE,
    load_agent_memory,
    load_settings,
    save_agent_memory,
)
from .dork_loader import load_dorks
from .ollama_client import OllamaClient
from .review_writer import write_review
from .searcher import GoogleSearcher
from .sub_agent import CrawlSubAgent, SearchSubAgent, paginate
from .tools import (
    ToolRegistry,
    make_expand_query_tool,
    make_filter_dorks_tool,
    make_get_dork_categories_tool,
)


_RELEVANCE_ORDER = {"high": 0, "medium": 1, "low": 2, "unknown": 3}

# Per-backend instructions included in planning prompts
_BROWSER_INSTRUCTIONS: Dict[str, str] = {
    "native": (
        "Use the native requests backend (no headless browser). "
        "Searches are fetched via plain HTTP from the local machine, "
        "and each search URL is also opened in the user's real browser."
    ),
    "playwright": (
        "Use Playwright (Chromium, headless). "
        "Load pages with page.goto(url, wait_until='domcontentloaded'), "
        "wait 2-4 s to avoid rate-limits, then extract div.g blocks "
        "for title/url/snippet. Handle pagination by clicking Next."
    ),
    "selenium": (
        "Use Selenium (ChromeDriver, headless=new). "
        "Call driver.get(url) with implicit waits of 2-4 s. "
        "Find elements via By.CSS_SELECTOR('div.g'), extract h3/a[href]/.VwiC3b. "
        "Re-fetch stale elements after transitions."
    ),
    "browser-use": (
        "Use browser-use (async BrowserSession, headless). "
        "Await session.start(), then await session.new_page(url) per query. "
        "Use page.evaluate(js_fn, args) returning JSON.stringify(results). "
        "Await asyncio.sleep(2-4) between requests, await session.stop() when done."
    ),
}


class DorkAgent:
    """Orchestrates dork selection, parallel searching, URL crawling, and memory."""

    def __init__(
        self,
        goal: Optional[str] = None,
        dork_file: Optional[str] = None,
        small_model: Optional[str] = None,
        large_model: Optional[str] = None,
        backend: Optional[str] = None,
        review_path: Optional[str] = None,
        max_results: Optional[int] = None,
        memory_file: Optional[str] = None,
        small_model_client: Optional[OllamaClient] = None,
        large_model_client: Optional[OllamaClient] = None,
        searcher: Optional[GoogleSearcher] = None,
    ) -> None:
        settings = load_settings()
        self.goal = goal
        self.dork_file = dork_file or settings["dork_file"]
        self.review_path = review_path or settings["review_path"]
        self.memory_file = Path(memory_file) if memory_file else AGENT_MEMORY_FILE
        self.memory = self._load_memory()
        self.small_model = small_model_client or OllamaClient(
            small_model or settings["small_model"]
        )
        self.large_model = large_model_client or OllamaClient(
            large_model or settings["large_model"]
        )
        self.searcher = searcher or GoogleSearcher(
            backend=backend or settings["browser_backend"],
            max_results=max_results or settings["max_results"],
        )

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def _save_memory(self) -> None:
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        self.memory_file.write_text(json.dumps(self.memory, indent=2), encoding="utf-8")

    def _load_memory(self) -> Dict[str, Any]:
        if self.memory_file.exists():
            try:
                return json.loads(self.memory_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {"sessions": []}

    def _record_memory(
        self,
        goal: str,
        selected_dorks: List[str],
        reasoning: str,
        findings: List[Dict[str, Any]],
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "goal": goal,
            "selected_dorks": selected_dorks,
            "reasoning": reasoning,
            "findings_count": sum(len(item.get("results", [])) for item in findings),
            "browser_backend": getattr(self.searcher, "backend", "unknown"),
            "small_model": self.small_model.model,
            "large_model": self.large_model.model,
        }
        self.memory.setdefault("sessions", []).append(entry)
        self.memory["sessions"] = self.memory["sessions"][-20:]
        self._save_memory()

    def _memory_summary(self) -> str:
        sessions = self.memory.get("sessions", [])
        if not sessions:
            return ""
        lines = []
        for s in sessions[-5:]:
            ts = s.get('timestamp', '')
            g = s.get('goal', '')
            nd = len(s.get('selected_dorks', []))
            nf = s.get('findings_count', 0)
            lines.append(f"- {ts}: {g} — {nd} dorks, {nf} results")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Browser instructions
    # ------------------------------------------------------------------

    def _build_browser_instructions(self, goal: str, backend: str) -> str:
        specific = _BROWSER_INSTRUCTIONS.get(backend, "Use the configured browser backend.")
        parts = [
            f"Search goal: {goal}",
            f"Browser backend: {backend}",
            f"Instructions: {specific}",
        ]
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Tool registry
    # ------------------------------------------------------------------

    def _make_tool_registry(self, all_dorks: List[str]) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(make_filter_dorks_tool(all_dorks))
        registry.register(make_get_dork_categories_tool(all_dorks))
        if hasattr(self.large_model, "generate"):
            registry.register(make_expand_query_tool(self.large_model.generate))
        return registry

    # ------------------------------------------------------------------
    # Dork selection
    # ------------------------------------------------------------------

    def ask_goal(self) -> str:
        prompt = (
            "You are a small reasoning model that asks a human for a clear search objective. "
            "Ask for a concise target and clarify the category of sites the user wants to find. "
            "Do not perform any searches yet."
        )
        return self.small_model.generate(prompt).strip() or (
            "Find interesting and notable web pages using Google dorks."
        )

    def select_dorks_with_reasoning(
        self,
        goal: str,
        dorks: List[str],
        max_selections: int = 10,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> tuple[List[str], str]:
        """Ask the LLM to choose the best dorks and explain its reasoning."""
        backend = getattr(self.searcher, "backend", "playwright")
        browser_instr = _BROWSER_INSTRUCTIONS.get(backend, "")
        memory_summary = self._memory_summary()
        registry = self._make_tool_registry(dorks)

        prompt_parts = [
            "You are a search planning agent.",
            f"Goal: {goal}",
            "",
            f"Browser backend: {backend}",
            f"Browser instructions: {browser_instr}",
            "",
        ]
        if memory_summary:
            prompt_parts += [
                "Recent session history (avoid repeating low-value choices):",
                memory_summary,
                "",
            ]
        prompt_parts += [
            registry.prompt_section(),
            "",
            "Select the most relevant dorks from the list below.",
            "You MAY call filter_dorks_by_topic or get_dork_categories first to",
            "narrow the list, then respond with JSON:",
            '  {\"reasoning\": \"...\", \"dorks\": [\"dork1\", \"dork2\"]}',
            "",
            "Available dorks:",
        ]
        prompt_parts += dorks + ["", f"Choose up to {max_selections} dorks."]
        prompt = "\n".join(prompt_parts)

        if hasattr(self.large_model, "generate_stream"):
            raw = self.large_model.generate_stream(prompt, on_token=on_token)
            registry.execute_from_text(raw)
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                cleaned = "\n".join(inner)
            try:
                response = json.loads(cleaned)
            except json.JSONDecodeError:
                response = raw
        elif hasattr(self.large_model, "generate_json"):
            response = self.large_model.generate_json(prompt)
        else:
            raw = self.large_model.generate(prompt)
            registry.execute_from_text(raw)
            try:
                response = json.loads(raw)
            except json.JSONDecodeError:
                response = raw

        reasoning = ""
        selected: List[str] = []

        if isinstance(response, dict):
            reasoning = str(response.get("reasoning", "")).strip()
            raw_dorks = response.get("dorks", [])
            if isinstance(raw_dorks, str):
                raw_dorks = [ln.strip() for ln in raw_dorks.splitlines() if ln.strip()]
            for dork in raw_dorks:
                if isinstance(dork, str):
                    candidate = dork.strip().strip('"').strip("'")
                    if candidate in dorks and candidate not in selected:
                        selected.append(candidate)
        elif isinstance(response, str):
            registry.execute_from_text(response)
            for line in response.splitlines():
                candidate = line.strip().strip('"').strip("'")
                if candidate in dorks and candidate not in selected:
                    selected.append(candidate)

        if not selected:
            selected = dorks[:max_selections]
            if not reasoning:
                reasoning = "Fell back to top dorks — LLM response could not be parsed."

        return selected[:max_selections], reasoning

    def explain_selected_dorks(
        self,
        goal: str,
        selected_dorks: List[str],
        on_token: Optional[Callable[[str], None]] = None,
    ) -> str:
        backend = getattr(self.searcher, "backend", "playwright")
        browser_instr = _BROWSER_INSTRUCTIONS.get(backend, "")
        prompt_parts = [
            "You are a search reasoning assistant.",
            f"Goal: {goal}",
            f"Browser backend: {backend} — {browser_instr}",
            "",
            "The user selected these dorks:",
            *selected_dorks,
            "",
            "Explain why each dork is a strong match for the goal.",
            "Return only the reasoning text.",
        ]
        prompt = "\n".join(prompt_parts)
        if hasattr(self.large_model, "generate_stream"):
            return self.large_model.generate_stream(prompt, on_token=on_token)
        if hasattr(self.large_model, "generate_json"):
            resp = self.large_model.generate_json(prompt)
            if isinstance(resp, dict):
                return str(resp.get("reasoning", "")).strip()
            return str(resp).strip()
        return self.large_model.generate(prompt).strip()

    # ------------------------------------------------------------------
    # Sub-agent orchestration
    # ------------------------------------------------------------------

    def run_sub_agents(
        self,
        goal: str,
        selected_dorks: List[str],
        max_workers: int = 5,
        max_crawl: int = 0,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Wave-1: search each dork concurrently.  Wave-2: crawl result URLs."""
        backend = getattr(self.searcher, "backend", "playwright")
        browser_instructions = self._build_browser_instructions(goal, backend)

        # ---- Wave 1: parallel dork searches ----------------------------
        search_agents = [
            SearchSubAgent(
                dork=dork,
                goal=goal,
                searcher=self.searcher,
                browser_instructions=browser_instructions,
                tab_id=i,
            )
            for i, dork in enumerate(selected_dorks)
        ]

        if progress_callback:
            progress_callback("wave1_start", {"total": len(search_agents)})

        # Notify UI so it can open each search URL in the user's real browser
        if progress_callback:
            for i, dork in enumerate(selected_dorks):
                search_url = GOOGLE_SEARCH_URL.format(query=urllib.parse.quote_plus(dork))
                progress_callback("browser_open", {
                    "search_id": i,
                    "dork": dork,
                    "search_url": search_url,
                })

        tab_results: Dict[int, Dict[str, Any]] = {}
        workers = min(max_workers, max(len(search_agents), 1))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(agent.run): agent for agent in search_agents}
            for future in as_completed(futures):
                sub = future.result()
                tab_results[sub["tab_id"]] = sub
                if progress_callback:
                    progress_callback("search_tab_done", sub)

        # Collect in original dork order
        findings: List[Dict[str, Any]] = [
            {
                "query": tab_results.get(i, {}).get("dork", dork),
                "results": tab_results.get(i, {}).get("results", []),
                "elapsed": tab_results.get(i, {}).get("elapsed", 0),
                "error": tab_results.get(i, {}).get("error"),
            }
            for i, dork in enumerate(selected_dorks)
        ]

        # Deduplicate URLs and produce paginated list
        seen_urls: set = set()
        all_urls: List[Dict[str, str]] = []
        for item in findings:
            for r in item.get("results", []):
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_urls.append(
                        {
                            "url": url,
                            "title": r.get("title", ""),
                            "snippet": r.get("snippet", "") or "",
                        }
                    )
        url_pages = paginate(all_urls, page_size=10)

        # ---- Wave 2: parallel URL crawls (optional) --------------------
        crawl_results: List[Dict[str, Any]] = []
        if max_crawl > 0 and all_urls:
            crawl_agents = [
                CrawlSubAgent(
                    url=item["url"],
                    title=item.get("title", ""),
                    goal=goal,
                    searcher=self.searcher,
                    llm=self.small_model,
                    tab_id=i,
                )
                for i, item in enumerate(all_urls[:max_crawl])
            ]

            if progress_callback:
                progress_callback("wave2_start", {"total": len(crawl_agents)})

            workers = min(max_workers, max(len(crawl_agents), 1))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(agent.run): agent for agent in crawl_agents}
                for future in as_completed(futures):
                    cr = future.result()
                    crawl_results.append(cr)
                    if progress_callback:
                        progress_callback("crawl_tab_done", cr)

            crawl_results.sort(
                key=lambda r: (
                    _RELEVANCE_ORDER.get(r.get("relevance", "unknown"), 3),
                    r.get("tab_id", 0),
                )
            )

        return {
            "goal": goal,
            "browser_instructions": browser_instructions,
            "findings": findings,
            "paginated_urls": url_pages,
            "all_urls": all_urls,
            "crawl_results": crawl_results,
        }

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def search_with_selected_dorks(
        self,
        goal: str,
        selected_dorks: List[str],
        max_selections: int = 10,
        max_crawl: int = 0,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        def _emit(event: str, data: Dict[str, Any]) -> None:
            if progress_callback:
                progress_callback(event, data)

        if not selected_dorks:
            _emit("planning", {"message": "Selecting dorks with AI reasoning…"})
            dorks = load_dorks(self.dork_file)
            on_token = lambda tok: _emit("stream_token", {"token": tok})  # noqa: E731
            selected_dorks, reasoning = self.select_dorks_with_reasoning(
                goal, dorks, max_selections, on_token=on_token
            )
        else:
            # User already chose the dorks — skip expensive LLM explanation,
            # go straight to searching so results appear quickly.
            selected_dorks = selected_dorks[:max_selections]
            reasoning = ""

        sub = self.run_sub_agents(
            goal, selected_dorks, max_crawl=max_crawl, progress_callback=progress_callback
        )
        self._record_memory(goal, selected_dorks, reasoning, sub["findings"])

        return {
            "goal": goal,
            "selected_dorks": selected_dorks,
            "reasoning": reasoning,
            "findings": sub["findings"],
            "paginated_urls": sub["paginated_urls"],
            "all_urls": sub["all_urls"],
            "crawl_results": sub["crawl_results"],
            "memory_summary": self._memory_summary(),
        }

    def run(self, max_selections: int = 10, max_crawl: int = 0) -> Dict[str, Any]:
        goal = self.goal or self.ask_goal()
        dorks = load_dorks(self.dork_file)
        selected_dorks, reasoning = self.select_dorks_with_reasoning(
            goal, dorks, max_selections
        )
        sub = self.run_sub_agents(goal, selected_dorks, max_crawl=max_crawl)

        write_review(
            self.review_path,
            goal,
            selected_dorks,
            sub["findings"],
            metadata={
                "small_model": self.small_model.model,
                "large_model": self.large_model.model,
                "browser_backend": getattr(self.searcher, "backend", "unknown"),
            },
            reasoning=reasoning,
        )
        self._record_memory(goal, selected_dorks, reasoning, sub["findings"])

        return {
            "goal": goal,
            "selected_dorks": selected_dorks,
            "reasoning": reasoning,
            "findings": sub["findings"],
            "paginated_urls": sub["paginated_urls"],
            "all_urls": sub["all_urls"],
            "crawl_results": sub["crawl_results"],
            "review_path": str(self.review_path),
            "memory_summary": self._memory_summary(),
        }
