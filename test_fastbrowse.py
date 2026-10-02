import os
import re

import pytest

import fastbrowse
from fastbrowse import DENY, browse, contains


def page(url="https://site.test/a", title="A", text="", actions=()):
    return {"url": url, "title": title, "text": text, "fingerprint": url + title, "actions": list(actions)}


def action(identifier, label):
    return {"id": identifier, "label": label, "kind": "click"}


class FakeBrowser:
    def observe(self, screenshot=False):
        return page()


class FakeAgent:
    def __init__(self, steps):
        self.steps = steps
        self.index = 0
        self.state = {
            "page": steps[0]["page"], "history": [], "decision": None,
            "status": "ready", "elapsed_ms": 5, "browser": FakeBrowser(),
        }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def command(self, name, body=None):
        step = self.steps[self.index]
        if name == "predict":
            self.state["decision"] = {"choice": step["choice"]}
            return
        self.state["decision"] = None
        if step["choice"] in {"DONE", "BLOCKED"}:
            self.state["status"] = step["choice"].lower()
            return
        label = next(a["label"] for a in self.state["page"]["actions"] if a["id"] == step["choice"])
        self.state["history"].append({"action": label})
        self.state["page"] = step["next"]
        self.index += 1


def run(steps, **options):
    return browse("https://site.test", "goal", factory=lambda url, goal: FakeAgent(steps), **options)


def test_success_stops_as_soon_as_the_page_matches():
    done = page(url="https://site.test/done")
    steps = [{"page": page(actions=[action("e1", "Open")]), "choice": "e1", "next": done}]
    result = run(steps, success=contains(url=["done"]))
    assert (result.ok, result.reason, result.steps) == (True, "success", 1)


def test_veto_happens_before_the_action_runs():
    steps = [{"page": page(actions=[action("e1", "Send")]), "choice": "e1", "next": page()}]
    result = run(steps)
    assert (result.ok, result.reason, result.steps, result.error) == (False, "vetoed", 0, "Send")


def test_callable_veto_sees_the_action_and_the_page():
    seen = []

    def deny(chosen, current):
        seen.append((chosen["label"], current["url"]))
        return current["url"].endswith("/a")

    steps = [{"page": page(actions=[action("e1", "Open")]), "choice": "e1", "next": page()}]
    result = run(steps, deny=deny)
    assert (result.reason, seen) == ("vetoed", [("Open", "https://site.test/a")])


def test_max_steps_bounds_a_wandering_agent():
    loop = page(actions=[action("e1", "Next")])
    steps = [{"page": loop, "choice": "e1", "next": loop} for _ in range(5)]
    result = run(steps, success=contains(text=["never"]), max_steps=2)
    assert (result.ok, result.reason, result.steps) == (False, "max_steps", 2)


def test_done_needs_independent_proof_when_a_check_is_given():
    steps = [{"page": page(), "choice": "DONE"}]
    assert run(steps, success=contains(text=["proof"])).reason == "done_unverified"
    assert run(steps).reason == "agent_done"


def test_blocked_is_reported():
    assert run([{"page": page(), "choice": "BLOCKED"}]).reason == "blocked"


def test_navigating_error_is_retried_once():
    calls = []

    def factory(url, goal):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Document is navigating")
        return FakeAgent([{"page": page(), "choice": "DONE"}])

    result = browse("https://site.test", "goal", factory=factory)
    assert (result.ok, len(calls)) == (True, 2)


def test_other_errors_are_not_retried():
    calls = []

    def factory(url, goal):
        calls.append(1)
        raise RuntimeError("boom")

    result = browse("https://site.test", "goal", factory=factory)
    assert (result.reason, result.error, len(calls)) == ("error", "boom", 1)


def test_contains_requires_every_needle_case_insensitively():
    check = contains(url=["WIKI"], title=["gödel"], text=["theorem"])
    assert check(page(url="https://en.wikipedia.org/wiki/x", title="Gödel", text="A Theorem."))
    assert not check(page(url="https://en.wikipedia.org/wiki/x", title="Gödel", text="nothing"))


@pytest.mark.parametrize("label", ["Send", "Connect", "Like", "Post", "Follow", "إرسال", "متابعة", "Order history"])
def test_deny_blocks_side_effect_labels(label):
    assert DENY.search(label)


@pytest.mark.parametrize("label", ["Search hotels", "Nile View Hotel", "Search Wikipedia", "Scroll down", "Full name"])
def test_deny_allows_reading_labels(label):
    assert not DENY.search(label)


def test_local_planner_defaults_do_not_override_the_environment(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL", "custom")
    run([{"page": page(), "choice": "DONE"}])
    assert os.environ["TEXT_MODEL"] == "custom"
    assert re.match(r"http://localhost", os.environ["TEXT_MODEL_BASE_URL"])


def test_a_leading_double_dash_forwarded_by_pnpm_is_dropped(monkeypatch):
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("profiles", nargs="+")
    parser.add_argument("--limit", type=int, default=5)
    monkeypatch.setattr(sys, "argv", ["activity.py", "--", "sara", "--limit", "3"])
    args = fastbrowse.parse_arguments(parser)
    assert (args.profiles, args.limit) == (["sara"], 3)


def test_attaching_to_your_chrome_clears_a_stale_isolated_endpoint(monkeypatch):
    monkeypatch.setenv("BU_CDP_URL", "http://127.0.0.1:9333")
    monkeypatch.setattr(fastbrowse, "reset_daemon", lambda: None)
    with fastbrowse.chrome_session(isolated=False):
        assert "BU_CDP_URL" not in os.environ
