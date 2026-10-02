import argparse
import json
import os
import statistics
import threading
import time
import urllib.request
import subprocess
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

OLLAMA = "http://localhost:11434"
SITE_PORT = 8791
PROXY_PORT = 8792

PAGES = {
    "/": ("Acme", '<a href="/pricing">Pricing</a> <a href="/docs">Docs</a> <a href="/contact">Contact</a><a href="/subscribe">Subscribe</a>'),
    "/subscribe": ("Acme subscribe", "<h1>Subscribed</h1>"),
    "/pricing": ("Acme pricing", "<h1>Pricing</h1><p>Basic 199, Plus 499, Premium 999</p>"),
    "/docs": ("Acme docs", '<h1>Docs</h1><a href="/docs/quickstart">Quickstart</a> <a href="/docs/api">API reference</a>'),
    "/docs/quickstart": ("Acme quickstart", "<h1>Quickstart</h1><p>Install and run.</p>"),
    "/docs/api": ("Acme API", "<h1>API reference</h1>"),
    "/contact": ("Acme contact", "<h1>Contact</h1><p>hello@example.com</p>"),
}

TASKS = [
    {"name": "one-hop", "goal": "Open the pricing page", "start": "/", "success": {"url": ["/pricing"]}, "expect": "success"},
    {"name": "two-hop", "goal": "Open the quickstart guide inside the docs", "start": "/", "success": {"url": ["/docs/quickstart"]}, "expect": "success"},
    {"name": "veto", "goal": "Subscribe to the newsletter", "start": "/", "success": None, "expect": "vetoed"},
]

MODES = {
    "cold-headless": {"warm": False, "headed": False, "same_tab": False},
    "cold-headed": {"warm": False, "headed": True, "same_tab": False},
    "warm-headless": {"warm": True, "headed": False, "same_tab": False},
    "warm-headed": {"warm": True, "headed": True, "same_tab": False},
    "warm-headless-same-tab": {"warm": True, "headed": False, "same_tab": True},
    "warm-headed-same-tab": {"warm": True, "headed": True, "same_tab": True},
}
MODEL = "qwen3:4b-instruct-2507-q4_K_M"

usage_lock = threading.Lock()
usage = {"prompt": 0, "completion": 0, "calls": 0}


class Site(BaseHTTPRequestHandler):
    def do_GET(self):
        title, body = PAGES.get(self.path, ("Not found", "<h1>404</h1>"))
        page = f"<!doctype html><title>{title}</title><body>{body}</body>".encode()
        self.send_response(200 if self.path in PAGES else 404)
        self.send_header("content-type", "text/html")
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, *args):
        pass


class Proxy(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        request = urllib.request.Request(OLLAMA + self.path, data=body, headers={"content-type": "application/json"})
        payload = urllib.request.urlopen(request, timeout=300).read()
        counted = json.loads(payload).get("usage") or {}
        with usage_lock:
            usage["prompt"] += counted.get("prompt_tokens", 0)
            usage["completion"] += counted.get("completion_tokens", 0)
            usage["calls"] += 1
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def serve(handler, port):
    server_class = ThreadingHTTPServer if handler is Proxy else HTTPServer
    server = server_class(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def snapshot():
    with usage_lock:
        return dict(usage)


def run_once(task, mode_name, mode):
    from fastbrowse import browse, chrome_session, contains

    before = snapshot()
    success = contains(**task["success"]) if task["success"] else None
    session = nullcontext() if mode["warm"] else chrome_session(isolated=True, headed=mode["headed"])
    started = time.perf_counter()
    with session:
        result = browse(f"http://127.0.0.1:{SITE_PORT}{task['start']}", task["goal"], success=success, max_steps=6)
    total_ms = round((time.perf_counter() - started) * 1000)
    after = snapshot()
    return {
        "mode": mode_name,
        "task": task["name"],
        "ok": result.reason == task["expect"],
        "reason": result.reason,
        "steps": result.steps,
        "task_ms": result.elapsed_ms,
        "total_ms": total_ms,
        "prompt_tokens": after["prompt"] - before["prompt"],
        "completion_tokens": after["completion"] - before["completion"],
        "trail": result.trail,
        "error": result.error,
    }


@contextmanager
def reused_tab():
    from browser_harness.admin import ensure_daemon
    from browser_harness.helpers import cdp
    from laya_ultrafast.browser import Browser

    original_init, original_close = Browser.__init__, Browser.close
    pool = {}

    def pooled_init(self, url):
        if not pool:
            original_init(self, url)
            pool.update(target=self.target, session=self.session)
            return
        ensure_daemon()
        self.target, self.session = pool["target"], pool["session"]
        self.call("Page.navigate", url=url)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and self.evaluate("document.readyState") != "complete":
            time.sleep(0.02)

    def pooled_close(self):
        self.target = None

    Browser.__init__, Browser.close = pooled_init, pooled_close
    try:
        yield
    finally:
        Browser.__init__, Browser.close = original_init, original_close
        if pool:
            cdp("Target.closeTarget", targetId=pool["target"])


def run_mode(mode_name, runs):
    from fastbrowse import chrome_session

    mode = MODES[mode_name]
    warm_session = chrome_session(isolated=True, headed=mode["headed"]) if mode["warm"] else nullcontext()
    tab = reused_tab() if mode["same_tab"] else nullcontext()
    rows = []
    with warm_session, tab:
        for task in TASKS:
            for run in range(runs):
                row = run_once(task, mode_name, mode) | {"run": run}
                rows.append(row)
                print(json.dumps(row), flush=True)
    return rows


def summarize(rows):
    table = []
    for mode in dict.fromkeys(row["mode"] for row in rows):
        for name in dict.fromkeys(row["task"] for row in rows if row["mode"] == mode):
            group = [row for row in rows if row["mode"] == mode and row["task"] == name]
            median = lambda key: statistics.median(row[key] for row in group)
            table.append({
                "mode": mode,
                "task": name,
                "runs": len(group),
                "pass_rate": f"{sum(row['ok'] for row in group)}/{len(group)}",
                "median_task_s": round(median("task_ms") / 1000, 2),
                "median_total_s": round(median("total_ms") / 1000, 2),
                "median_open_close_s": round(statistics.median(row["total_ms"] - row["task_ms"] for row in group) / 1000, 2),
                "median_local_planner_tokens": statistics.median(row["prompt_tokens"] + row["completion_tokens"] for row in group),
                "first_run_total_s": round(next(r["total_ms"] for r in rows if r["mode"] == mode) / 1000, 2) if name == TASKS[0]["name"] else None,
            })
    return table


def main():
    parser = argparse.ArgumentParser(description="Benchmark fastbrowse: speed, browser open/close cost, pass rate and token consumption.")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--modes", nargs="+", choices=list(MODES), default=list(MODES))
    parser.add_argument("--out", type=Path, default=Path("bench_results.json"))
    parser.add_argument("--unload-model", action="store_true", help="Unload the Ollama model first so the first run pays the model load.")
    args = parser.parse_args()

    if args.unload_model:
        subprocess.run(["ollama", "stop", MODEL], check=False)

    os.environ["TEXT_MODEL_BASE_URL"] = f"http://127.0.0.1:{PROXY_PORT}/v1"
    serve(Site, SITE_PORT)
    serve(Proxy, PROXY_PORT)

    rows = []
    for mode_name in args.modes:
        rows.extend(run_mode(mode_name, args.runs))

    summary = summarize(rows)
    args.out.write_text(json.dumps({"rows": rows, "summary": summary}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
