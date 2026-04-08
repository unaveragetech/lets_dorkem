"""Sub-agent classes for concurrent dork searching and URL crawling.

SearchSubAgent  — searches a single dork query in its own browser context.
CrawlSubAgent   — visits a specific URL and scores its relevance to the goal.

Both classes expose a blocking ``run()`` method so they can be dispatched
via ``concurrent.futures.ThreadPoolExecutor`` from the main DorkAgent.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .ollama_client import OllamaClient
    from .searcher import GoogleSearcher


class SearchSubAgent:
    """Searches a single dork query and returns structured results."""

    def __init__(
        self,
        dork: str,
        goal: str,
        searcher: "GoogleSearcher",
        browser_instructions: str = "",
        tab_id: int = 0,
    ) -> None:
        self.dork = dork
        self.goal = goal
        self.searcher = searcher
        self.browser_instructions = browser_instructions
        self.tab_id = tab_id

    def run(self) -> Dict[str, Any]:
        start = time.monotonic()
        try:
            results = self.searcher.search(self.dork)
            return {
                "tab_id": self.tab_id,
                "dork": self.dork,
                "results": results,
                "result_count": len(results),
                "elapsed": round(time.monotonic() - start, 2),
                "error": None,
                "status": "done",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "tab_id": self.tab_id,
                "dork": self.dork,
                "results": [],
                "result_count": 0,
                "elapsed": round(time.monotonic() - start, 2),
                "error": str(exc),
                "status": "error",
            }


class CrawlSubAgent:
    """Crawls a URL and evaluates its relevance to the research goal."""

    def __init__(
        self,
        url: str,
        title: str,
        goal: str,
        searcher: "GoogleSearcher",
        llm: Optional["OllamaClient"] = None,
        tab_id: int = 0,
    ) -> None:
        self.url = url
        self.title = title
        self.goal = goal
        self.searcher = searcher
        self.llm = llm
        self.tab_id = tab_id

    def run(self) -> Dict[str, Any]:
        start = time.monotonic()
        extracted = ""
        try:
            extracted = self.searcher.crawl_url(self.url)
        except Exception as exc:  # noqa: BLE001
            return {
                "tab_id": self.tab_id,
                "url": self.url,
                "title": self.title,
                "extracted": "",
                "summary": f"Crawl failed: {exc}",
                "relevance": "unknown",
                "elapsed": round(time.monotonic() - start, 2),
                "status": "error",
            }

        summary = ""
        relevance = "unknown"

        if self.llm and extracted:
            prompt = (
                f"Goal: {self.goal}\n"
                f"URL: {self.url}\n"
                f"Page content (excerpt):\n{extracted[:3000]}\n\n"
                "In ONE concise sentence, rate this page as HIGH / MEDIUM / LOW relevance "
                "and summarise the key finding related to the goal."
            )
            try:
                resp = self.llm.generate(prompt).strip()
                summary = resp
                low = resp.lower()
                if "high" in low:
                    relevance = "high"
                elif "medium" in low:
                    relevance = "medium"
                else:
                    relevance = "low"
            except Exception:  # noqa: BLE001
                pass

        return {
            "tab_id": self.tab_id,
            "url": self.url,
            "title": self.title,
            "extracted": extracted[:1000],
            "summary": summary,
            "relevance": relevance,
            "elapsed": round(time.monotonic() - start, 2),
            "status": "done",
        }


def paginate(items: List[Any], page_size: int) -> List[List[Any]]:
    """Split *items* into pages of *page_size*."""
    return [items[i : i + page_size] for i in range(0, len(items), page_size)]
