# UI Reference

`Index.html` is a self-contained single-page application served by `ui_server.py`. All JavaScript is inline. No build step, no framework.

---

## Layout

```
┌─────────────────── .page-shell (max-width 1280px) ──────────────────────┐
│ header.topbar                                                            │
│   brand h1 + p        [Dark/Light]  [Reload Dorks]                      │
├──────────────────────────────────────────────────────────────────────────│
│ section.hero                                                             │
│   [search-input ─────────────────────────────]  [Search]                │
│   ☑ Google  ☑ Perplexity  ☐ Bing  ☐ DuckDuckGo  ☐ Wikipedia  [Voice]   │
├──────────── .section-grid (2 cols) ──────────────────────────────────────│
│ #dork-library                  │ #agent-panel                           │
│  [filter input]                │  small model ▼  large model ▼          │
│  "N dorks · M shown · K sel."  │  backend ▼  max crawl #               │
│  [chip][chip][chip]...         │  [goal textarea]                       │
│  ◀ Prev  Page 1/28  Next ▶     │  [Run AI Agent]  [Clear Selection]     │
│                                │  #agent-progress (hidden while idle)   │
├────────────────────────────────┤    #stream-box (planning phase)        │
│ #crawl-panel                   │    #search-tabs (wave-1 cards)         │
│  status pill                   │    #crawl-section (wave-2 cards)       │
│  dork samples                  │  #agent-memory  #agent-reasoning       │
└────────────────────────────────┴──#agent-results─────────────────────────┘
```

---

## JS Globals

| Variable | Type | Purpose |
|---|---|---|
| `allDorks` | `string[]` | Full list from `/api/dorks` |
| `selectedDorks` | `string[]` | Currently selected dorks for the agent |
| `_dorkPage` | `number` | Current page index in the dork library |
| `_DORKS_PER_PAGE` | `number` | 50 |
| `_lastCrawlStatus` | `string` | Previous crawl status — used to detect transition to `"complete"` |
| `_pollInterval` | `number\|null` | `setInterval` handle for job polling |
| `_openedBrowserTabs` | `Set<string>` | Tracks which bridge URLs have been opened so tabs aren't duplicated |
| `apiBase` | `string` | `window.location.origin` or `http://127.0.0.1:8000` |

---

## Key Functions

### `renderDorkList()`

Renders the current page of filtered dorks.

1. Calls `_getFilteredDorks()` to apply the filter box value
2. Slices `_dorkPage * _DORKS_PER_PAGE` → `+50`
3. Creates `<button class="dork-chip">` for each dork:
   - **click** — toggles `selectedDorks`, flips `.selected` class without re-rendering
   - **dblclick** — copies dork into `#search-input`, scrolls to top, flashes `.dbl-flash`
4. Updates pager controls (Prev/Next buttons + page info pill)

### `runAgent()`

1. Validates that at least one dork is selected or a goal is entered
2. Clears `_openedBrowserTabs`
3. Posts to `/api/search` with all settings
4. Starts `setInterval(1000ms)` polling `/api/jobs/<id>`
5. On each poll:
   - Calls `renderProgress(job)` to update cards + stream box
   - Opens any new `browser_urls` entries in named tabs via `window.open(url, 'dorkem_tab_N')`
   - On `status === 'done'`: calls `renderAgentResults(job.result)`
   - On `status === 'error'`: shows error message

### `renderProgress(job)`

Updates the live progress section:
- Shows/hides `#stream-box` based on `job.phase === 'planning'`
- Auto-scrolls stream box to bottom
- Rebuilds `#search-tabs` and `#crawl-tabs` from `job.tabs` / `job.crawl_tabs`

### `renderAgentResults(result)`

Hides progress UI, renders results:
- Goal header with dork count + total result count
- Top crawled pages section (relevance ≥ medium)
- All URLs paginated list
- Per-dork result cards with title/URL/snippet
- "Google may have blocked" message if 0 total results

### `fetchProgress()`

Polls `/api/progress`. Detects transition to `status === 'complete'` by comparing with `_lastCrawlStatus` and auto-calls `fetchDorks()` to refresh the library.

### `performSearch()`

Opens the hero search bar query in new tabs. Supports engine prefix shortcuts:

| Prefix | Engine |
|---|---|
| `G-` | Google |
| `P-` | Perplexity |
| `B-` | Bing |
| `D-` | DuckDuckGo |
| `W-` | Wikipedia |

---

## CSS Variables

```css
--surface:   #0d111b   /* dark card background */
--surface-2: #131a2d
--surface-3: #192439
--text:      #e6edf7
--muted:     #8ca1c6
--accent:    #61dafb   /* cyan highlight */
--accent-2:  #6bffa6   /* green highlight */
--border:    rgba(255,255,255,0.08)
--shadow:    0 24px 60px rgba(0,0,0,0.35)
--radius:    24px
```

Light mode overrides are applied via `body.light-mode`.

---

## search_bridge.html

A lightweight styled page opened once per dork when using the `native` backend.

**URL format:** `http://127.0.0.1:8000/search_bridge.html?q=<encoded_dork>&job_id=<id>&si=<index>`

**Flow:**

1. Display the decoded dork query
2. Fetch `GET /api/proxy_fetch?url=https://www.google.com/search?q=<q>&num=10`
3. Detect CAPTCHA — show user-friendly message with "Open in Google" link if blocked
4. Parse HTML with `DOMParser`, try selectors in order:
   - `div.tF2Cxc` → `div.N54PNb` → `div[data-hveid]` → `div.g` → `a[href] + h3` fallback
5. Render result cards (title / URL / snippet)
6. POST results to `/api/native_result/<job_id>/<si>`
7. Show "Done — N results sent to AI agent" status

The page stays open so the user can click through results. The "Open in Google →" button always remains visible.
