import ai_decide
import alerts


def test_unreachable_model_alerts_and_still_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_decide, "DECISIONS_LOG", tmp_path / "decisions.jsonl")
    monkeypatch.setattr(ai_decide, "CLAUDE_BIN", "/nonexistent/claude")
    decision = ai_decide.decide({"symbol": "AAA"}, {})
    assert decision["action"] == "ignore" and decision["reasoning"].startswith("CALL_ERROR")
    assert "CALL_ERROR" in (tmp_path / "decisions.jsonl").read_text()
    [alert] = alerts.load_alerts()
    assert alert["kind"] == "model_unreachable" and "AAA" in alert["message"]
