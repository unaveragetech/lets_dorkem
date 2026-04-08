import asyncio
import json
import random
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional
from .config import GOOGLE_SEARCH_URL, DEFAULT_MAX_RESULTS, DEFAULT_BROWSER_BACKEND

# browser-use uses asyncio internally and cannot run concurrently across threads
# (tasks/futures get bound to a single event loop). Serialise all browser-use
# invocations with this lock so each asyncio.run() gets a clean, exclusive loop.
_BROWSER_USE_LOCK = threading.Lock()


class SearchResult:
    def __init__(self, title: str, url: str, snippet: Optional[str] = None) -> None:
        self.title = title
        self.url = url
        self.snippet = snippet

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class GoogleSearcher:
    def __init__(self, backend: Optional[str] = None, max_results: Optional[int] = None) -> None:
        self.backend = backend or DEFAULT_BROWSER_BACKEND
        self.max_results = max_results or DEFAULT_MAX_RESULTS

    def search(self, query: str, max_results: Optional[int] = None) -> List[Dict[str, Optional[str]]]:
        target = max_results or self.max_results
        if self.backend == "native":
            return self._search_with_requests(query, target)
        if self.backend == "browser-use":
            try:
                return self._search_with_browser_use(query, target)
            except Exception as exc:
                print(f"Browser-use search failed: {exc}. Falling back to playwright or selenium.")
                try:
                    return self._search_with_playwright(query, target)
                except Exception:
                    return self._search_with_selenium(query, target)
        if self.backend == "playwright":
            try:
                return self._search_with_playwright(query, target)
            except ImportError:
                return self._search_with_selenium(query, target)
        return self._search_with_selenium(query, target)

    def _search_with_requests(self, query: str, max_results: int) -> List[Dict[str, Optional[str]]]:
        """Fetch Google results via plain HTTP requests — no headless browser, no automation flags."""
        import requests as _requests
        import time as _time
        import random as _random

        url = GOOGLE_SEARCH_URL.format(query=urllib.parse.quote_plus(query))
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.google.com/",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
        _time.sleep(_random.uniform(1.0, 2.5))
        session = _requests.Session()
        try:
            resp = session.get(url, headers=headers, timeout=20, allow_redirects=True)
            return self._parse_google_html(resp.text, max_results)
        except Exception:
            return []

    def _parse_google_html(self, html: str, max_results: int) -> List[Dict[str, Optional[str]]]:
        """Parse Google search result HTML using stdlib only (no external parser)."""
        import re

        if "unusual traffic" in html or "recaptcha" in html.lower():
            return []

        results: List[Dict[str, Optional[str]]] = []
        seen_urls: set = set()

        # Walk every <h3> in the document; look back up to 2 KB for a parent <a href=>
        for h3_m in re.finditer(r'<h3[\s>]', html):
            if len(results) >= max_results:
                break
            h3_pos = h3_m.start()
            lookback = html[max(0, h3_pos - 2000):h3_pos]
            href_matches = list(re.finditer(r'<a\s[^>]*href="([^"]+)"', lookback))
            if not href_matches:
                continue
            href = href_matches[-1].group(1)

            # Resolve redirect or direct URL
            if href.startswith('/url?'):
                q_m = re.search(r'[?&]q=(https?://[^&]+)', href)
                url: Optional[str] = urllib.parse.unquote(q_m.group(1)) if q_m else None
            elif href.startswith('http://') or href.startswith('https://'):
                url = href
            else:
                continue

            if not url or url in seen_urls:
                continue
            if 'google.com' in url:
                continue
            seen_urls.add(url)

            h3_end = html.find('</h3>', h3_pos)
            if h3_end == -1:
                continue
            title = re.sub(r'<[^>]+>', '', html[h3_pos:h3_end + 5]).strip()
            if not title or len(title) < 3:
                continue

            # Snippet: first substantial <span> after the h3
            ctx = html[h3_end:h3_end + 1200]
            snip_m = re.search(r'<span[^>]*>([\w][^<]{20,300})</span>', ctx)
            snippet: Optional[str] = re.sub(r'<[^>]+>', '', snip_m.group(1)).strip()[:280] if snip_m else None

            results.append(SearchResult(title, url, snippet).to_dict())

        return results

    def _search_with_browser_use(self, query: str, max_results: int) -> List[Dict[str, Optional[str]]]:
        try:
            from browser_use import BrowserSession
        except ImportError as exc:
            raise ImportError("browser-use is not installed. Install it with pip install browser-use") from exc

        async def run_search() -> List[Dict[str, Optional[str]]]:
            url = GOOGLE_SEARCH_URL.format(query=urllib.parse.quote_plus(query))
            session = BrowserSession(headless=True, user_agent=self._user_agent())
            await session.start()
            page = await session.new_page(url)
            await asyncio.sleep(random.uniform(2.0, 4.0))
            script = (
                "(max_results) => {"
                " const results = [];"
                " const blocks = Array.from(document.querySelectorAll('div.g'));"
                " for (const block of blocks) {"
                "   const link = block.querySelector('a');"
                "   const titleEl = block.querySelector('h3');"
                "   const snippetEl = block.querySelector('.VwiC3b, .aCOpRe, span');"
                "   if (!link || !titleEl) continue;"
                "   results.push({"
                "       title: titleEl.innerText.trim(),"
                "       url: link.href || '',"
                "       snippet: snippetEl ? snippetEl.innerText.trim() : null," 
                "   });"
                "   if (results.length >= max_results) break;"
                " }"
                " return JSON.stringify(results);"
                "}"
            )
            raw = await page.evaluate(script, max_results)
            await session.stop()
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []

        with _BROWSER_USE_LOCK:
            return asyncio.run(run_search())

    def _search_with_playwright(self, query: str, max_results: int) -> List[Dict[str, Optional[str]]]:
        from playwright.sync_api import sync_playwright

        url = GOOGLE_SEARCH_URL.format(query=urllib.parse.quote_plus(query))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self._user_agent())
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(random.uniform(2.0, 4.0))
            return self._extract_google_results(page, max_results)

    def _search_with_selenium(self, query: str, max_results: int) -> List[Dict[str, Optional[str]]]:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument(f"user-agent={self._user_agent()}")
        driver = webdriver.Chrome(options=options)
        try:
            url = GOOGLE_SEARCH_URL.format(query=urllib.parse.quote_plus(query))
            driver.get(url)
            time.sleep(random.uniform(2.0, 4.0))
            return self._extract_google_results_selenium(driver, max_results)
        finally:
            driver.quit()

    def _extract_google_results(self, page: Any, max_results: int) -> List[Dict[str, Optional[str]]]:
        entries = page.query_selector_all("div.g")
        results: List[Dict[str, Optional[str]]] = []

        for entry in entries:
            if len(results) >= max_results:
                break
            link_element = entry.query_selector("a")
            title_element = entry.query_selector("h3")
            snippet_element = entry.query_selector(".VwiC3b") or entry.query_selector("span.aCOpRe")
            if not link_element or not title_element:
                continue
            title = title_element.inner_text().strip()
            url = link_element.get_attribute("href") or ""
            snippet = snippet_element.inner_text().strip() if snippet_element else None
            results.append(SearchResult(title, url, snippet).to_dict())

        return results

    def _extract_google_results_selenium(self, driver: Any, max_results: int) -> List[Dict[str, Optional[str]]]:
        from selenium.webdriver.common.by import By

        containers = driver.find_elements(By.CSS_SELECTOR, "div.g")
        results: List[Dict[str, Optional[str]]] = []

        for container in containers:
            if len(results) >= max_results:
                break
            try:
                title_el = container.find_element(By.CSS_SELECTOR, "h3")
                link_el = container.find_element(By.CSS_SELECTOR, "a")
                snippet_el = None
                try:
                    snippet_el = container.find_element(By.CSS_SELECTOR, ".VwiC3b, span.aCOpRe")
                except Exception:
                    snippet_el = None
                title = title_el.text.strip()
                url = link_el.get_attribute("href") or ""
                snippet = snippet_el.text.strip() if snippet_el else None
                results.append(SearchResult(title, url, snippet).to_dict())
            except Exception:
                continue

        return results

    def _user_agent(self) -> str:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )

    # ------------------------------------------------------------------
    # URL crawling (wave-2 sub-agents visit individual result pages)
    # ------------------------------------------------------------------

    def _crawl_with_requests(self, url: str, max_chars: int) -> str:
        """Crawl a URL using plain HTTP requests — strips HTML tags for text content."""
        import re
        import requests as _requests

        headers = {
            "User-Agent": self._user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }
        try:
            resp = _requests.get(url, headers=headers, timeout=15)
            text = re.sub(r'<script[^>]*>.*?</script>', ' ', resp.text, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'&[a-zA-Z#0-9]+;', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:max_chars]
        except Exception:
            return ""

    def crawl_url(self, url: str, max_chars: int = 8000) -> str:
        """Fetch *url* and return its visible text content (truncated to *max_chars*)."""
        if self.backend == "native":
            return self._crawl_with_requests(url, max_chars)
        if self.backend == "browser-use":
            try:
                return self._crawl_with_browser_use(url, max_chars)
            except Exception:
                pass
        if self.backend in ("playwright", "browser-use"):
            try:
                return self._crawl_with_playwright(url, max_chars)
            except ImportError:
                pass
        return self._crawl_with_selenium(url, max_chars)

    def _crawl_with_playwright(self, url: str, max_chars: int) -> str:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self._user_agent())
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            text = page.evaluate(
                "() => document.body ? document.body.innerText : ''"
            )
            browser.close()
        return (text or "")[:max_chars]

    def _crawl_with_selenium(self, url: str, max_chars: int) -> str:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument(f"user-agent={self._user_agent()}")
        driver = webdriver.Chrome(options=options)
        try:
            driver.get(url)
            text = driver.execute_script(
                "return document.body ? document.body.innerText : '';"
            )
        finally:
            driver.quit()
        return (text or "")[:max_chars]

    def _crawl_with_browser_use(self, url: str, max_chars: int) -> str:
        try:
            from browser_use import BrowserSession
        except ImportError as exc:
            raise ImportError("browser-use is not installed.") from exc

        async def run_crawl() -> str:
            session = BrowserSession(headless=True, user_agent=self._user_agent())
            await session.start()
            page = await session.new_page(url)
            import asyncio
            await asyncio.sleep(2.0)
            raw = await page.evaluate(
                "() => JSON.stringify(document.body ? document.body.innerText : '')"
            )
            await session.stop()
            import json as _json
            return _json.loads(raw) if raw else ""

        with _BROWSER_USE_LOCK:
            return asyncio.run(run_crawl())[:max_chars]
