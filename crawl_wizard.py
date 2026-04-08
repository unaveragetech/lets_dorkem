import json
import sys
from pathlib import Path
from typing import Optional

from dork_agent.config import SLOW_CRAWL_DORKS_FILE, SLOW_CRAWL_PROGRESS_FILE
from dork_agent.source import crawl_exploit_db_pages


def prompt(text: str, default: str) -> str:
    answer = input(f"{text} [{default}]: ").strip()
    return answer or default


def prompt_int(text: str, default: int) -> int:
    answer = input(f"{text} [{default}]: ").strip()
    if not answer:
        return default
    try:
        return int(answer)
    except ValueError:
        print("Invalid number; using default.")
        return default


def prompt_choice(text: str, choices: list[str], default: str) -> str:
    choices_text = "/".join(choices)
    answer = input(f"{text} ({choices_text}) [{default}]: ").strip().lower()
    if not answer:
        return default
    if answer in choices:
        return answer
    print(f"Invalid choice: {answer}. Using default {default}.")
    return default


def main() -> None:
    print("=== Google Dork Slow Crawl Wizard ===\n")

    base_url = prompt(
        "Enter the Google Hacking Database page to crawl",
        "https://www.exploit-db.com/google-hacking-database",
    )
    crawl_mode = prompt_choice("Crawl by pages or entries", ["pages", "entries"], "pages")

    if crawl_mode == "pages":
        max_pages = prompt_int("How many pages should the crawler fetch", 10)
        stop_after = None
    else:
        max_entries = prompt_int("How many total dork entries should the crawler retrieve", 1200)
        max_pages = 67
        stop_after = max_entries

    per_page_delay = prompt_int("Seconds to pause after each page", 5)
    batch_size = prompt_int("Pause after how many pages for a longer break (0 to disable)", 2)
    batch_delay = 0
    if batch_size > 0:
        batch_delay = prompt_int("Longer pause duration in seconds", 15)

    print("\nStarting slow crawl. Press Ctrl+C to stop gracefully.\n")

    progress = {
        "status": "running",
        "current_page": 0,
        "total_pages": max_pages,
        "dorks_found": 0,
    }
    SLOW_CRAWL_PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SLOW_CRAWL_PROGRESS_FILE.write_text(json.dumps(progress, indent=2), encoding="utf-8")
    SLOW_CRAWL_DORKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SLOW_CRAWL_DORKS_FILE.write_text("", encoding="utf-8")

    try:
        dorks = crawl_exploit_db_pages(
            base_url=base_url,
            max_pages=max_pages,
            wait_seconds=per_page_delay,
            show_realtime=True,
            stop_after=stop_after,
            batch_size=batch_size,
            batch_delay=batch_delay,
            progress_file=SLOW_CRAWL_PROGRESS_FILE,
            dork_log_file=SLOW_CRAWL_DORKS_FILE,
        )
    except KeyboardInterrupt:
        print("\nCrawl interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        print(f"Crawl failed: {exc}")
        sys.exit(1)

    print(f"\nCrawl complete. Extracted {len(dorks)} dorks.")

    # Append newly found dorks to the main dork database file so they
    # persist permanently even if slow_crawl_dorks.txt is cleared later.
    main_db = Path(__file__).resolve().parent / "data" / "google_hacking_database.txt"
    try:
        existing = set()
        if main_db.exists():
            existing = {ln.strip() for ln in main_db.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")}
        new_dorks = [d for d in dorks if d not in existing]
        if new_dorks:
            main_db.parent.mkdir(parents=True, exist_ok=True)
            with main_db.open("a", encoding="utf-8") as f:
                f.write("\n" + "\n".join(new_dorks) + "\n")
            print(f"Saved {len(new_dorks)} new dorks to {main_db.name} ({len(existing)} already existed).")
        else:
            print(f"All {len(dorks)} dorks already present in {main_db.name}.")
    except Exception as exc:
        print(f"Warning: could not update main dork database: {exc}")

    show_list = input("\nPrint all dork entries? (y/N): ").strip().lower()
    if show_list == 'y':
        for index, dork in enumerate(dorks, start=1):
            print(f"{index}. {dork}")


if __name__ == "__main__":
    main()
