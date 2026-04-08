import json
from pathlib import Path
from typing import Any, Dict

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
SETTINGS_FILE = ROOT_DIR / "dork_agent" / "settings.json"
SOURCE_LIST_FILE = DATA_DIR / "dork_sources.json"
REMOTE_DORK_CACHE = DATA_DIR / "remote_dorks.txt"
DEFAULT_DORK_FILE = DATA_DIR / "google_hacking_database.txt"
REVIEW_FILE = ROOT_DIR / "review.md"
AGENT_MEMORY_FILE = DATA_DIR / "agent_memory.json"
SLOW_CRAWL_PROGRESS_FILE = DATA_DIR / "slow_crawl_progress.json"
SLOW_CRAWL_DORKS_FILE = DATA_DIR / "slow_crawl_dorks.txt"
DEFAULT_SMALL_MODEL = "llama2-mini"
DEFAULT_LARGE_MODEL = "llama2"
DEFAULT_BROWSER_BACKEND = "playwright"
DEFAULT_MAX_RESULTS = 5
GOOGLE_SEARCH_URL = "https://www.google.com/search?q={query}"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "small_model": DEFAULT_SMALL_MODEL,
    "large_model": DEFAULT_LARGE_MODEL,
    "browser_backend": DEFAULT_BROWSER_BACKEND,
    "dork_file": str(DEFAULT_DORK_FILE),
    "review_path": str(REVIEW_FILE),
    "max_results": DEFAULT_MAX_RESULTS,
}


def load_settings() -> Dict[str, Any]:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: Dict[str, Any]) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def load_agent_memory() -> Dict[str, Any]:
    if AGENT_MEMORY_FILE.exists():
        try:
            return json.loads(AGENT_MEMORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"sessions": []}


def save_agent_memory(memory: Dict[str, Any]) -> None:
    AGENT_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    AGENT_MEMORY_FILE.write_text(json.dumps(memory, indent=2), encoding="utf-8")
