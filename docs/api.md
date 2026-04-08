# API Reference

All endpoints are served by `ui_server.py` on `http://127.0.0.1:8000`.  
CORS headers (`Access-Control-Allow-Origin: *`) are set on all responses.

---

## GET /api/dorks

Returns all dorks loaded from `data/google_hacking_database.txt`, `data/slow_crawl_dorks.txt`, and `data/remote_dorks.txt`, deduplicated.

**Response**
```json
{
  "dorks": ["intitle:\"index of\" \"parent directory\"", "filetype:sql inurl:backup", "..."]
}
```

---

## GET /api/settings

Returns the current agent settings and the list of supported browser backends.

**Response**
```json
{
  "settings": {
    "small_model": "llama3.2:latest",
    "large_model": "olmo-3:latest",
    "browser_backend": "native",
    "dork_file": "data/google_hacking_database.txt",
    "review_path": "review.md",
    "max_results": 5
  },
  "available_backends": ["native", "playwright", "selenium", "browser-use"]
}
```

---

## GET /api/models

Queries the local Ollama REST API (`http://127.0.0.1:11434/api/tags`) and returns available model names.

**Response**
```json
{
  "models": ["llama3.2:latest", "olmo-3:latest", "gemma:7b"]
}
```

Returns `{"models": []}` if Ollama is unreachable.

---

## GET /api/progress

Returns the slow crawl state from `data/slow_crawl_progress.json`.

**Response**
```json
{
  "status": "complete",
  "current_page": 100,
  "total_pages": 100,
  "dorks_found": 1500,
  "dork_samples": ["intitle:\"index of\" /", "filetype:env DB_PASSWORD"]
}
```

`status` values: `"idle"`, `"running"`, `"complete"`

---

## GET /api/sources

Returns the list of remote dork source URLs configured in `data/dork_sources.json`.

**Response**
```json
{
  "sources": ["https://www.exploit-db.com/google-hacking-database"]
}
```

---

## GET /api/jobs/`<job_id>`

Poll a background agent job. The frontend calls this every second.

**Response — running**
```json
{
  "id": "a3f9...",
  "status": "running",
  "phase": "wave1",
  "message": "Wave 1: 3/8 dork searches complete",
  "stream_text": "I selected these dorks because...",
  "tabs": [
    {
      "tab_id": 0,
      "dork": "intitle:\"index of\" /",
      "status": "done",
      "result_count": 5,
      "elapsed": 4.2,
      "error": null
    }
  ],
  "crawl_tabs": [],
  "browser_urls": [
    {
      "id": 0,
      "dork": "intitle:\"index of\" /",
      "search_url": "https://www.google.com/search?q=intitle%3A%22index+of%22+%2F&num=10",
      "bridge_url": "http://127.0.0.1:8000/search_bridge.html?q=intitle...&job_id=a3f9&si=0"
    }
  ],
  "result": null,
  "error": null
}
```

**Response — done**
```json
{
  "status": "done",
  "result": {
    "goal": "Find exposed directory listings",
    "selected_dorks": ["intitle:\"index of\" /"],
    "reasoning": "This dork targets open directories...",
    "findings": [
      {
        "query": "intitle:\"index of\" /",
        "results": [
          {"title": "Index of /", "url": "https://example.com/files/", "snippet": "..."}
        ],
        "elapsed": 4.2,
        "error": null
      }
    ],
    "paginated_urls": [[{"url": "...", "title": "...", "snippet": "..."}]],
    "crawl_results": [],
    "memory_summary": "- 2026-04-07T…: Find exposed directory listings — 1 dorks, 5 results"
  }
}
```

**Response — error**
```json
{
  "status": "error",
  "error": "Ollama connection refused"
}
```

---

## GET /api/proxy_fetch?url=`<encoded_url>`

Server-side HTTP fetch of a search engine URL. Used by `search_bridge.html` to retrieve Google HTML without a headless browser.

Allowed domains (SSRF guard): `www.google.com`, `google.com`, `www.bing.com`, `bing.com`, `duckduckgo.com`, `www.duckduckgo.com`

**Response**  
Raw HTML with original `Content-Type` header.  
Returns `{"error": "Domain not allowed."}` (403) for any other hostname.

---

## POST /api/search

Start a new agent job.

**Request body**
```json
{
  "goal": "Find exposed admin panels",
  "selected_dorks": ["inurl:admin login"],
  "max_selections": 10,
  "max_crawl": 3,
  "small_model": "llama3.2:latest",
  "large_model": "olmo-3:latest",
  "browser_backend": "native"
}
```

All fields except `goal` or `selected_dorks` (at least one required) are optional.

**Response**
```json
{ "job_id": "a3f9bc..." }
```

---

## POST /api/native_result/`<job_id>`/`<si>`

Called by `search_bridge.html` to report parsed results back to the agent for a specific dork index `si`.

**Request body**
```json
{
  "results": [
    {"title": "Admin Login", "url": "https://example.com/admin/", "snippet": "..."}
  ]
}
```

**Response**
```json
{ "ok": true }
```

---

## POST /api/refresh-sources

Trigger a fresh crawl of all configured remote dork sources and update `data/remote_dorks.txt`.

**Request body** (optional — defaults to `data/dork_sources.json`)
```json
{ "sources": ["https://www.exploit-db.com/google-hacking-database"] }
```

**Response**
```json
{ "dorks_cached": 1500 }
```

---

## OPTIONS (CORS preflight)

All API paths respond to `OPTIONS` with 204 and the appropriate CORS headers.
