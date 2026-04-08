# Browser Backends

`DorkAgent` supports four interchangeable backends for fetching Google search results. Select via the UI dropdown or pass `browser_backend` in the `/api/search` POST body.

---

## Comparison

| Backend | Requires | Speed | CAPTCHA risk | Best for |
|---|---|---|---|---|
| `native` | `requests` (stdlib) | Fast | **Low** | Default — no browser fingerprint |
| `selenium` | Chrome + chromedriver | Slow | High | JS-heavy result pages |
| `playwright` | Playwright browsers | Medium | High | Modern sites, async usage |
| `browser-use` | `browser-use` pkg | Variable | High | AI-controlled browsing |

---

## native (recommended)

Uses Python `requests` to fetch `https://www.google.com/search?q=<dork>&num=10` directly. No webdriver flags, no headless Chrome — the request looks like a regular browser visiting from your IP.

### Search flow

```python
_search_with_requests(dork)
  │
  ├─ GET https://www.google.com/search?q=<dork>&num=10
  │    headers: User-Agent (rotating pool), Accept-Language: en-US
  │
  └─ _parse_google_html(html)
       walks response HTML with regex + string slicing
       extracts: title / href / snippet per result block
       returns list[dict]
```

### `_parse_google_html(html)`

Does **not** use BeautifulSoup. Uses pure `re` patterns and string slicing:

1. Looks for `<h3` tags to find result boundaries
2. Walks backwards to find enclosing `<a href=` for the URL
3. Looks for the next `<span` or `<div` after `</h3>` for the snippet
4. Strips all HTML tags from title and snippet with `re.sub(r'<[^>]+>', '')`
5. Decodes `&amp;` `&lt;` `&gt;` entity refs

Returns an empty list when the response body contains `"detected unusual traffic"` — the caller emits an appropriate event.

### Crawl flow

```python
_crawl_with_requests(url)
  │
  ├─ GET <url>
  │    timeout=10, allow_redirects=True
  │
  └─ strips HTML → visible text (same regex approach)
       passed to large_model for relevance scoring
```

---

## selenium

Drives a real Chrome instance via `selenium 4.x`.

### Setup

```bash
pip install selenium
# chromedriver must match your Chrome version and be on PATH
```

### Search flow

```python
_search_with_selenium(dork)
  │
  ├─ WebDriver(ChromeOptions) — headless=False so Google is less suspicious
  ├─ driver.get("https://www.google.com/search?q=<dork>&num=10")
  │
  └─ _extract_google_results_selenium(driver)
       driver.find_elements(By.CSS_SELECTOR, "div.g")
         for each: h3.innerText → title
                   a.href      → url
                   span/div    → snippet
       returns list[dict]
```

Options applied:
- `--no-sandbox`
- `--disable-dev-shm-usage`
- `--disable-blink-features=AutomationControlled`
- `window-size=1280,800`

### Why CAPTCHA is more likely

Chrome in webdriver mode sets the `navigator.webdriver` property even with the `AutomationControlled` flag. Google's bot detection checks this property.

---

## playwright

Uses `playwright` async API wrapped in a sync caller thread.

### Setup

```bash
pip install playwright
python -m playwright install chromium
```

### Search flow

```python
_search_with_playwright(dork)
  │
  ├─ async: browser = await playwright.chromium.launch(headless=True)
  ├─ page.goto("https://www.google.com/search?q=<dork>&num=10")
  │
  └─ _extract_google_results(page)
       page.query_selector_all("div.tF2Cxc")
         for each: .querySelector("h3")  → title
                   .querySelector("a")  → url
                   .querySelector(".VwiC3b") → snippet
       returns list[dict]
```

---

## browser-use

Uses the `browser-use` library which wraps Playwright with an AI agent that can interact with the page (click, scroll, handle consent dialogs).

### Setup

```bash
pip install browser-use
```

### Search flow

```python
_search_with_browser_use(dork)
  │
  ├─ acquires _BROWSER_USE_LOCK (asyncio.Lock — only one browser-use agent at a time)
  ├─ BrowserUseAgent.run("Search Google for: <dork>  Extract result titles and URLs.")
  │
  └─ parses agent output text for title/URL pairs
       returns list[dict]
```

### `_BROWSER_USE_LOCK`

`browser-use` is not thread-safe for concurrent browser instances. The lock in `dork_agent/agent.py` ensures wave-1 sub-agents queue rather than overlap when this backend is selected.

---

## search_bridge.html (native assist mode)

When the `native` backend is selected the agent also opens `search_bridge.html` tabs — one per dork — so the user can see actual Google results in their browser. The bridge page runs its own fetch + parse cycle and POSTs results back to `/api/native_result/<job_id>/<si>`.

### Selector fallback chain

The bridge tries selectors in order until one returns results:

```
1. div.tF2Cxc           ← standard result card (2023 layout)
2. div.N54PNb            ← alternate card class
3. div[data-hveid]       ← presence of this attribute = result block
4. div.g                 ← legacy catch-all
5. a[href] + h3 fallback ← brute-force: any h3 that follows a link
```

### CAPTCHA handling

If the fetched HTML contains any of:
- `"detected unusual traffic"`
- `"our systems have detected"`
- `id="captcha"`

The bridge shows a warning card: **"Google has blocked this request"** with an **"Open in Google →"** link. The user can solve the CAPTCHA manually and the bridge will re-fetch on page reload.

---

## Choosing a Backend

```
Is Playwright installed?  No  → use native (default)
                          Yes → use playwright for headless

Do you need AI-controlled
interaction (e.g. accept
cookie banners)?          Yes → use browser-use
                          No  → use native or selenium

Getting 429 / CAPTCHA?        → switch to native
                                 or add delays between dorks
                                 in settings
```
