import argparse
from typing import List, Optional

from dork_agent.agent import DorkAgent
from dork_agent.dork_loader import load_dorks
from dork_agent.source import load_source_urls, refresh_remote_sources


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Google Dork automation agent and manage Google dork sources."
    )
    parser.add_argument("--goal", help="Search objective for the dork agent.", default=None)
    parser.add_argument(
        "--dork-file",
        help="Path to the Google dork dataset file.",
        default=None,
    )
    parser.add_argument(
        "--review-path",
        help="Path to write the generated review markdown.",
        default=None,
    )
    parser.add_argument(
        "--small-model",
        help="Local Ollama model name used for intent reasoning.",
        default=None,
    )
    parser.add_argument(
        "--large-model",
        help="Local Ollama model name used for dork selection and planning.",
        default=None,
    )
    parser.add_argument(
        "--browser-backend",
        help="Browser automation backend: playwright or selenium.",
        choices=["playwright", "selenium"],
        default=None,
    )
    parser.add_argument(
        "--max-selections",
        help="Maximum number of dorks to select and search.",
        type=int,
        default=8,
    )
    parser.add_argument(
        "--refresh-sources",
        action="store_true",
        help="Download and cache dorks from configured remote sources.",
    )
    parser.add_argument(
        "--browse-dorks",
        action="store_true",
        help="Browse available dorks from local and remote sources.",
    )
    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="List configured remote dork source URLs.",
    )
    parser.add_argument(
        "--filter",
        help="Filter dorks by keyword when browsing.",
        default=None,
    )
    parser.add_argument(
        "--limit",
        help="Maximum number of dorks to print when browsing.",
        type=int,
        default=100,
    )
    return parser.parse_args()


def browse_dorks(filter_text: Optional[str], limit: int) -> None:
    dorks = load_dorks(include_remote=True)
    if filter_text:
        filter_lower = filter_text.lower()
        dorks = [d for d in dorks if filter_lower in d.lower()]

    print(f"Loaded {len(dorks)} dorks from local and remote sources.")
    if not dorks:
        print("No dorks matched the filter.")
        return

    for index, dork in enumerate(dorks[:limit], start=1):
        print(f"{index}. {dork}")
    if len(dorks) > limit:
        print(f"...and {len(dorks) - limit} more dorks. Use --limit to increase output.")


def main() -> None:
    args = parse_args()

    if args.list_sources:
        urls = load_source_urls()
        print("Configured remote source URLs:")
        for url in urls:
            print(f"- {url}")
        return

    if args.refresh_sources:
        sources = load_source_urls()
        print(f"Refreshing {len(sources)} remote source(s)...")
        refresh_remote_sources(sources)
        print("Remote source refresh complete.")
        return

    if args.browse_dorks:
        browse_dorks(args.filter, args.limit)
        return

    agent = DorkAgent(
        goal=args.goal,
        dork_file=args.dork_file,
        small_model=args.small_model,
        large_model=args.large_model,
        backend=args.browser_backend,
        review_path=args.review_path,
        max_results=args.max_selections,
    )
    result = agent.run(max_selections=args.max_selections)
    print("Agent completed.")
    print(f"Review written to: {result['review_path']}")
    print(f"Selected {len(result['selected_dorks'])} dorks.")


if __name__ == "__main__":
    main()
