import argparse
import json
import os
import statistics
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

OLLAMA = "http://localhost:11434"
SITE_PORT = 8791
PROXY_PORT = 8792
VIEWPORT = (1280, 800)
IMAGE_TOKEN_DIVISOR = 750

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


def run_once(task, session_args):
    from fastbrowse import browse, chrome_session, contains

    before = snapshot()
    success = contains(**task["success"]) if task["success"] else None
    with chrome_session(**session_args):
        result = browse(f"http://127.0.0.1:{SITE_PORT}{task['start']}", task["goal"], success=success, max_steps=6)
    after = snapshot()
    return {
        "task": task["name"],
        "ok": result.reason == task["expect"],
        "reason": result.reason,
        "steps": result.steps,
        "wall_ms": result.elapsed_ms,
        "agent_ms": result.agent_ms,
        "prompt_tokens": after["prompt"] - before["prompt"],
        "completion_tokens": after["completion"] - before["completion"],
        "planner_calls": after["calls"] - before["calls"],
        "trail": result.trail,
        "error": result.error,
    }


def screenshot_tokens_per_step():
    width, height = VIEWPORT
    return round(width * height / IMAGE_TOKEN_DIVISOR)


def summarize(rows):
    table = []
    for name in dict.fromkeys(row["task"] for row in rows):
        group = [row for row in rows if row["task"] == name]
        steps = statistics.median(row["steps"] for row in group)
        local_tokens = statistics.median(row["prompt_tokens"] + row["completion_tokens"] for row in group)
        table.append({
            "task": name,
            "runs": len(group),
            "pass_rate": f"{sum(row['ok'] for row in group)}/{len(group)}",
            "median_steps": steps,
            "median_wall_s": round(statistics.median(row["wall_ms"] for row in group) / 1000, 2),
            "median_agent_s": round(statistics.median(row["agent_ms"] for row in group) / 1000, 2),
            "median_local_planner_tokens": local_tokens,
            "external_api_tokens": 0,
            "screenshot_loop_image_tokens_estimate": round(steps * screenshot_tokens_per_step()),
        })
    return table


def main():
    parser = argparse.ArgumentParser(description="Benchmark fastbrowse: speed, pass rate and token consumption.")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("bench_results.json"))
    args = parser.parse_args()

    os.environ["TEXT_MODEL_BASE_URL"] = f"http://127.0.0.1:{PROXY_PORT}/v1"
    serve(Site, SITE_PORT)
    serve(Proxy, PROXY_PORT)
    session_args = {"isolated": True, "headed": False}

    rows = []
    for task in TASKS:
        for run in range(args.runs):
            row = run_once(task, session_args) | {"run": run}
            rows.append(row)
            print(json.dumps(row), flush=True)

    summary = summarize(rows)
    args.out.write_text(json.dumps({"rows": rows, "summary": summary}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
