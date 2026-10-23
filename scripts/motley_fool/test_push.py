import alerts


def test_push_sends_to_topic_and_survives_failure(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.setattr(alerts, "load_dotenv", lambda *a: None)
    monkeypatch.setenv("NTFY_TOPIC", "my-topic")
    sent = []
    monkeypatch.setattr(alerts.urllib.request, "urlopen", lambda req, timeout: sent.append(req))
    assert alerts.push("AI trader: test", "hi")
    assert sent[0].full_url == "https://ntfy.sh/my-topic" and sent[0].data == b"hi"
    assert sent[0].get_header("Title") == "AI trader: test"

    def down(req, timeout):
        raise OSError("network down")

    monkeypatch.setattr(alerts.urllib.request, "urlopen", down)
    assert not alerts.push("t", "m")  # logged, not raised
    monkeypatch.setenv("NTFY_TOPIC", "")
    assert not alerts.push("t", "m")


def test_push_never_fires_under_pytest(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "my-topic")
    monkeypatch.setattr(alerts.urllib.request, "urlopen", lambda *a, **k: 1 / 0)
    assert not alerts.push("t", "m")
