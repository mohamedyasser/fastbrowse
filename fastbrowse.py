import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

os.environ.setdefault("BU_NAME", "fastbrowse")  # browser_harness reads BU_NAME at import time

from browser_harness import _ipc as ipc  # noqa: E402
from browser_harness.admin import NAME as DAEMON, restart_daemon  # noqa: E402
from browser_harness.helpers import cdp  # noqa: E402
from laya_ultrafast import Agent  # noqa: E402
from laya_ultrafast.browser import Browser, StalePage  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LOCAL_PLANNER = {
    "DECISION_MODEL": "laya",
    "TEXT_MODEL_BASE_URL": "http://localhost:11434/v1",
    "TEXT_MODEL": "qwen3:4b-instruct-2507-q4_K_M",
    "TEXT_MODEL_REASONING": "none",
}
DENY = re.compile(
    r"\b(send|post|publish|like|react|connect|follow|unfollow|message|comment|reply|delete|remove|"
    r"buy|pay|purchase|checkout|order|apply|subscribe|block|report|"
    r"إرسال|ارسال|نشر|أعجبني|اعجبني|إعجاب|تواصل|متابعة|رسالة|تعليق|رد|حذف|شراء|دفع|اشتراك|حظر|إبلاغ)\b",
    re.IGNORECASE,
)


@dataclass
class Result:
    ok: bool
    reason: str
    steps: int
    elapsed_ms: int
    agent_ms: int
    url: str
    trail: list[str] = field(default_factory=list)
    error: str | None = None


def contains(url=(), title=(), text=()):
    needles = {"url": url, "title": title, "text": text}

    def check(page):
        return all(n.lower() in str(page.get(key, "")).lower() for key, values in needles.items() for n in values)

    return check


def chosen_action(page, decision):
    return next((a for a in page["actions"] if a["id"] == decision["choice"]), None)


def vetoes(deny, action, page):
    return bool(deny(action, page)) if callable(deny) else bool(deny.search(action["label"]))


def attempt(factory, url, goal, success, max_steps, deny):
    started = time.perf_counter()
    with factory(url, goal) as agent:
        state = agent.state

        def result(ok, reason, error=None):
            return Result(
                ok, reason, len(state["history"]), round((time.perf_counter() - started) * 1000),
                state["elapsed_ms"], state["page"]["url"], [h["action"] for h in state["history"]], error,
            )

        while state["status"] not in {"done", "blocked"} and len(state["history"]) < max_steps:
            if success and success(state["page"]):
                return result(True, "success")
            try:
                agent.command("predict")
                action = chosen_action(state["page"], state["decision"])
                if action and vetoes(deny, action, state["page"]):
                    state["decision"] = None
                    return result(False, "vetoed", action["label"])
                agent.command("act", {"fingerprint": state["page"]["fingerprint"]})
            except StalePage:
                state["decision"] = None
                state["status"] = "ready"
                state["page"] = state["browser"].observe(screenshot=False)

        if success:
            if success(state["page"]):
                return result(True, "success")
            if state["status"] == "done":
                return result(False, "done_unverified")
        elif state["status"] == "done":
            return result(True, "agent_done")
        return result(False, "blocked" if state["status"] == "blocked" else "max_steps")


def browse(url, goal, *, success=None, max_steps=10, retries=1, deny=DENY, factory=Agent):
    for key, value in LOCAL_PLANNER.items():
        os.environ.setdefault(key, value)
    last = None
    for _ in range(retries + 1):
        try:
            return attempt(factory, url, goal, success, max_steps, deny)
        except Exception as error:
            last = Result(False, "error", 0, 0, 0, url, error=str(error))
            if "navigating" not in str(error).lower():
                return last
    return last


def stop_live_daemon(grace=0.5):
    pid = ipc.identify(DAEMON, timeout=1.0)
    if pid is None:
        return
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.05)
    os.kill(pid, signal.SIGKILL)


def reset_daemon():
    try:
        stop_live_daemon()  # restart_daemon alone waits 15 s for a daemon that never exits by itself
        restart_daemon(DAEMON)
    except Exception:  # cleanup only: a daemon that is already gone is the goal state
        pass


@contextmanager
def isolated_chrome(port=9333, profile=None, headless=True):
    reset_daemon()
    with tempfile.TemporaryDirectory() as scratch:
        flags = ["--headless=new"] if headless else []
        process = subprocess.Popen(
            [CHROME, *flags, f"--remote-debugging-port={port}", f"--user-data-dir={profile or scratch}",
             "--no-first-run", "--no-default-browser-check", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Isolated Chrome did not start")
                    time.sleep(0.2)
            os.environ["BU_CDP_URL"] = f"http://127.0.0.1:{port}"
            yield
        finally:
            reset_daemon()
            process.terminate()
            process.wait(10)


@contextmanager
def chrome_session(isolated=False, port=9333, profile=None, headed=False):
    if isolated:
        with isolated_chrome(port, profile, not headed):
            yield
        return
    reset_daemon()
    os.environ.pop("BU_CDP_URL", None)
    yield


@contextmanager
def open_page(url):
    browser = Browser(url)
    try:
        yield browser
    finally:
        browser.close()


def reveal(browser):
    browser.call("Emulation.clearDeviceMetricsOverride")
    cdp("Target.activateTarget", targetId=browser.target)


def settle(browser, timeout=8.0, interval=0.4):
    deadline = time.monotonic() + timeout
    previous = -1
    while time.monotonic() < deadline:
        size = browser.evaluate("document.querySelector('main')?.innerText.length ?? document.body.innerText.length")
        if size and size == previous:
            return size
        previous = size
        time.sleep(interval)
    return previous


def add_session_arguments(parser):
    parser.add_argument("--isolated", action="store_true", help="Launch a throwaway Chrome instead of attaching to yours.")
    parser.add_argument("--headed", action="store_true", help="With --isolated: show the window.")
    parser.add_argument("--port", type=int, default=9333)
    parser.add_argument("--profile", type=Path, help="With --isolated: keep this Chrome profile between runs.")


def session_from(args):
    return chrome_session(args.isolated, args.port, args.profile, args.headed)


def parse_arguments(parser):
    argv = sys.argv[1:]
    return parser.parse_args(argv[1:] if argv[:1] == ["--"] else argv)


def main():
    parser = argparse.ArgumentParser(description="Fast local browsing with a pre-execution veto.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--url-contains", action="append", default=[])
    parser.add_argument("--title-contains", action="append", default=[])
    parser.add_argument("--text-contains", action="append", default=[])
    parser.add_argument("--max-steps", type=int, default=10)
    add_session_arguments(parser)
    args = parse_arguments(parser)

    checks = (args.url_contains, args.title_contains, args.text_contains)
    success = contains(*checks) if any(checks) else None
    with session_from(args):
        result = browse(args.url, args.goal, success=success, max_steps=args.max_steps)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
