import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import (
    DATA_DIR,
    REMOTE_DORK_CACHE,
    SOURCE_LIST_FILE,
    SLOW_CRAWL_PROGRESS_FILE,
    SLOW_CRAWL_DORKS_FILE,
)

DEFAULT_SOURCE_URLS = [
    "https://www.exploit-db.com/google-hacking-database",
]

PATTERN_KEYWORDS = [
    "filetype:",
    "inurl:",
    "intitle:",
    "site:",
    "intext:",
    "allinurl:",
    "allintitle:",
    "cache:",
    "ext:",
    "link:",
]


def load_source_urls() -> List[str]:
    if SOURCE_LIST_FILE.exists():
        try:
            data = json.loads(SOURCE_LIST_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(item) for item in data if isinstance(item, str)]
        except json.JSONDecodeError:
            pass
    return DEFAULT_SOURCE_URLS.copy()


def save_source_urls(urls: List[str]) -> None:
    SOURCE_LIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_LIST_FILE.write_text(json.dumps(urls, indent=2), encoding="utf-8")


def fetch_source(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def parse_dorks_from_text(text: str) -> List[str]:
    dorks: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lower_line = line.lower()
        if any(keyword in lower_line for keyword in PATTERN_KEYWORDS) and len(line) < 240:
            dorks.append(line)
    return dorks


def parse_dorks_from_html(html: str) -> List[str]:
    found = re.findall(
        r">([^<]*(?:filetype:|inurl:|intitle:|site:|intext:|allinurl:|allintitle:|cache:|ext:|link:)[^<]*)<",
        html,
        flags=re.IGNORECASE,
    )
    return [item.strip() for item in found if item.strip()]


def _create_selenium_driver() -> Any:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError as exc:
        raise RuntimeError("Selenium is required for rendering Exploit-DB pages. Install selenium first.") from exc

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=options)


def crawl_exploit_db_pages(
    base_url: str,
    max_pages: int = 67,
    wait_seconds: int = 6,
    show_realtime: bool = False,
    stop_after: Optional[int] = None,
    batch_size: int = 0,
    batch_delay: int = 0,
    progress_file: Optional[Path] = None,
    dork_log_file: Optional[Path] = None,
) -> List[str]:
    try:
        from selenium.webdriver.common.by import By
    except ImportError:
        raise RuntimeError("Selenium is required to crawl Exploit-DB paginated dorks.")

    def write_progress(page: int, total_pages: int, count: int, status: str = "running") -> None:
        if not progress_file:
            return
        progress_file.parent.mkdir(parents=True, exist_ok=True)
        progress_file.write_text(
            json.dumps(
                {
                    "status": status,
                    "current_page": page,
                    "total_pages": total_pages,
                    "dorks_found": count,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def append_dork(dork_text: str) -> None:
        if not dork_log_file:
            return
        dork_log_file.parent.mkdir(parents=True, exist_ok=True)
        with dork_log_file.open("a", encoding="utf-8") as handle:
            handle.write(dork_text + "\n")

    driver = _create_selenium_driver()
    dorks: List[str] = []
    try:
        driver.get(base_url)
        time.sleep(wait_seconds)

        for page_index in range(max_pages):
            current_page = page_index + 1
            rows = driver.find_elements(By.CSS_SELECTOR, "#exploits-table tbody tr")
            if show_realtime:
                print(f"[Crawl] Page {current_page}/{max_pages} - found {len(rows)} rows")

            for row in rows:
                if stop_after is not None and len(dorks) >= stop_after:
                    break
                try:
                    dork_link = row.find_element(By.CSS_SELECTOR, "td:nth-child(2) a[href^='/ghdb/']")
                    dork_text = (
                        dork_link.get_attribute("innerText")
                        or dork_link.get_attribute("textContent")
                        or ""
                    ).strip()
                    if dork_text:
                        if show_realtime:
                            print(f"  [Page {current_page}] {dork_text}")
                        dorks.append(dork_text)
                        append_dork(dork_text)
                except Exception:
                    continue

            write_progress(current_page, max_pages, len(dorks))
            if stop_after is not None and len(dorks) >= stop_after:
                if show_realtime:
                    print(f"Reached target of {stop_after} dorks.")
                break

            next_buttons = driver.find_elements(By.CSS_SELECTOR, "ul.pagination li.next:not(.disabled) a")
            if not next_buttons:
                if show_realtime:
                    print("No more pages available.")
                break

            if show_realtime:
                print(f"Pausing for {wait_seconds} seconds before next page...")
            time.sleep(wait_seconds)

            next_button = next_buttons[0]
            try:
                next_button.click()
            except Exception:
                driver.execute_script("arguments[0].click();", next_button)

            if batch_size and current_page % batch_size == 0:
                if show_realtime:
                    print(f"Batch completed. Pausing for {batch_delay} seconds...")
                time.sleep(batch_delay)

            time.sleep(wait_seconds)

        write_progress(current_page, max_pages, len(dorks), status="complete")
        return dorks
    finally:
        driver.quit()


def normalize_dorks(dorks: List[str]) -> List[str]:
    unique: Dict[str, None] = {}
    for dork in dorks:
        normalized = " ".join(dork.split())
        if normalized and normalized not in unique:
            unique[normalized] = None
    return list(unique.keys())


def load_remote_cache() -> List[str]:
    if REMOTE_DORK_CACHE.exists():
        with REMOTE_DORK_CACHE.open("r", encoding="utf-8") as handle:
            return [line.strip() for line in handle if line.strip()]
    return []


def refresh_remote_sources(urls: Optional[List[str]] = None) -> List[str]:
    urls = urls or load_source_urls()
    collected: List[str] = []
    for source_url in urls:
        try:
            if "exploit-db.com/google-hacking-database" in source_url:
                collected.extend(crawl_exploit_db_pages(source_url))
            else:
                content = fetch_source(source_url)
                collected.extend(parse_dorks_from_text(content))
                collected.extend(parse_dorks_from_html(content))
        except urllib.error.URLError:
            continue
        except Exception:
            continue

    dorks = normalize_dorks(collected)
    REMOTE_DORK_CACHE.parent.mkdir(parents=True, exist_ok=True)
    REMOTE_DORK_CACHE.write_text("\n".join(dorks), encoding="utf-8")
    return dorks
