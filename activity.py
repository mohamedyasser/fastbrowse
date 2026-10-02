import argparse
import json
import random
import time
import urllib.request
from dataclasses import asdict

from fastbrowse import add_session_arguments, open_page, parse_arguments, session_from, settle
from linkedin import is_login_wall, parse_feed, post_key, profile_activity_url

SIDECAR = "http://127.0.0.1:8765"
PAGE_TEXT = "document.querySelector('main')?.innerText ?? ''"
RELEVANCE = {
    "relevance": {
        "type": "choice",
        "instructions": "Is this ecommerce advertising performance content relevant?",
        "criteria": {"high": "directly relevant", "low": "weakly relevant", "none": "not relevant"},
    }
}


def collect_posts(browser, scrolls, pause=0.9):
    settle(browser)
    seen, posts = set(), []
    for step in range(scrolls + 1):
        for post in parse_feed(browser.evaluate(PAGE_TEXT) or ""):
            if post_key(post) not in seen:
                seen.add(post_key(post))
                posts.append(post)
        if step < scrolls:
            browser.evaluate("window.scrollBy(0, innerHeight * 1.5)")
            time.sleep(pause)
    return posts


def classify(text, sidecar=SIDECAR):
    body = json.dumps({"model": "multilingual", "state": {"body": text[:2500]}, "questions": RELEVANCE}).encode()
    request = urllib.request.Request(f"{sidecar}/v1/systemone", data=body, headers={"content-type": "application/json"})
    answer = json.load(urllib.request.urlopen(request, timeout=15))["answers"]["relevance"]
    return {"relevance": answer["choice"], "confidence": answer.get("answer_confidence", answer.get("confidence"))}


def read_profile(value, *, limit, scrolls, sidecar, triage):
    url = profile_activity_url(value)
    with open_page(url) as browser:
        settle(browser)
        current = browser.evaluate("location.href") or url
        if is_login_wall(current):
            return {"profile": value, "url": url, "ok": False, "error": "LinkedIn is not signed in in this Chrome"}
        posts = [p for p in collect_posts(browser, scrolls) if p.text][:limit]
    rows = []
    for post in posts:
        row = asdict(post)
        if triage:
            row.update(classify(post.text, sidecar))
        rows.append(row)
    return {"profile": value, "url": url, "ok": True, "posts": rows}


def main():
    parser = argparse.ArgumentParser(description="Read recent LinkedIn posts of profiles (read-only).")
    parser.add_argument("profiles", nargs="+", help="Profile URLs or slugs.")
    parser.add_argument("--limit", type=int, default=5, help="Posts kept per profile.")
    parser.add_argument("--scrolls", type=int, default=3)
    parser.add_argument("--triage", action="store_true", help="Add a coarse Laya relevance label per post.")
    parser.add_argument("--sidecar", default=SIDECAR)
    parser.add_argument("--min-pause", type=float, default=8.0, help="Seconds between profiles (human pacing).")
    parser.add_argument("--max-pause", type=float, default=25.0)
    add_session_arguments(parser)
    args = parse_arguments(parser)

    results = []
    with session_from(args):
        for index, value in enumerate(args.profiles):
            if index:
                time.sleep(random.uniform(args.min_pause, args.max_pause))
            try:
                results.append(read_profile(value, limit=args.limit, scrolls=args.scrolls, sidecar=args.sidecar, triage=args.triage))
            except Exception as error:
                results.append({"profile": value, "ok": False, "error": str(error)})
    print(json.dumps({"profiles": results}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    main()
