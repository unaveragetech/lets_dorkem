import json
import threading
import urllib.parse
import uuid
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

from dork_agent.agent import DorkAgent
from dork_agent.config import (
    SLOW_CRAWL_DORKS_FILE,
    SLOW_CRAWL_PROGRESS_FILE,
    load_settings,
    save_settings,
)
from dork_agent.dork_loader import load_dorks
from dork_agent.ollama_client import OllamaClient
from dork_agent.source import load_source_urls, refresh_remote_sources

ROOT_DIR = Path(__file__).resolve().parent
PORT = 8000

# ---------------------------------------------------------------------------
# Job store — tracks background agent runs
# ---------------------------------------------------------------------------

_jobs: dict = {}
_jobs_lock = threading.Lock()


def _new_job(job_id: str) -> dict:
    job = {
        "id": job_id,
        "status": "running",
        "phase": "starting",
        "message": "Starting agent…",
        "stream_text": "",
        "tabs": [],
        "crawl_tabs": [],
        "browser_urls": [],
        "result": None,
        "error": None,
    }
    with _jobs_lock:
        _jobs[job_id] = job
    return job


def _update_job(job_id: str, **kwargs) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def _get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        return dict(_jobs.get(job_id, {}))


def _make_progress_callback(job_id: str):
    """Return a callback that updates the job store as sub-agents complete."""

    def callback(event: str, data: dict) -> None:
        job = _get_job(job_id)
        if not job:
            return

        if event == "planning":
            _update_job(
                job_id,
                phase="planning",
                message=data.get("message", "Planning search strategy…"),
                stream_text="",
            )
        elif event == "stream_token":
            token = data.get("token", "")
            if token:
                with _jobs_lock:
                    if job_id in _jobs:
                        _jobs[job_id]["stream_text"] = _jobs[job_id].get("stream_text", "") + token
        elif event == "browser_open":
            dork = data.get("dork", "")
            si = data.get("search_id", 0)
            search_url = data.get("search_url", "")
            q = urllib.parse.quote_plus(dork)
            bridge_url = f"http://127.0.0.1:{PORT}/search_bridge.html?q={q}&job_id={job_id}&si={si}"
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id]["browser_urls"].append({
                        "id": si,
                        "dork": dork,
                        "search_url": search_url,
                        "bridge_url": bridge_url,
                    })
        elif event == "wave1_start":
            _update_job(
                job_id,
                phase="wave1",
                message=f"Searching {data['total']} dorks in parallel…",
            )
        elif event == "search_tab_done":
            tab_entry = {
                "tab_id": data.get("tab_id"),
                "dork": data.get("dork", ""),
                "status": data.get("status", "done"),
                "result_count": data.get("result_count", 0),
                "elapsed": data.get("elapsed", 0),
                "error": data.get("error"),
            }
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id]["tabs"].append(tab_entry)
                    done = sum(
                        1 for t in _jobs[job_id]["tabs"]
                        if t["status"] in ("done", "error")
                    )
                    total = _jobs[job_id].get("_wave1_total", 0)
                    _jobs[job_id]["message"] = f"Wave 1: {done}/{total} dork searches complete"
                    _jobs[job_id]["_wave1_total"] = total or done
        elif event == "wave2_start":
            _update_job(
                job_id,
                phase="wave2",
                message=f"Crawling {data['total']} URLs in parallel…",
            )
        elif event == "crawl_tab_done":
            crawl_entry = {
                "tab_id": data.get("tab_id"),
                "url": data.get("url", ""),
                "title": data.get("title", ""),
                "status": data.get("status", "done"),
                "relevance": data.get("relevance", "unknown"),
                "summary": data.get("summary", ""),
                "elapsed": data.get("elapsed", 0),
            }
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id]["crawl_tabs"].append(crawl_entry)

    return callback


