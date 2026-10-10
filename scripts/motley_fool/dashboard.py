"""Web dashboard: decision history + reasoning, live account, performance, alerts, risk settings.

Serves on localhost only. Other devices reach it through Tailscale Serve (tailnet-only
HTTPS proxy to this port; see install-mac.sh), same as ClaudeOS and SocialOS.

    uv run python scripts/motley_fool/dashboard.py [--port 8765]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import ai_decide
import alerts
import metrics
from dotenv import load_dotenv, set_key

PORT = 8765
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
KEY_RE = re.compile(r"[A-Za-z0-9]{16,128}")
TAILSCALE_APP_BIN = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


def all_decisions() -> list[dict]:
    """Every logged decision, newest first, each with `id` = its line number in the log."""
    if not ai_decide.DECISIONS_LOG.exists():
        return []
    records = []
    with open(ai_decide.DECISIONS_LOG) as f:
        for i, line in enumerate(f):
            if line.strip():
                records.append({"id": i, **json.loads(line)})
    return records[::-1]


def tailscale_names() -> set[str]:
    """This machine's MagicDNS names (full and short), or an empty set if Tailscale is down."""
    exe = shutil.which("tailscale") or TAILSCALE_APP_BIN
    try:
        out = subprocess.run(
            [exe, "status", "--json"], capture_output=True, text=True, timeout=5
        ).stdout
        dns = json.loads(out)["Self"].get("DNSName", "").rstrip(".").lower()
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        return set()
    return {dns, dns.split(".")[0]} - {""}


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.2f}%"


def _usd(v: float) -> str:
    return f"${v:,.2f}"


def _signed(v: float | None, text: str) -> str:
    """Wrap text in a gain/loss colour class (the sign is also in the text, so colour isn't the only cue)."""
    cls = "" if not v else ("pos" if v > 0 else "neg")
    return f"<span class='{cls}'>{text}</span>"


def _tile(label: str, value: str, sub: str = "") -> str:
    return f"<div class=tile><div class=label>{label}</div><div class=value>{value}</div><div class=sub>{sub}</div></div>"


def _empty(text: str) -> str:
    return f"<p class=empty>{escape(text)}</p>"


def keys_status() -> dict:
    """Which Alpaca keys are on file. Never returns the secret; only the key ID's last 4 characters."""
    load_dotenv(ENV_PATH)
    key, secret = os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_SECRET_KEY", "")
    return {"key_tail": key[-4:] if key else None, "has_secret": bool(secret)}


def save_alpaca_keys(api_key: str, secret_key: str) -> None:
    """Store paper-trading keys in the repo's .env (owner-only file) and in this process."""
    api_key, secret_key = api_key.strip(), secret_key.strip()
    for name, value in (("API key ID", api_key), ("Secret key", secret_key)):
        if not KEY_RE.fullmatch(value):
            raise ValueError(f"{name} should be 16-128 letters and digits, with no spaces.")
    ENV_PATH.touch(mode=0o600, exist_ok=True)
    ENV_PATH.chmod(0o600)
    for name, value in (("ALPACA_API_KEY", api_key), ("ALPACA_SECRET_KEY", secret_key)):
        set_key(str(ENV_PATH), name, value)
        os.environ[name] = value


def _account_html(client_factory) -> str:
    try:
        s = metrics.account_snapshot(client_factory())
    except (
        Exception,
        SystemExit,
    ) as e:  # missing keys / Alpaca down: the rest of the page should still load
        if not keys_status()["key_tail"]:
            return "<p class=empty>No Alpaca keys yet. <a href='#keys'>Add your paper-trading keys</a> to see the account.</p>"
        return f"<p class=err>Account unavailable: {escape(str(e))}</p>"
    tiles = (
        _tile("Equity", _usd(s["equity"]))
        + _tile("Buying power", _usd(s["buying_power"]), f"Cash {_usd(s['cash'])}")
        + _tile(
            "Today",
            _signed(s["day_pl"], _usd(s["day_pl"])),
            _signed(s["day_pl"], f"{s['day_pl_pct']:+.2f}%"),
        )
        + _tile("Open P/L", _signed(s["total_unrealized_pl"], _usd(s["total_unrealized_pl"])))
    )
    rows = "".join(
        f"<li><div><b>{escape(p['symbol'])}</b><small>{p['qty']:g} sh · {_usd(p['market_value'])}</small></div>"
        f"<div class=num>{_signed(p['unrealized_pl'], _usd(p['unrealized_pl']))}"
        f"<small>{_signed(p['unrealized_pl'], _pct(p['unrealized_plpc']))}</small></div></li>"
        for p in s["positions"]
    )
    return f"<div class=tiles>{tiles}</div><h3>Positions</h3>" + (
        f"<ul class=list>{rows}</ul>" if rows else _empty("No open positions.")
    )


