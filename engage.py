import argparse
import json
import re
import time
import urllib.request

from fastbrowse import add_session_arguments, parse_arguments, reveal, session_from, settle
from laya_ultrafast.browser import Browser
from linkedin import is_login_wall, parse_post

OLLAMA = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
MAX_COMMENT = 600
COMMENT_LABELS = ("Comment", "تعليق")
SYSTEM = (
    "You draft a LinkedIn comment for a Flowfy co-founder. Flowfy connects a store's real orders to its ad "
    "platforms: server-side tracking, event deduplication and attribution.\n"
    "Rules: reply in the same language and dialect as the post (Egyptian Arabic for Egyptian Arabic posts). "
    "Two or three short sentences. Add one concrete insight that builds on the post, then end with one genuine "
    "question. Mention Flowfy only when the post is directly about tracking, attribution or numbers that do not "
    "match the store, and then in one clause, never a link or a pitch. No hashtags, no emojis, no flattery. "
    "Output only the comment text."
)
FIND_EDITOR = (
    "(() => { const all = [...document.querySelectorAll('[contenteditable=\"true\"]')];"
    " return all.find(e => /comment/i.test(e.getAttribute('aria-label') || '')) ?? (all.length === 1 ? all[0] : null); })"
)
OPEN_COMPOSER = (
    "(() => { const labels = " + json.dumps(list(COMMENT_LABELS)) + ";"
    " const b = [...document.querySelectorAll('button')].find(b => labels.includes(b.innerText.trim()));"
    " if (b) b.click(); return !!b; })()"
)


def draft_comment(post_text, *, model=DEFAULT_MODEL, angle="", base=OLLAMA):
    user = f"Post:\n{post_text[:3000]}" + (f"\n\nAngle to take: {angle}" if angle else "")
    body = json.dumps({
        "model": model, "temperature": 0.4,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
    }).encode()
    request = urllib.request.Request(f"{base}/chat/completions", data=body, headers={"content-type": "application/json"})
    text = json.load(urllib.request.urlopen(request, timeout=120))["choices"][0]["message"]["content"].strip().strip('"“”')
    if not text or len(text) > MAX_COMMENT:
        raise ValueError(f"Draft is empty or longer than {MAX_COMMENT} characters")
    return text


def has_editor(browser):
    return bool(browser.evaluate(f"!!({FIND_EDITOR})()"))


def open_composer(browser, timeout=6.0):
    if has_editor(browser):
        return True
    browser.evaluate(OPEN_COMPOSER)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if has_editor(browser):
            return True
        time.sleep(0.2)
    return False


def normalize(text):
    return re.sub(r"\s+", " ", text or "").strip()


def fill_composer(browser, text):
    browser.evaluate(f"(() => {{ ({FIND_EDITOR})().focus(); return true; }})()")
    browser.call("Input.insertText", text=text)
    shown = browser.evaluate(f"(() => ({FIND_EDITOR})()?.innerText ?? '')()")
    return normalize(shown) == normalize(text)


def prepare(url, *, model, angle, dry_run, text=None, base=OLLAMA):
    if text is not None and not 0 < len(text.strip()) <= MAX_COMMENT:
        return {"ok": False, "url": url, "error": f"--text must be 1-{MAX_COMMENT} characters"}
    browser = Browser(url)
    keep_open = False
    try:
        settle(browser)
        if is_login_wall(browser.evaluate("location.href") or url):
            return {"ok": False, "url": url, "error": "LinkedIn is not signed in in this Chrome"}
        if text is not None:
            draft = text.strip()
        else:
            post = parse_post(browser.evaluate("document.querySelector('main')?.innerText ?? ''") or "")
            if not post:
                return {"ok": False, "url": url, "error": "Could not read the post text"}
            draft = draft_comment(post, model=model, angle=angle, base=base)
        if dry_run:
            return {"ok": True, "url": url, "draft": draft, "filled": False}
        if not open_composer(browser):
            return {"ok": False, "url": url, "draft": draft, "error": "Comment box did not open"}
        if not fill_composer(browser, draft):
            return {"ok": False, "url": url, "draft": draft, "error": "Comment box does not contain the draft"}
        reveal(browser)
        keep_open = True
        return {"ok": True, "url": url, "draft": draft, "filled": True, "next": "Review the draft in Chrome and press Post yourself."}
    finally:
        if not keep_open:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description="Draft a comment and fill LinkedIn's comment box. Never presses Post.")
    parser.add_argument("url", help="Post URL.")
    parser.add_argument("--angle", default="", help="Optional direction for the comment.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--text", help="Fill this exact comment instead of drafting one with the local model.")
    parser.add_argument("--dry-run", action="store_true", help="Only print the draft; do not touch the comment box.")
    add_session_arguments(parser)
    args = parse_arguments(parser)

    with session_from(args):
        result = prepare(args.url, model=args.model, angle=args.angle, dry_run=args.dry_run, text=args.text)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
