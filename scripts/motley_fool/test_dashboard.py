import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
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
    closed = []
    day = 86400
    client = ns(
        closed=closed,
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
                avg_entry_price="100",
            )
        ],
        get_orders=lambda filter=None: [
            ns(
                symbol="AAA",
                side=ns(value="sell"),
                status=ns(value="accepted"),
                qty="10",
                notional=None,
                filled_avg_price=None,
                submitted_at=datetime(2026, 9, 5, 14, 0, tzinfo=UTC),
            )
        ],
        get_portfolio_history=lambda req: ns(
            timestamp=[1756684800 + i * day for i in range(4)],
            equity=[None, 10000.0, 10200.0, 10500.0],
        ),
        close_position=closed.append,
    )
    monkeypatch.setattr(
        metrics,
        "sp500_closes",
        lambda start: {"2025-09-02": 5000.0, "2025-09-03": 5050.0, "2025-09-04": 5100.0},
    )
    monkeypatch.setattr(dashboard, "PIPELINE_PLIST", tmp_path / "pipeline.plist")
    test_pause_run_now_exempt_and_sell.client = client
    srv = ThreadingHTTPServer(
        ("127.0.0.1", 0), dashboard.make_handler(lambda: client, {"127.0.0.1"})
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(url):
    return urllib.request.urlopen(url).read().decode()


def test_decisions_newest_first_and_reasoning_matches_log(server):
    html = get(server + "/").split("<section id=decisions>")[1]
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


def test_home_screen_icon(server):
    assert "rel=apple-touch-icon" in get(server + "/")
    r = urllib.request.urlopen(server + "/apple-touch-icon.png")
    assert r.headers["Content-Type"] == "image/png" and r.read()[:4] == b"\x89PNG"


def post(url, data=b""):
    return (
        urllib.request.urlopen(urllib.request.Request(url, data=data, method="POST"))
        .read()
        .decode()
    )


def test_status_strip_orders_and_unread_banner(server):
    html = get(server + "/")
    assert "Never run on this Mac" in html and "Not scheduled" in html
    assert (
        "accepted" in html and "<time datetime='2026-09-05T14:00:00+00:00'>" in html
    )  # pending order
    assert "role=alert" not in html

    alerts.write_run_status(
        {
            "started": "2026-09-05T14:00:00+00:00",
            "finished": "2026-09-05T14:00:09+00:00",
            "ok": True,
            "summary": "no new picks",
            "session_ok": False,
        }
    )
    alerts.notify("stop_loss", "Stop-loss: sell order placed for AAA")
    html = get(server + "/")
    assert "no new picks" in html and "Needs login" in html
    assert "role=alert" in html and "Alerts <b>(1)</b>" in html
    html = post(server + "/alerts/read")
    assert "role=alert" not in html and "Alerts <b>" not in html


def test_chart_position_detail_and_outcomes(server):
    html = get(server + "/?range=1w")
    assert "<polyline class='line s-portfolio'" in html and "<polyline class='line s-sp500'" in html
    assert ">+5.0%</text>" in html and ">+2.0%</text>" in html  # 10000 -> 10500, 5000 -> 5100
    assert "Show as table" in html and "aria-current=true>1W" in html
    assert (
        "Avg entry" in html and "20.0 points above the −10% stop-loss" in html
    )  # +10% vs -10% limit
    assert "See the decision that bought it" in html
    assert "Since buy" in html and "Would be" in html


def test_decision_filters(server):
    html = get(server + "/?action=ignore")
    assert "1 of 2 decisions" in html and "second" in html and "first &lt;b&gt;" not in html
    assert "No decisions match" in get(server + "/?q=ZZZ")
    assert "1 of 2 decisions" in get(server + "/?q=aa")


def test_pause_run_now_exempt_and_sell(server, monkeypatch):
    assert "Trading paused" in post(server + "/pause", b"paused=1")
    assert alerts.get_settings()["trading_paused"] is True
    post(server + "/pause", b"paused=0")
    assert alerts.get_settings()["trading_paused"] is False

    started = []
    monkeypatch.setattr(dashboard, "start_pipeline_run", lambda: started.append(1))
    assert "Pipeline run started" in post(server + "/run")
    assert started == [1]

    assert "Exempt from the stop-loss" in post(server + "/positions/exempt", b"symbol=AAA&exempt=1")
    assert alerts.get_settings()["stop_loss_exempt"] == ["AAA"]

    confirm = get(server + "/sell?symbol=AAA")
    assert (
        "Yes, sell AAA" in confirm and test_pause_run_now_exempt_and_sell.client.closed == []
    )  # GET never sells
    post(server + "/positions/sell", b"symbol=AAA")
    assert test_pause_run_now_exempt_and_sell.client.closed == ["AAA"]
    for bad in (b"symbol=ZZZ", b"symbol=a;b"):
        with pytest.raises(urllib.error.HTTPError):
            post(server + "/positions/sell", bad)
