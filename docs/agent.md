# Agent Reference

`DorkAgent` lives in `dork_agent/agent.py`. It is the orchestration core — selecting dorks, running wave-1 searches, wave-2 crawls, and emitting structured progress events throughout.

---

## Constructor

```python
DorkAgent(
    goal: str,
    dorks: list[str],
    on_event: Callable[[dict], None],
    settings: dict | None = None
)
```

| Parameter | Default | Description |
|---|---|---|
| `goal` | required | Natural language goal provided by the user |
| `dorks` | required | Pre-selected dorks (or full library if none selected) |
| `on_event` | required | Callback fired for every progress event |
| `settings` | `{}` | Dict from `/api/settings`: `small_model`, `large_model`, `browser_backend`, `max_crawl` |

---

## Lifecycle

```
DorkAgent.run()
  │
  ├── maybe select_dorks_with_reasoning()   ← skipped if user pre-selected dorks
  │      uses small_model over Ollama stream
  │
  ├── explain_selected_dorks()              ← skipped if user pre-selected dorks
  │
  ├── run_sub_agents()  ← wave-1: search each selected dork
  │      for each dork:
  │        _search(dork)    ← dispatches to backend
  │        emit search_tab_done
  │
  └── run_sub_agents()  ← wave-2: crawl result URLs
         for each url:
           _crawl(url)      ← dispatches to backend
           emit crawl_tab_done
```

---

## Methods

### `select_dorks_with_reasoning(goal, dorks, max_selections, on_token)`

Prompts `small_model` with the goal and full dork list. Streams the response token-by-token, emits `stream_token` events. Parses the final accumulated JSON:

```json
{
  "selected_dorks": ["site:example.com filetype:pdf", ...],
  "reasoning": "These dorks match because..."
}
```

Falls back gracefully if JSON parsing fails (takes first `max_selections` dorks).

### `_search(dork)`

Dispatches to:
- `_search_with_requests()` when `browser_backend == "native"`
- `_search_with_selenium()` when `browser_backend == "selenium"`
- `_search_with_playwright()` when `browser_backend == "playwright"`
- `_search_with_browser_use()` when `browser_backend == "browser-use"`

Returns `list[dict]` with keys `title`, `url`, `snippet`.

### `_crawl(url)`

Fetches and extracts visible text from a URL. Emits content to the large model for relevance scoring.

### `paginate(results, page_size)`

Splits result list into pages. Used for the wave-2 crawl URL list in `renderAgentResults`.

---

## Progress Events

All events are dicts passed to `on_event`. The job store (`dork_agent/job_store.py`) accumulates them.

| `type` | When | Extra keys |
|---|---|---|
| `planning` | LLM dork selection starts | `phase: "planning"` |
| `stream_token` | Each token from the LLM stream | `token: str`, `accumulated: str` |
| `selection_done` | LLM finished selecting | `selected_dorks: list[str]`, `reasoning: str` |
| `wave1_start` | Wave-1 (search) begins | `total: int` |
| `search_tab_done` | One dork's search finished | `dork: str`, `results: list[dict]`, `tab_index: int`, `browser_urls: list[str]` |
| `wave2_start` | Wave-2 (crawl) begins | `total: int` |
| `crawl_tab_done` | One URL crawled | `url: str`, `relevance: str`, `summary: str`, `tab_index: int` |
| `browser_open` | Agent opened a real browser tab | `url: str` |
| `done` | All work complete | `result: dict` |
| `error` | Unhandled exception | `message: str` |

### Result Object (`done.result`)

```json
{
  "goal": "find exposed config files",
  "selected_dorks": ["filetype:env DB_PASSWORD", ...],
  "reasoning": "...",
  "total_results": 47,
  "findings": [
    {
      "dork": "filetype:env DB_PASSWORD",
      "results": [
        { "title": "...", "url": "https://...", "snippet": "..." }
      ]
    }
  ],
  "crawled": [
    {
      "url": "https://...",
      "relevance": "high",
      "summary": "..."
    }
  ]
}
```

---

## Tool Registry

`dork_agent/tool_registry.py` registers built-in tools the LLM can call during planning.

| Tool | Inputs | Purpose |
|---|---|---|
| `filter_dorks_by_topic` | `topic: str` | Returns dorks matching topic keyword |
| `get_dork_categories` | — | Returns unique operator category list |
| `expand_query` | `query: str` | Suggests related dork variants |

Tools are injected into the planning prompt as a JSON schema block. The LLM can invoke them by emitting `{"tool_call": "filter_dorks_by_topic", "args": {"topic": "login"}}`.

---

## Memory

Saved to `data/agent_memory.json` (gitignored). Written after each successful run.

```json
{
  "sessions": [
    {
      "timestamp": "2025-01-15T14:32:00",
      "goal": "find exposed config files",
      "selected_dorks": ["filetype:env DB_PASSWORD"],
      "reasoning": "...",
      "findings_count": 12,
      "browser_backend": "native",
      "small_model": "llama3.2:3b",
      "large_model": "llama3.1:8b"
    }
  ]
}
```

The last 5 sessions are injected into the planning prompt as context. Displayed in `#agent-memory` in the UI.

---

## Ollama Integration

All LLM calls go through `dork_agent/ollama_client.py`.

```python
generate(model, prompt)              # → str (blocking)
generate_stream(model, prompt)       # → Iterator[str] (token stream)
list_models()                        # → list[str] (model names)
```

Base URL defaults to `http://127.0.0.1:11434`. Override with the `OLLAMA_BASE_URL` environment variable.