def _performance_html(decisions: list[dict]) -> str:
    try:
        b = metrics.benchmarks(decisions)
        ignored = metrics.ignored_performance(decisions)
    except Exception as e:
        return f"<p class=err>Performance unavailable: {escape(str(e))}</p>"
    tiles = (
        f"<div class=tile><div class=label>Our buys ({b['n_buys']})</div><div class=value id=ret-ours>{_pct(b['ours'])}</div></div>"
        f"<div class=tile><div class=label>S&amp;P 500, same dates</div><div class=value id=ret-sp500>{_pct(b['sp500'])}</div></div>"
        f"<div class=tile><div class=label>Stock Advisor recs ({b['n_recs']})</div><div class=value id=ret-advisor>{_pct(b['advisor'])}</div></div>"
    )
    ig = "".join(
        f"<li><a class=row href='/decision/{r['id']}'><div><b>{escape(r['symbol'] or '?')}</b>"
        f"<small>ignored {r['day']}</small></div>"
        f"<div class=num>{_signed(r['change_pct'], _pct(r['change_pct']))}</div></a></li>"
        for r in ignored
    )
    return (
        f"<p class=hint>Average return since each pick's date.</p><div class=tiles>{tiles}</div>"
        "<h3>Ignored picks since the decision</h3>"
        + (f"<ul class=list>{ig}</ul>" if ig else _empty("No ignored picks yet."))
    )


def _alerts_html() -> str:
    rows = "".join(
        f"<li><div><b>{escape(a['kind'].replace('_', ' '))}</b><small>{escape(a['timestamp'][:16].replace('T', ' '))} UTC</small>"
        f"<p>{escape(a['message'])}</p></div></li>"
        for a in alerts.load_alerts()
    )
    return (
        f"<ul class=list id=alerts>{rows}</ul>" if rows else _empty("No alerts.")
    ) + "<form method=post action=/alerts/test><button class=quiet>Send test alert</button></form>"


def _settings_html() -> str:
    s = alerts.get_settings()
    k = keys_status()
    if k["key_tail"] and k["has_secret"]:
        status = f"Keys saved (key ID ends in {escape(k['key_tail'])}). Enter both again to replace them."
    else:
        status = "No keys saved yet."
    return (
        "<h3>Risk limits</h3><form method=post action=/settings>"
        "<label>Stop-loss per position (%)"
        f"<input name=stop_loss_pct type=number inputmode=decimal step=0.1 min=0.1 max=100 required value='{s['stop_loss_pct']:g}'></label>"
        "<label>Daily-loss kill switch (%)"
        f"<input name=daily_loss_pct type=number inputmode=decimal step=0.1 min=0.1 max=100 required value='{s['daily_loss_pct']:g}'></label>"
        "<button>Save limits</button></form>"
        f"<h3 id=keys>Alpaca paper-trading keys</h3><p class=hint id=keys-status>{status}</p>"
        "<form method=post action=/keys autocomplete=off>"
        "<label>API key ID<input name=api_key required autocomplete=off autocapitalize=off autocorrect=off spellcheck=false></label>"
        "<label>Secret key<input name=secret_key type=password required autocomplete=off></label>"
        "<button>Save keys</button></form>"
        "<p class=hint>Stored only in the .env file on the MacBook and never shown again. "
        "Use paper keys: this app only talks to Alpaca's paper account.</p>"
    )


def _decisions_html(decisions: list[dict]) -> str:
    rows = "".join(
        f"<li><a class=row href='/decision/{d['id']}'><div><b>{escape(d['symbol'] or '?')}</b> "
        f"<span class='badge {escape(d['decision']['action'])}'>{escape(d['decision']['action'])}</span>"
        f"<small>{escape(d['timestamp'][:16].replace('T', ' '))} UTC · confidence {escape(str(d['decision'].get('confidence', '')))}</small>"
        f"<p>{escape(d['decision'].get('reasoning', '')[:140])}</p></div><div class=chev>›</div></a></li>"
        for d in decisions
    )
    return f"<ul class=list>{rows}</ul>" if rows else _empty("No decisions logged yet.")


