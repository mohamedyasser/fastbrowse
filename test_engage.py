import inspect
import io
import json

import pytest

import engage


class FakeBrowser:
    def __init__(self, editor_after_click=True, editor_present=False, shown=""):
        self.editor = editor_present
        self.editor_after_click = editor_after_click
        self.shown = shown
        self.scripts = []
        self.calls = []

    def evaluate(self, script):
        self.scripts.append(script)
        if script == engage.OPEN_COMPOSER:
            self.editor = self.editor_after_click
            return True
        if script.startswith("!!("):
            return self.editor
        if "?.innerText" in script:
            return self.shown
        return True

    def call(self, method, **params):
        self.calls.append((method, params))


def reply(text):
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": text}}]}).encode())


def test_composer_is_never_clicked_when_an_editor_is_already_open():
    browser = FakeBrowser(editor_present=True)
    assert engage.open_composer(browser)
    assert engage.OPEN_COMPOSER not in browser.scripts


def test_composer_opens_with_a_single_click_and_reports_failure_when_it_never_appears():
    opened = FakeBrowser()
    assert engage.open_composer(opened, timeout=1)
    assert opened.scripts.count(engage.OPEN_COMPOSER) == 1

    missing = FakeBrowser(editor_after_click=False)
    assert not engage.open_composer(missing, timeout=0.3)


def test_fill_types_through_the_browser_and_compares_ignoring_whitespace():
    good = FakeBrowser(shown="سؤال   جميل\nفعلا؟")
    assert engage.fill_composer(good, "سؤال جميل فعلا؟")
    assert good.calls == [("Input.insertText", {"text": "سؤال جميل فعلا؟"})]
    assert not engage.fill_composer(FakeBrowser(shown="something else"), "سؤال جميل فعلا؟")


def test_the_only_click_in_the_module_is_the_composer_opener():
    assert inspect.getsource(engage).count(".click(") == 1
    assert ".click()" in engage.OPEN_COMPOSER


def test_draft_prompt_carries_the_post_and_angle(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return reply('"تعليق قصير؟"')

    monkeypatch.setattr(engage.urllib.request, "urlopen", fake_urlopen)
    draft = engage.draft_comment("نص البوست", angle="ركز على الـ CAPI", model="m")
    user = captured["body"]["messages"][1]["content"]
    assert draft == "تعليق قصير؟"
    assert "نص البوست" in user and "ركز على الـ CAPI" in user
    assert captured["body"]["model"] == "m"


@pytest.mark.parametrize("text", ["", "x" * (engage.MAX_COMMENT + 1)])
def test_unusable_drafts_are_rejected(monkeypatch, text):
    monkeypatch.setattr(engage.urllib.request, "urlopen", lambda request, timeout: reply(text))
    with pytest.raises(ValueError):
        engage.draft_comment("post")
