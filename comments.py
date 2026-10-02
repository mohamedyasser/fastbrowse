import argparse
import json
import time
from dataclasses import asdict

from fastbrowse import add_session_arguments, open_page, parse_arguments, session_from, settle
from linkedin import is_login_wall, parse_feed

PAGE_TEXT = "document.querySelector('main')?.innerText ?? ''"
SORT_LABELS = {"Most relevant", "Most recent"}
SECTION_END = "About"


def comments_section(text):
    lines = text.split("\n")
    start = next((i + 1 for i, line in enumerate(lines) if line in SORT_LABELS), None)
    if start is None:
        return ""
    end = next((i for i in range(start, len(lines)) if lines[i] == SECTION_END), len(lines))
    return "\n".join(line for line in lines[start:end] if line.strip())


def read_thread(url, settle_seconds=4.0):
    with open_page(url) as browser:
        settle(browser)
        if is_login_wall(browser.evaluate("location.href") or url):
            return {"url": url, "ok": False, "error": "LinkedIn is not signed in in this Chrome"}
        time.sleep(settle_seconds)
        browser.evaluate("window.scrollBy(0, innerHeight * 2)")
        time.sleep(2)
        text = browser.evaluate(PAGE_TEXT) or ""
    post = next(iter(parse_feed(text)), None)
    return {"url": url, "ok": True, "post": asdict(post) if post else None, "comments": comments_section(text)}


def main():
    parser = argparse.ArgumentParser(description="Read a LinkedIn post and its existing comments (read-only).")
    parser.add_argument("url", help="Post permalink.")
    add_session_arguments(parser)
    args = parse_arguments(parser)
    with session_from(args):
        result = read_thread(args.url)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