STYLE = """<style>
:root{color-scheme:light dark;--bg:#f4f5f7;--card:#fff;--ink:#16181d;--mute:#5d6470;--line:#e3e5ea;--accent:#1f5fd1;--pos:#12733b;--neg:#b3261e}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#191c22;--ink:#eceef2;--mute:#9aa1ad;--line:#2a2e37;--accent:#7aa7ff;--pos:#5fd08a;--neg:#ff8a80}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 -apple-system,system-ui,sans-serif;padding:0 max(12px,env(safe-area-inset-right)) calc(24px + env(safe-area-inset-bottom)) max(12px,env(safe-area-inset-left))}
main{max-width:720px;margin:0 auto}
header{padding:calc(14px + env(safe-area-inset-top)) 0 4px}h1{font-size:22px;margin:0}
nav{position:sticky;top:0;z-index:1;display:flex;gap:6px;overflow-x:auto;padding:8px 0;background:var(--bg);scrollbar-width:none}
nav a{flex:none;padding:10px 14px;min-height:44px;border-radius:22px;background:var(--card);border:1px solid var(--line);color:var(--ink);text-decoration:none;font-size:15px}
section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:12px 0;scroll-margin-top:68px}
h2{font-size:18px;margin:0 0 10px}h3{font-size:15px;margin:18px 0 6px;color:var(--mute);scroll-margin-top:68px}
a{color:var(--accent)}small{display:block;color:var(--mute);font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}
.tile{border:1px solid var(--line);border-radius:10px;padding:10px}.label,.sub{color:var(--mute);font-size:13px}
.value{font-size:20px;font-weight:600;font-variant-numeric:tabular-nums}
.list{list-style:none;margin:0;padding:0}.list li{border-top:1px solid var(--line)}.list li:first-child{border-top:0}
.list li,.row{display:flex;justify-content:space-between;align-items:center;gap:12px}
.list li>div,.row{padding:10px 0;min-height:44px}.row{width:100%;color:inherit;text-decoration:none}
.list p{margin:4px 0 0;color:var(--mute);font-size:14px;overflow-wrap:anywhere}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;flex:none}.chev{color:var(--mute);font-size:22px;flex:none}
.pos{color:var(--pos)}.neg{color:var(--neg)}.err{color:var(--neg)}.empty,.hint{color:var(--mute);font-size:14px;margin:6px 0}
.badge{font-size:12px;padding:2px 8px;border-radius:10px;border:1px solid var(--line);text-transform:uppercase;letter-spacing:.03em}
.badge.buy{color:var(--pos)}.badge.exit{color:var(--neg)}
label{display:block;font-size:14px;color:var(--mute);margin:10px 0}
input{display:block;width:100%;margin-top:4px;padding:12px;font-size:16px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink)}
button{width:100%;min-height:48px;margin-top:6px;border:0;border-radius:10px;background:var(--accent);color:var(--card);font-size:16px;font-weight:600}
button.quiet{background:transparent;color:var(--accent);border:1px solid var(--line)}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.flash{border-radius:10px;padding:12px;margin:12px 0;border:1px solid var(--line);background:var(--card)}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.5 ui-monospace,monospace;margin:0}
</style>"""

FLASH = {
    "keys": "Alpaca keys saved.",
    "limits": "Risk limits saved.",
    "alert": "Test alert sent.",
}


def page(body: str, title: str = "Trader dashboard") -> bytes:
    return (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1,viewport-fit=cover'>"
        f"<title>{escape(title)}</title>{STYLE}<main><header><h1>{escape(title)}</h1></header>{body}</main></html>"
    ).encode()


