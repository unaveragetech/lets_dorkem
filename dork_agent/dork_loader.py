from pathlib import Path
from typing import List, Optional, Union
from .config import DEFAULT_DORK_FILE, SLOW_CRAWL_DORKS_FILE
from .source import load_remote_cache


def _load_local_file(path: Path) -> List[str]:
    dorks: List[str] = []
    if not path.exists():
        return dorks

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            dorks.append(line)

    return dorks


def load_dorks(path: Optional[Union[str, Path]] = None, include_remote: bool = True) -> List[str]:
    dork_file = Path(path) if path else DEFAULT_DORK_FILE
    dorks = _load_local_file(dork_file)

    # Also load from slow crawl dorks file if it exists
    if SLOW_CRAWL_DORKS_FILE.exists():
        dorks.extend(_load_local_file(SLOW_CRAWL_DORKS_FILE))

    if include_remote:
        dorks.extend(load_remote_cache())

    unique = list(dict.fromkeys(dorks))
    return unique
