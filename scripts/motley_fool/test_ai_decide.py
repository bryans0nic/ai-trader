import ai_decide
import pytest

IGNORE = {"confidence": 0, "action": "ignore"}


@pytest.fixture(autouse=True)
def _tmp_log(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_decide, "DECISIONS_LOG", tmp_path / "decisions.jsonl")


def _reply(monkeypatch, content):
    monkeypatch.setattr(
        ai_decide, "_call_claude", lambda *_: {"content": content, "reasoning": "", "model": "m"}
    )


@pytest.mark.parametrize(
    "garbled",
    [
        "",
        "sorry, no idea",
        "{not json}",
        '{"confidence": 90}',
        '{"action": "yolo"}',
        '{"action": 5}',
        "[1, 2]",
    ],
)
def test_garbled_reply_is_ignore(monkeypatch, garbled):
    _reply(monkeypatch, garbled)
    d = ai_decide.decide({"symbol": "X"}, {})
    assert d["action"] == "ignore" and d["confidence"] == 0


def test_claude_failure_is_ignore(monkeypatch):
    def boom(*_):
        raise RuntimeError("claude exited 1: not logged in")

    monkeypatch.setattr(ai_decide, "_call_claude", boom)
    d = ai_decide.decide({"symbol": "X"}, {})
    assert d["action"] == "ignore" and "CALL_ERROR" in d["reasoning"]


def test_good_reply_passes_through(monkeypatch):
    _reply(monkeypatch, '{"confidence": 70, "action": "buy", "reasoning": "ok"}')
    assert ai_decide.decide({"symbol": "X"}, {})["action"] == "buy"