def index_page(client_factory, saved: str = "") -> bytes:
    decisions = all_decisions()
    flash = f"<p class=flash role=status>{FLASH[saved]}</p>" if saved in FLASH else ""
    sections = [
        ("account", "Account", _account_html(client_factory)),
        ("performance", "Performance", _performance_html(decisions)),
        ("alerts-section", "Alerts", _alerts_html()),
        ("decisions", "Decisions", _decisions_html(decisions)),
        ("settings", "Settings", _settings_html()),
    ]
    nav = "<nav>" + "".join(f"<a href='#{i}'>{t}</a>" for i, t, _ in sections) + "</nav>"
    return page(
        nav
        + flash
        + "".join(f"<section id={i}><h2>{t}</h2>{html}</section>" for i, t, html in sections)
    )


def decision_page(decision_id: int) -> bytes | None:
    d = next((d for d in all_decisions() if d["id"] == decision_id), None)
    if d is None:
        return None
    dec = d["decision"]
    action = escape(dec["action"])
    body = (
        "<nav><a href='/#decisions'>‹ All decisions</a></nav>"
        f"<section><p><span class='badge {action}'>{action}</span> confidence {escape(str(dec.get('confidence', '')))}</p>"
        f"<small>{escape(d['timestamp'][:16].replace('T', ' '))} UTC · {escape(str(d.get('model')))}</small></section>"
        f"<section><h2>Reasoning</h2><pre id=reasoning>{escape(dec.get('reasoning', ''))}</pre></section>"
        + (
            f"<section><h2>Model chain of thought</h2><pre>{escape(d['model_reasoning'])}</pre></section>"
            if d.get("model_reasoning")
            else ""
        )
        + f"<section><h2>Signal</h2><pre>{escape(json.dumps(d.get('signal'), indent=2))}</pre></section>"
        f"<section><h2>Portfolio at the time</h2><pre>{escape(json.dumps(d.get('portfolio_snapshot'), indent=2))}</pre></section>"
    )
    return page(body, f"{d['symbol']} decision")


def make_handler(client_factory, allowed_hosts: set[str], refresh_hosts=None):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes = b"", location: str | None = None):
            self.send_response(status)
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            # Blocks DNS-rebinding / cross-site form posts against the localhost server.
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            origin = urlparse(self.headers.get("Origin") or "").hostname
            if refresh_hosts and host not in allowed_hosts:
                refresh_hosts()
            return host in allowed_hosts and (origin is None or origin in allowed_hosts)

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b"forbidden")
            url = urlparse(self.path)
            path = url.path
            if path == "/":
                saved = parse_qs(url.query).get("saved", [""])[0]
                return self._send(200, index_page(client_factory, saved))
            if path.startswith("/decision/") and path[10:].isdigit():
                body = decision_page(int(path[10:]))
                return self._send(200, body) if body else self._send(404, b"not found")
            self._send(404, b"not found")

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, b"forbidden")
            length = min(int(self.headers.get("Content-Length") or 0), 10_000)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
            path = urlparse(self.path).path
            try:
                if path == "/alerts/test":
                    alerts.notify("test", "Test alert from the dashboard")
                    saved = "alert"
                elif path == "/settings":
                    alerts.save_settings(**{k: form[k] for k in alerts.DEFAULTS if k in form})
                    saved = "limits"
                elif path == "/keys":
                    save_alpaca_keys(form.get("api_key", ""), form.get("secret_key", ""))
                    saved = "keys"
                else:
                    return self._send(404, b"not found")
            except (ValueError, KeyError) as e:
                body = f"<section><p class=err>{escape(str(e))}</p><a href='/#settings'>Back</a></section>"
                return self._send(400, page(body, "Couldn't save"))
            self._send(303, location=f"/?saved={saved}")

        def log_message(self, *args):  # quiet
            pass

    return Handler


def serve(port: int = PORT, client_factory=None) -> None:
    if client_factory is None:
        from portfolio import _client as client_factory
    allowed = {"127.0.0.1", "localhost"}
    last_refresh = 0.0

    def refresh() -> None:
        # Tailscale may come up after this service does (login), so re-ask on an unknown host.
        nonlocal last_refresh
        if time.time() - last_refresh > 30:
            last_refresh = time.time()
            allowed.update(tailscale_names())

    refresh()
    server = ThreadingHTTPServer(
        ("127.0.0.1", port), make_handler(client_factory, allowed, refresh)
    )
    print(f"Dashboard: http://127.0.0.1:{port}/  (allowed hosts: {sorted(allowed)})")
    server.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=PORT)
    serve(ap.parse_args().port)
