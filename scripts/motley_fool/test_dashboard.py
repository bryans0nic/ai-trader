import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import ai_decide
import alerts
import dashboard
import metrics
import pytest
import state


def _write_log(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _dec(ts, sym, action, why):
    return {
        "timestamp": ts,
        "symbol": sym,
        "signal": {"symbol": sym},
        "portfolio_snapshot": {},
        "model": "claude",
        "model_reasoning": "",
        "decision": {"action": action, "confidence": 60, "reasoning": why},
    }


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_decide, "DECISIONS_LOG", tmp_path / "decisions.jsonl")
    _write_log(
        ai_decide.DECISIONS_LOG,
        [
            _dec("2026-09-01T10:00:00+00:00", "AAA", "buy", "first <b>reason</b>"),
            _dec("2026-09-02T10:00:00+00:00", "BBB", "ignore", "second"),
        ],
    )
    state.save_state(
        {
            "picks": {"REC": {"symbol": "REC", "action": "Buy", "rec_date": "09/01/2026"}},
            "last_scraped": None,
        }
    )
    prices = {"AAA": (100, 110), "BBB": (50, 45), "REC": (10, 12), "^GSPC": (5000, 5100)}
    monkeypatch.setattr(metrics, "price_on", lambda s, day: prices[s][0])
    monkeypatch.setattr(metrics, "latest_price", lambda s: prices[s][1])
    ns = SimpleNamespace
    client = ns(
        get_account=lambda: ns(
            equity="10500", last_equity="10000", cash="4000", buying_power="8000"
        ),
        get_all_positions=lambda: [
            ns(
                symbol="AAA",
                qty="10",
                market_value="1100",
                unrealized_pl="100",
                unrealized_plpc="0.1",
            )
        ],
    )
    srv = ThreadingHTTPServer(
        ("127.0.0.1", 0), dashboard.make_handler(lambda: client, {"127.0.0.1"})
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(url):
    return urllib.request.urlopen(url).read().decode()


def test_decisions_newest_first_and_reasoning_matches_log(server):
    html = get(server + "/")
    assert html.index("/decision/1") < html.index("/decision/0")  # BBB (newer) before AAA
    detail = get(server + "/decision/0")
    assert (
        "<pre id=reasoning>first &lt;b&gt;reason&lt;/b&gt;</pre>" in detail
    )  # escaped, exact log text


def test_account_and_performance_numbers(server):
    html = get(server + "/")
    assert "$10,500.00" in html and "$8,000.00" in html and "+10.00%" in html
    assert "id=ret-ours>+10.00%" in html  # AAA 100 -> 110
    assert "id=ret-sp500>+2.00%" in html  # 5000 -> 5100
    assert "id=ret-advisor>+20.00%" in html  # REC 10 -> 12
    assert "-10.00%" in html  # ignored BBB 50 -> 45


def test_alert_appears_in_notification_center(server):
    req = urllib.request.Request(server + "/alerts/test", method="POST", data=b"")
    urllib.request.urlopen(req)
    assert "Test alert from the dashboard" in get(server + "/")
    assert alerts.load_alerts()[0]["kind"] == "test"


def test_settings_form_and_bad_host(server):
    urllib.request.urlopen(urllib.request.Request(server + "/settings", data=b"stop_loss_pct=7"))
    assert alerts.get_settings()["stop_loss_pct"] == 7
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(
            urllib.request.Request(server + "/", headers={"Host": "evil.example"})
        )
    assert e.value.code == 403


def test_keys_saved_to_env_and_never_shown(server, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.setattr(dashboard, "ENV_PATH", env)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    assert "No keys saved yet" in get(server + "/")

    key, secret = "PKTESTKEY1234567890A", "s3cr3t" * 6
    body = f"api_key={key}&secret_key={secret}".encode()
    html = (
        urllib.request.urlopen(urllib.request.Request(server + "/keys", data=body)).read().decode()
    )
    assert "Alpaca keys saved" in html and "ends in 890A" in html
    assert secret not in html and key not in html
    assert (
        f"ALPACA_SECRET_KEY='{secret}'" in env.read_text() and env.stat().st_mode & 0o777 == 0o600
    )

    with pytest.raises(urllib.error.HTTPError) as e:  # newline would inject extra .env lines
        urllib.request.urlopen(
            urllib.request.Request(server + "/keys", data=b"api_key=abc%0AX=1&secret_key=short")
        )
    assert e.value.code == 400
