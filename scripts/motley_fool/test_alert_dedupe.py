from datetime import timedelta

import ai_decide
import alerts


def test_repeat_failures_alert_once_within_window(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_decide, "DECISIONS_LOG", tmp_path / "decisions.jsonl")
    monkeypatch.setattr(ai_decide, "CLAUDE_BIN", "/nonexistent/claude")
    ai_decide.decide({"symbol": "AAA"}, {})
    ai_decide.decide({"symbol": "BBB"}, {})
    assert [a["kind"] for a in alerts.load_alerts()] == ["model_unreachable"]
    assert len((tmp_path / "decisions.jsonl").read_text().splitlines()) == 2  # both still logged


def test_alert_again_after_window():
    assert alerts.notify("k", "m", dedupe_key="k", within=timedelta(hours=1))
    assert not alerts.notify("k", "m", dedupe_key="k", within=timedelta(hours=1))
    assert alerts.notify("k", "m", dedupe_key="k", within=timedelta(0))  # window elapsed
