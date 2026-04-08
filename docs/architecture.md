# Architecture

## Overview

Dorkem is a single-host, multi-threaded Python application. A lightweight HTTP server (`ui_server.py`) handles both static file serving and an API, while background threads run the AI agent and browser automation. Everything communicates via a simple in-memory job store that the frontend polls.

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser (your real browser)                                    │
│                                                                 │
│  Index.html  ←── static ───┐    search_bridge.html (per-dork)  │
│  (JS polling /api/jobs/*)  │    (opened by JS window.open)     │
└──────────────┬─────────────┘────────────────┬───────────────────┘
               │  HTTP (port 8000)             │ POST /api/native_result
               ▼                              ▼
┌──────────────────────────────────────────────────────────────┐
│  ui_server.py  (ThreadingHTTPServer)                         │
│                                                              │
│  ┌──────────────┐  ┌─────────────────────────────────────┐  │
│  │ Static files │  │ API endpoints                       │  │
│  │ (GET /)      │  │  GET  /api/dorks                    │  │
│  └──────────────┘  │  GET  /api/settings                 │  │
│                    │  GET  /api/models                   │  │
│                    │  GET  /api/progress                 │  │
│                    │  GET  /api/jobs/<id>                │  │
│                    │  GET  /api/proxy_fetch?url=         │  │
│                    │  POST /api/search         ──────────┼──┼──► background thread
│                    │  POST /api/native_result/<id>/<si>  │  │
│                    │  POST /api/refresh-sources          │  │
│                    └─────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
               │  background thread
               ▼
┌──────────────────────────────────────────────────────────────┐
│  DorkAgent  (dork_agent/agent.py)                            │
│                                                              │
│  select_dorks_with_reasoning()  ← OllamaClient (streaming)  │
│          │                                                   │
│  run_sub_agents()                                            │
│   │                                                          │
│   ├─ Wave 1: ThreadPoolExecutor                              │
│   │   └─ SearchSubAgent × N  ← GoogleSearcher               │
│   │                           (native / selenium / playwright│
│   │                            / browser-use)               │
│   │                                                          │
│   └─ Wave 2: ThreadPoolExecutor  (if max_crawl > 0)         │
│       └─ CrawlSubAgent × M  ← GoogleSearcher.crawl_url()   │
│                               OllamaClient (relevance score) │
└──────────────────────────────────────────────────────────────┘
               │  progress events
               ▼
┌──────────────────────────────────────────────┐
│  _jobs  (in-memory dict, protected by Lock)  │
│  { job_id: { status, phase, tabs, result … } }│
└──────────────────────────────────────────────┘
```

---

## Threading Model

| Thread | Purpose |
|---|---|
| Main / server thread | `ThreadingHTTPServer` — one new thread per HTTP request |
| Agent thread | Created by `POST /api/search`, runs `_run_agent_job()` to completion |
| Wave-1 pool | `ThreadPoolExecutor(max_workers=5)` — one thread per dork search |
| Wave-2 pool | `ThreadPoolExecutor(max_workers=5)` — one thread per URL crawl |

`_BROWSER_USE_LOCK` (a `threading.Lock`) in `searcher.py` serialises all `asyncio.run()` calls so that browser-use's internal event loop is never shared between threads.

---

## Data Flow

### Search request

```
POST /api/search  {goal, selected_dorks, settings}
  │
  ├─ persist settings to dork_agent/settings.json
  ├─ create DorkAgent with requested models + backend
  ├─ allocate job_id, insert into _jobs
  ├─ spawn daemon thread → _run_agent_job()
  └─ return {job_id}

_run_agent_job()
  ├─ emit "planning" event
  ├─ if no user dorks: select_dorks_with_reasoning() → streaming LLM
  ├─ if user dorks: skip LLM, use directly
  ├─ emit "browser_open" event × N  (→ UI opens search_bridge.html tabs)
  ├─ emit "wave1_start"
  ├─ SearchSubAgent.run() × N in parallel
  │    └─ GoogleSearcher.search(dork)
  │         └─ backend-specific fetch + parse
  ├─ emit "search_tab_done" × N
  ├─ (optional) emit "wave2_start"
  ├─ CrawlSubAgent.run() × M in parallel
  │    └─ GoogleSearcher.crawl_url(url)
  │    └─ OllamaClient.generate(relevance prompt)
  ├─ emit "crawl_tab_done" × M
  ├─ record_memory()
  ├─ write_review()
  └─ _update_job(status="done", result=…)
```

### Frontend polling

```
setInterval(1000ms)
  GET /api/jobs/<job_id>
    → renderProgress(job)    # update tab cards + stream box
    → open window.open() for new browser_urls entries
    → if done: renderAgentResults(job.result)
```

---

## File Roles

| File | Role |
|---|---|
| `ui_server.py` | HTTP server, job store, API routing |
| `dork_agent/agent.py` | `DorkAgent` — orchestrates planning + sub-agents |
| `dork_agent/sub_agent.py` | `SearchSubAgent`, `CrawlSubAgent`, `paginate()` |
| `dork_agent/searcher.py` | `GoogleSearcher` — 4 backends + HTML parser |
| `dork_agent/ollama_client.py` | `OllamaClient` — `generate()`, `generate_stream()`, `list_models()` |
| `dork_agent/dork_loader.py` | Load + deduplicate dork files |
| `dork_agent/source.py` | Exploit-DB Selenium crawler, remote source fetcher |
| `dork_agent/tools.py` | `ToolRegistry`, built-in tools for the LLM |
| `dork_agent/config.py` | File paths, defaults, `load_settings()` / `save_settings()` |
| `dork_agent/review_writer.py` | Writes `review.md` Markdown report |
| `Index.html` | Single-page dashboard (all JS inline) |
| `search_bridge.html` | Per-dork tab: proxy fetch + DOMParser + result reporting |
| `crawl_wizard.py` | Interactive bulk-crawl wizard |
| `run_dork_agent.py` | CLI interface to the agent |
| `setup_dork_agent.py` | First-run model/backend configuration wizard |