def _run_agent_job(job_id: str, agent: DorkAgent, goal: str,
                   selected_dorks: list, max_selections: int, max_crawl: int) -> None:
    """Worker function executed in a background thread."""
    try:
        callback = _make_progress_callback(job_id)
        result = agent.search_with_selected_dorks(
            goal,
            selected_dorks,
            max_selections=max_selections,
            max_crawl=max_crawl,
            progress_callback=callback,
        )
        _update_job(job_id, status="done", phase="complete",
                    message="Done.", result=result)
    except Exception as exc:  # noqa: BLE001
        _update_job(job_id, status="error", phase="error",
                    message=str(exc), error=str(exc))


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTPServer that handles each request in a new thread."""
    daemon_threads = True


class UIRequestHandler(SimpleHTTPRequestHandler):

    def send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def parse_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            return self.handle_api_get(parsed.path)
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            return self.handle_api_post(parsed.path)
        self.send_error(404, "Not Found")

    def log_message(self, fmt, *args):  # noqa: D401
        pass  # suppress request logs; uncomment to re-enable

    # ------------------------------------------------------------------
    # GET handlers
    # ------------------------------------------------------------------

    def handle_api_get(self, path: str) -> None:
        if path == "/api/dorks":
            self.send_json({"dorks": load_dorks(include_remote=True)})
            return

        if path == "/api/progress":
            progress = {
                "status": "idle",
                "current_page": 0,
                "total_pages": 0,
                "dorks_found": 0,
                "dork_samples": [],
            }
            if SLOW_CRAWL_PROGRESS_FILE.exists():
                try:
                    progress = json.loads(
                        SLOW_CRAWL_PROGRESS_FILE.read_text(encoding="utf-8")
                    )
                except json.JSONDecodeError:
                    pass
            if SLOW_CRAWL_DORKS_FILE.exists():
                try:
                    lines = [
                        ln.strip()
                        for ln in SLOW_CRAWL_DORKS_FILE.read_text(encoding="utf-8").splitlines()
                        if ln.strip()
                    ]
                    progress["dork_samples"] = lines[-10:]
                except Exception:
                    progress["dork_samples"] = []
            self.send_json(progress)
            return

        if path == "/api/sources":
            self.send_json({"sources": load_source_urls()})
            return

        if path == "/api/settings":
            settings = load_settings()
            self.send_json(
                {
                    "settings": settings,
                    "available_backends": ["native", "playwright", "selenium", "browser-use"],
                }
            )
            return

        if path == "/api/models":
            models = OllamaClient.list_models()
            self.send_json({"models": models})
            return

        # /api/jobs/<job_id>
        if path.startswith("/api/jobs/"):
            job_id = path[len("/api/jobs/"):]
            job = _get_job(job_id)
            if job is None:
                self.send_json({"error": "Job not found."}, status=404)
            else:
                self.send_json(job)
            return

        # /api/proxy_fetch?url=<encoded>
        if path.startswith("/api/proxy_fetch"):
            from urllib.parse import urlparse as _up, parse_qs as _pqs
            import requests as _req
            qs = _pqs(urlparse(self.path).query)
            target_url = qs.get("url", [None])[0]
            if not target_url:
                self.send_json({"error": "Missing url param."}, status=400)
                return
            # Safety: only allow well-known search domains from localhost
            parsed_target = _up(target_url)
            allowed_hosts = {
                "www.google.com", "google.com",
                "www.bing.com", "bing.com",
                "duckduckgo.com", "www.duckduckgo.com",
            }
            if parsed_target.hostname not in allowed_hosts:
                self.send_json({"error": "Domain not allowed."}, status=403)
                return
            try:
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                }
                resp = _req.get(target_url, headers=headers, timeout=15, allow_redirects=True)
                body = resp.content
                self.send_response(200)
                ct = resp.headers.get("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=502)
            return

        self.send_error(404, "API endpoint not found")

    # ------------------------------------------------------------------
    # POST handlers
    # ------------------------------------------------------------------

    def handle_api_post(self, path: str) -> None:
        # /api/native_result/{job_id}/{si} — bridge page reports parsed results
        if path.startswith("/api/native_result/"):
            parts = path.split("/")
            if len(parts) >= 5:
                job_id = parts[3]
                _si = parts[4]
                body = self.parse_body()
                results = body.get("results", [])
                with _jobs_lock:
                    if job_id in _jobs:
                        # Tag bridge results onto the matching tab entry if present
                        for tab in _jobs[job_id].get("tabs", []):
                            try:
                                if str(tab.get("tab_id")) == str(_si):
                                    tab.setdefault("bridge_results", []).extend(results)
                            except Exception:
                                pass
            self.send_json({"ok": True})
            return

        if path == "/api/search":
            body = self.parse_body()
            goal = body.get("goal", "").strip()
            selected_dorks = body.get("selected_dorks", [])
            max_selections = int(body.get("max_selections", 10))
            max_crawl = int(body.get("max_crawl", 0))
            small_model = body.get("small_model") or None
            large_model = body.get("large_model") or None
            browser_backend = body.get("browser_backend") or None

            if not selected_dorks and not goal:
                self.send_json({"error": "Provide a goal or selected dorks."}, status=400)
                return

            # Persist model/backend selections
            settings = load_settings()
            if small_model:
                settings["small_model"] = small_model
            if large_model:
                settings["large_model"] = large_model
            if browser_backend:
                settings["browser_backend"] = browser_backend
            save_settings(settings)

            agent = DorkAgent(
                goal=goal or "Find relevant dorks.",
                small_model=small_model,
                large_model=large_model,
                backend=browser_backend,
            )

            job_id = uuid.uuid4().hex
            _new_job(job_id)

            t = threading.Thread(
                target=_run_agent_job,
                args=(job_id, agent, goal or "Find relevant dorks.",
                      selected_dorks, max_selections, max_crawl),
                daemon=True,
            )
            t.start()

            self.send_json({"job_id": job_id})
            return

        if path == "/api/refresh-sources":
            body = self.parse_body()
            sources = body.get("sources") or load_source_urls()
            refreshed = refresh_remote_sources(sources)
            self.send_json({"dorks_cached": len(refreshed)})
            return

        self.send_error(404, "API endpoint not found")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    handler_class = UIRequestHandler
    handler_class.directory = str(ROOT_DIR)
    httpd = ThreadingHTTPServer(("", PORT), handler_class)
    print(f"Serving UI on http://127.0.0.1:{PORT}")
    httpd.serve_forever()
