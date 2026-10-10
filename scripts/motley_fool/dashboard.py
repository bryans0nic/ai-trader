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
from datetime import datetime, timedelta
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import ai_decide
import alerts
import metrics
from dotenv import load_dotenv, set_key
from portfolio import manual_sell
from state import load_state

PORT = 8765
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
ICON_PATH = Path(__file__).resolve().parent / "icon.png"
SYMBOL_RE = re.compile(r"[A-Z][A-Z.]{0,9}")
PIPELINE_LABEL = "com.aitrader.pipeline"
PIPELINE_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{PIPELINE_LABEL}.plist"
PIPELINE_INTERVAL_S = 1800  # matches install-mac.sh
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
    return f"{'-' if v < 0 else ''}${abs(v):,.2f}"


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


def _time(iso: str | None) -> str:
    """UTC timestamp the page script rewrites into local / "2h ago" form."""
    if not iso:
        return ""
    return f"<time datetime='{escape(iso)}'>{escape(iso[:16].replace('T', ' '))} UTC</time>"


def start_pipeline_run() -> None:
    """Ask launchd to run the scheduled pipeline job now (no-op if one is already running)."""
    r = subprocess.run(
        ["launchctl", "kickstart", f"gui/{os.getuid()}/{PIPELINE_LABEL}"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise ValueError(
            "The trading schedule isn't installed on this Mac. Run install-mac.sh --pipeline first."
        )


def _status_html() -> str:
    run, settings = alerts.read_run_status(), alerts.get_settings()
    scheduled = PIPELINE_PLIST.exists()
    if settings["trading_paused"]:
        trading = "<b class=neg>⏸ Paused</b>: no new buys"
    elif scheduled:
        trading = "<b class=pos>● On</b>"
    else:
        trading = "<b>○ Not scheduled</b>"
    if not run:
        last = "Never run on this Mac"
    else:
        mark = "<b class=pos>✓ OK</b>" if run["ok"] else "<b class=neg>✕ Failed</b>"
        last = f"{mark} {_time(run.get('finished') or run['started'])}<small>{escape(run.get('summary', ''))}</small>"
    nxt = ""
    if run and scheduled:
        due = datetime.fromisoformat(run["started"]) + timedelta(seconds=PIPELINE_INTERVAL_S)
        nxt = f"<div><span class=label>Next run</span>{_time(due.isoformat())}</div>"
    login = {True: "<b class=pos>✓ OK</b>", False: "<b class=neg>✕ Needs login</b>"}.get(
        (run or {}).get("session_ok"), "Not checked yet"
    )
    return (
        "<section id=status class=status>"
        f"<div><span class=label>Trading</span>{trading}</div>"
        f"<div><span class=label>Last run</span>{last}</div>{nxt}"
        f"<div><span class=label>Motley Fool login</span>{login}</div></section>"
    )


def _unread_html() -> str:
    unread = alerts.unread_alerts()
    if not unread:
        return ""
    latest = unread[0]
    more = f" (+{len(unread) - 1} more)" if len(unread) > 1 else ""
    return (
        "<div class=banner role=alert><div><b>⚠ "
        f"{escape(latest['kind'].replace('_', ' '))}</b>{more}<p>{escape(latest['message'])}</p></div>"
        "<form method=post action=/alerts/read><button class=quiet>Mark as read</button></form></div>"
    )


def _buy_decisions(decisions: list[dict]) -> dict[str, dict]:
    """Latest buy decision per symbol (decisions are newest first)."""
    out: dict[str, dict] = {}
    for d in decisions:
        if d["decision"]["action"] == "buy":
            out.setdefault(d["symbol"], d)
    return out


def _position_html(p: dict, settings: dict, pick: dict, bought: dict | None) -> str:
    sym, limit = escape(p["symbol"]), settings["stop_loss_pct"]
    exempt = p["symbol"] in settings["stop_loss_exempt"]
    if exempt:
        stop = "Exempt from the stop-loss"
    else:
        room = p["unrealized_plpc"] + limit
        stop = (
            f"{room:.1f} points above the −{limit:g}% stop-loss"
            if room > 0
            else f"Past the −{limit:g}% stop-loss; sells on the next run"
        )
    facts = [
        ("Avg entry", _usd(p["avg_entry_price"]) if p["avg_entry_price"] else "n/a"),
        ("Stop-loss", stop),
    ]
    if pick.get("confidence") is not None:
        facts.insert(1, ("Claude's confidence", f"{pick['confidence']:g}"))
    if bought:
        facts.insert(1, ("Bought", _time(bought["timestamp"])))
    rows = "".join(f"<div><span class=label>{k}</span>{v}</div>" for k, v in facts)
    link = (
        f"<a href='/decision/{bought['id']}'>See the decision that bought it ›</a>"
        if bought
        else ""
    )
    return (
        f"<li><details><summary><div><b>{sym}</b><small>{p['qty']:g} sh · {_usd(p['market_value'])}"
        f"{' · exempt' if exempt else ''}</small></div>"
        f"<div class=num>{_signed(p['unrealized_pl'], _usd(p['unrealized_pl']))}"
        f"<small>{_signed(p['unrealized_pl'], _pct(p['unrealized_plpc']))}</small></div></summary>"
        f"<div class=facts>{rows}</div>{link}<div class=actions>"
        f"<form method=post action=/positions/exempt><input type=hidden name=symbol value='{sym}'>"
        f"<input type=hidden name=exempt value='{0 if exempt else 1}'>"
        f"<button class=quiet>{'Remove stop-loss exemption' if exempt else 'Exempt from stop-loss'}</button></form>"
        f"<a class='btn danger' href='/sell?symbol={sym}'>Sell now…</a></div></details></li>"
    )


def _orders_html(client) -> str:
    try:
        orders = metrics.recent_orders(client)
    except Exception as e:
        return f"<p class=err>Orders unavailable: {escape(str(e))}</p>"
    rows = "".join(
        f"<li><div><b>{escape(o['symbol'])}</b> <span class='badge {escape(o['side'])}'>{escape(o['side'])}</span>"
        f"<small>{_time(o['submitted_at'])} · "
        + (f"{o['qty']:g} sh" if o["qty"] else _usd(o["notional"] or 0))
        + (f" · filled at {_usd(o['filled_avg_price'])}" if o["filled_avg_price"] else "")
        + f"</small></div><div class=num>{escape(o['status'])}</div></li>"
        for o in orders
    )
    return f"<ul class=list>{rows}</ul>" if rows else _empty("No orders yet.")


def _account_html(client_factory, decisions: list[dict]) -> str:
    try:
        client = client_factory()
        s = metrics.account_snapshot(client)
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
    settings, picks, bought = (
        alerts.get_settings(),
        load_state()["picks"],
        _buy_decisions(decisions),
    )
    rows = "".join(
        _position_html(p, settings, picks.get(p["symbol"], {}), bought.get(p["symbol"]))
        for p in s["positions"]
    )
    return (
        f"<div class=tiles>{tiles}</div><h3>Positions</h3>"
        + (f"<ul class=list>{rows}</ul>" if rows else _empty("No open positions."))
        + "<h3>Orders</h3>"
        + _orders_html(client)
    )


def _chart_html(client_factory, range_key: str) -> str:
    """Account vs S&P 500, both as % change since the start of the range (one shared axis)."""
    tabs = "".join(
        f"<a href='/?range={k}#performance'{' aria-current=true' if k == range_key else ''}>{k.upper()}</a>"
        for k in metrics.RANGES
    )
    head = f"<div class=chart-head><h3>Account vs S&amp;P 500</h3><div class=seg>{tabs}</div></div>"
    try:
        rows = metrics.equity_vs_sp500(client_factory(), range_key)
    except (Exception, SystemExit) as e:
        return head + f"<p class=err>Chart unavailable: {escape(str(e))}</p>"
    if len(rows) < 2:
        return head + _empty("Not enough account history for a chart yet.")

    w, h, left, right, top, bottom = 340, 190, 34, 56, 10, 22
    series = {"portfolio": [r["portfolio"] for r in rows], "sp500": [r["sp500"] for r in rows]}
    values = [v for vs in series.values() for v in vs if v is not None] + [0.0]
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.1 or 1.0
    lo, hi = lo - pad, hi + pad

    def x(i: int) -> float:
        return left + i * (w - left - right) / (len(rows) - 1)

    def y(v: float) -> float:
        return top + (hi - v) * (h - top - bottom) / (hi - lo)

    grid = "".join(
        f"<line class=grid x1={left} x2={w - right} y1={y(v):.1f} y2={y(v):.1f} />"
        f"<text class=axis x={left - 5} y={y(v) + 3:.1f} text-anchor=end>{v:+.1f}%</text>"
        for v in (lo + pad, 0.0, hi - pad)
        if lo <= v <= hi
    )
    marks, ends = "", []
    for name, vals in series.items():
        pts = [(x(i), y(v)) for i, v in enumerate(vals) if v is not None]
        if len(pts) < 2:
            continue
        path = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        marks += f"<polyline class='line s-{name}' points='{path}' />"
        marks += f"<circle class='dot s-{name}' cx={pts[-1][0]:.1f} cy={pts[-1][1]:.1f} r=4 />"
        ends.append([pts[-1][1], next(v for v in reversed(vals) if v is not None)])
    if len(ends) == 2 and abs(ends[0][0] - ends[1][0]) < 12:  # keep the two end labels apart
        upper, lower = sorted(ends, key=lambda e: e[0])
        mid = (upper[0] + lower[0]) / 2
        upper[0], lower[0] = mid - 6, mid + 6
    labels = "".join(
        f"<text class=end x={w - right + 8} y={ey + 4:.1f}>{v:+.1f}%</text>" for ey, v in ends
    )
    data = escape(json.dumps([[r["day"], r["portfolio"], r["sp500"], r["equity"]] for r in rows]))
    table = "".join(
        f"<tr><td>{r['day']}<td>{_usd(r['equity'])}<td>{_pct(r['portfolio'])}<td>{_pct(r['sp500'])}</tr>"
        for r in reversed(rows)
    )
    return (
        head + "<div class=legend><span><i class=s-portfolio></i>This account</span>"
        "<span><i class=s-sp500></i>S&amp;P 500</span></div>"
        f"<div class=chart data-rows='{data}' data-left={left} data-right={right} data-w={w}>"
        f"<svg viewBox='0 0 {w} {h}' role=img aria-label='Account and S&amp;P 500 percent change since "
        f"{rows[0]['day']}'>{grid}{marks}{labels}"
        f"<text class=axis x={left} y={h - 6}>{rows[0]['day']}</text>"
        f"<text class=axis x={w - right} y={h - 6} text-anchor=end>{rows[-1]['day']}</text>"
        f"<line class=cross y1={top} y2={h - bottom} hidden /></svg><div class=tip hidden></div></div>"
        "<details class=tbl><summary>Show as table</summary><table><tr><th>Day<th>Equity<th>Account<th>S&amp;P 500</tr>"
        f"{table}</table></details>"
    )


def _performance_html(client_factory, decisions: list[dict], range_key: str) -> str:
    chart = _chart_html(client_factory, range_key)
    try:
        b = metrics.benchmarks(decisions)
        ignored = metrics.ignored_performance(decisions)
    except Exception as e:
        return chart + f"<p class=err>Performance unavailable: {escape(str(e))}</p>"
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
        chart
        + f"<h3>Picks</h3><p class=hint>Average return since each pick's date.</p><div class=tiles>{tiles}</div>"
        "<h3>Ignored picks since the decision</h3>"
        + (f"<ul class=list>{ig}</ul>" if ig else _empty("No ignored picks yet."))
    )


def _alerts_html() -> str:
    unread = {a["timestamp"] for a in alerts.unread_alerts()}
    rows = "".join(
        f"<li><div><b>{'● ' if a['timestamp'] in unread else ''}{escape(a['kind'].replace('_', ' '))}</b>"
        f"<small>{_time(a['timestamp'])}</small><p>{escape(a['message'])}</p></div></li>"
        for a in alerts.load_alerts()
    )
    read = (
        "<form method=post action=/alerts/read><button>Mark all as read</button></form>"
        if unread
        else ""
    )
    return (
        (f"<ul class=list id=alerts>{rows}</ul>" if rows else _empty("No alerts."))
        + read
        + "<form method=post action=/alerts/test><button class=quiet>Send test alert</button></form>"
    )


def _settings_html() -> str:
    s = alerts.get_settings()
    k = keys_status()
    if k["key_tail"] and k["has_secret"]:
        status = f"Keys saved (key ID ends in {escape(k['key_tail'])}). Enter both again to replace them."
    else:
        status = "No keys saved yet."
    paused = s["trading_paused"]
    return (
        "<h3>Trading</h3>"
        f"<p class=hint>{'Paused: new picks are not checked or bought. Stop-losses still run.' if paused else 'On: new picks are checked every 30 minutes.'}</p>"
        f"<form method=post action=/pause><input type=hidden name=paused value='{0 if paused else 1}'>"
        f"<button class='{'' if paused else 'quiet'}'>{'Resume trading' if paused else 'Pause trading'}</button></form>"
        "<form method=post action=/run><button class=quiet>Run the pipeline now</button></form>"
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


def _outcome(d: dict) -> str:
    """What happened after a decision: return since a buy, or what an ignored pick would have made."""
    action = d["decision"]["action"]
    if action not in ("buy", "ignore") or not d.get("symbol"):
        return ""
    change = metrics.pct_change_since(d["symbol"], d["timestamp"][:10])
    if change is None:
        return ""
    lead = "Since buy" if action == "buy" else "Would be"
    return f"<div class=num><small>{lead}</small>{_signed(change, _pct(change))}</div>"


def _decisions_html(decisions: list[dict], action: str, q: str) -> str:
    chips = "".join(
        f"<a href='/?{urlencode({'action': a, 'q': q})}#decisions'{' aria-current=true' if a == action else ''}>{label}</a>"
        for a, label in (("", "All"), ("buy", "Buy"), ("ignore", "Ignore"), ("exit", "Exit"))
    )
    search = (
        "<form class=search method=get action='/#decisions'>"
        f"<input type=hidden name=action value='{escape(action)}'>"
        f"<input name=q type=search placeholder='Search symbol' aria-label='Search symbol' value='{escape(q)}' "
        "autocapitalize=characters autocorrect=off><button class=quiet>Search</button></form>"
    )
    shown = [
        d
        for d in decisions
        if (not action or d["decision"]["action"] == action)
        and (not q or q.upper() in (d["symbol"] or "").upper())
    ]
    rows = "".join(
        f"<li><a class=row href='/decision/{d['id']}'><div><b>{escape(d['symbol'] or '?')}</b> "
        f"<span class='badge {escape(d['decision']['action'])}'>{escape(d['decision']['action'])}</span>"
        f"<small>{_time(d['timestamp'])} · confidence {escape(str(d['decision'].get('confidence', '')))}</small>"
        f"<p>{escape(d['decision'].get('reasoning', '')[:140])}</p></div>{_outcome(d)}<div class=chev>›</div></a></li>"
        for d in shown
    )
    count = f"<p class=hint>{len(shown)} of {len(decisions)} decisions</p>" if action or q else ""
    empty = "No decisions match." if decisions else "No decisions logged yet."
    return f"<div class=seg>{chips}</div>{search}{count}" + (
        f"<ul class=list>{rows}</ul>" if rows else _empty(empty)
    )


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
.status{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.status .label{display:block}
.banner{display:flex;gap:12px;align-items:center;justify-content:space-between;border:2px solid var(--neg);border-radius:14px;padding:12px;margin:12px 0;background:var(--card)}
.banner p{margin:4px 0 0;font-size:14px;overflow-wrap:anywhere}.banner form{flex:none}.banner button{width:auto;padding:0 14px;margin:0}
details>summary{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0;min-height:44px;cursor:pointer;list-style:none}
details>summary::-webkit-details-marker{display:none}.list li>details{width:100%}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;padding:4px 0 10px;font-size:15px}.facts .label{display:block}
.actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:10px 0;align-items:end}.actions button{margin:0}
.btn{display:flex;align-items:center;justify-content:center;min-height:48px;border-radius:10px;border:1px solid var(--line);text-decoration:none;font-weight:600}
.danger{color:var(--neg);border-color:var(--neg)}button.danger{background:var(--neg);color:var(--card)}
.seg{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}.seg a{padding:8px 14px;min-height:40px;border:1px solid var(--line);border-radius:20px;text-decoration:none;color:var(--ink);font-size:14px}
.seg a[aria-current]{background:var(--ink);color:var(--card);border-color:var(--ink)}
.search{display:flex;gap:8px;align-items:center}.search input{margin:0}.search button{width:auto;margin:0;padding:0 16px}
.chart-head{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}.chart-head h3{margin:6px 0}
.legend{display:flex;gap:16px;font-size:13px;color:var(--mute);margin:4px 0}.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
:root{--s1:#2a78d6;--s2:#eb6834}@media(prefers-color-scheme:dark){:root{--s1:#3987e5;--s2:#d95926}}
i.s-portfolio{background:var(--s1)}i.s-sp500{background:var(--s2)}
.chart{position:relative;touch-action:pan-y}.chart svg{display:block;width:100%;height:auto}
.line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}.line.s-portfolio{stroke:var(--s1)}.line.s-sp500{stroke:var(--s2)}
.dot{stroke:var(--card);stroke-width:2}.dot.s-portfolio{fill:var(--s1)}.dot.s-sp500{fill:var(--s2)}
.grid{stroke:var(--line);stroke-width:1}.cross{stroke:var(--mute);stroke-width:1}
.axis{fill:var(--mute);font-size:9px}.end{fill:var(--ink);font-size:10px;font-weight:600}
.tip{position:absolute;top:0;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 8px;font-size:12px;white-space:nowrap;box-shadow:0 2px 8px #0003}
.tbl table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}.tbl td,.tbl th{text-align:left;padding:4px 6px;border-top:1px solid var(--line)}
nav a b{color:var(--neg)}
</style>"""

SCRIPT = """<script>
for (const t of document.querySelectorAll("time")) {
  const d = new Date(t.dateTime), mins = Math.round((d - Date.now()) / 60000), a = Math.abs(mins);
  if (isNaN(d)) continue;
  const rel = new Intl.RelativeTimeFormat("en", {numeric: "auto"});
  t.title = d.toLocaleString();
  t.textContent = a < 60 ? rel.format(mins, "minute") : a < 1440 ? rel.format(Math.round(mins / 60), "hour")
    : d.toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
}
for (const c of document.querySelectorAll(".chart")) {
  const rows = JSON.parse(c.dataset.rows), L = +c.dataset.left, R = +c.dataset.right, W = +c.dataset.w;
  const cross = c.querySelector(".cross"), tip = c.querySelector(".tip"), f = v => v == null ? "n/a" : (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  const move = e => {
    const box = c.getBoundingClientRect(), vx = (e.clientX - box.left) * W / box.width;
    const i = Math.max(0, Math.min(rows.length - 1, Math.round((vx - L) / (W - L - R) * (rows.length - 1))));
    const x = L + i * (W - L - R) / (rows.length - 1), r = rows[i];
    cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.removeAttribute("hidden");
    tip.innerHTML = "<b></b><br>This account <span></span><br>S&amp;P 500 <span></span>";
    tip.querySelector("b").textContent = r[0];
    const s = tip.querySelectorAll("span"); s[0].textContent = f(r[1]); s[1].textContent = f(r[2]);
    tip.hidden = false;
    const px = x * box.width / W;
    tip.style.left = Math.min(px + 8, box.width - tip.offsetWidth - 4) + "px";
  };
  c.addEventListener("pointermove", move); c.addEventListener("pointerdown", move);
  c.addEventListener("pointerleave", () => { cross.setAttribute("hidden", ""); tip.hidden = true; });
}
</script>"""

FLASH = {
    "keys": "Alpaca keys saved.",
    "limits": "Risk limits saved.",
    "alert": "Test alert sent.",
    "read": "Alerts marked as read.",
    "paused": "Trading paused. Stop-losses still run.",
    "resumed": "Trading resumed.",
    "run": "Pipeline run started. Refresh in a minute to see the result.",
    "sold": "Sell order placed.",
    "exempt": "Stop-loss exemption updated.",
}


def page(body: str, title: str = "Trader dashboard") -> bytes:
    return (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1,viewport-fit=cover'>"
        "<link rel=apple-touch-icon href=/apple-touch-icon.png><link rel=icon type=image/png href=/apple-touch-icon.png>"
        "<meta name=apple-mobile-web-app-title content=Trader><meta name=theme-color content=#0f1115>"
        f"<title>{escape(title)}</title>{STYLE}<main><header><h1>{escape(title)}</h1></header>{body}</main>{SCRIPT}</html>"
    ).encode()


def index_page(client_factory, params: dict | None = None) -> bytes:
    params = params or {}
    range_key = params.get("range") if params.get("range") in metrics.RANGES else "1m"
    action = params.get("action") if params.get("action") in ("buy", "ignore", "exit") else ""
    q = (params.get("q") or "")[:12]
    saved = params.get("saved", "")
    decisions = all_decisions()
    flash = f"<p class=flash role=status>{FLASH[saved]}</p>" if saved in FLASH else ""
    unread = len(alerts.unread_alerts())
    sections = [
        ("account", "Account", _account_html(client_factory, decisions)),
        ("performance", "Performance", _performance_html(client_factory, decisions, range_key)),
        ("alerts-section", "Alerts", _alerts_html()),
        ("decisions", "Decisions", _decisions_html(decisions, action, q)),
        ("settings", "Settings", _settings_html()),
    ]
    nav = (
        "<nav>"
        + "".join(
            f"<a href='#{i}'>{t}{f' <b>({unread})</b>' if i == 'alerts-section' and unread else ''}</a>"
            for i, t, _ in sections
        )
        + "</nav>"
    )
    return page(
        nav
        + flash
        + _unread_html()
        + _status_html()
        + "".join(f"<section id={i}><h2>{t}</h2>{html}</section>" for i, t, html in sections)
    )


def sell_confirm_page(client_factory, symbol: str) -> bytes | None:
    """Confirmation step before a manual sell; None if the symbol isn't held."""
    pos = next(
        (
            p
            for p in metrics.account_snapshot(client_factory())["positions"]
            if p["symbol"] == symbol
        ),
        None,
    )
    if pos is None:
        return None
    sym = escape(symbol)
    body = (
        f"<section><p>Sell all <b>{pos['qty']:g} shares of {sym}</b> (about {_usd(pos['market_value'])}, "
        f"{_pct(pos['unrealized_plpc'])}) at market price?</p>"
        "<p class=hint>If the market is closed the order waits for the next open.</p>"
        f"<form method=post action=/positions/sell><input type=hidden name=symbol value='{sym}'>"
        f"<button class=danger>Yes, sell {sym}</button></form>"
        "<a class=btn href='/#account'>Cancel</a></section>"
    )
    return page(body, f"Sell {symbol}?")


def decision_page(decision_id: int) -> bytes | None:
    d = next((d for d in all_decisions() if d["id"] == decision_id), None)
    if d is None:
        return None
    dec = d["decision"]
    action = escape(dec["action"])
    body = (
        "<nav><a href='/#decisions'>‹ All decisions</a></nav>"
        f"<section><p><span class='badge {action}'>{action}</span> confidence {escape(str(dec.get('confidence', '')))}</p>"
        f"<small>{_time(d['timestamp'])} · {escape(str(d.get('model')))}</small></section>"
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
        def _send(
            self,
            status: int,
            body: bytes = b"",
            location: str | None = None,
            ctype: str = "text/html; charset=utf-8",
        ):
            self.send_response(status)
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Type", ctype)
            self.send_header(
                "Cache-Control", "max-age=86400" if ctype == "image/png" else "no-store"
            )
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
            params = {k: v[0] for k, v in parse_qs(url.query).items()}
            if path == "/":
                return self._send(200, index_page(client_factory, params))
            if path in (
                "/apple-touch-icon.png",
                "/apple-touch-icon-precomposed.png",
                "/favicon.ico",
            ):
                return self._send(200, ICON_PATH.read_bytes(), ctype="image/png")
            if path == "/sell" and SYMBOL_RE.fullmatch(params.get("symbol", "")):
                body = sell_confirm_page(client_factory, params["symbol"])
                return self._send(200, body) if body else self._send(404, b"not found")
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
            anchor = ""
            try:
                if path == "/alerts/test":
                    alerts.notify("test", "Test alert from the dashboard")
                    saved = "alert"
                elif path == "/alerts/read":
                    alerts.mark_alerts_read()
                    saved = "read"
                elif path == "/settings":
                    alerts.save_settings(**{k: form[k] for k in alerts.LIMITS if k in form})
                    saved = "limits"
                elif path == "/keys":
                    save_alpaca_keys(form.get("api_key", ""), form.get("secret_key", ""))
                    saved = "keys"
                elif path == "/pause":
                    paused = form.get("paused") == "1"
                    alerts.save_settings(trading_paused=paused)
                    saved = "paused" if paused else "resumed"
                elif path == "/run":
                    start_pipeline_run()
                    saved = "run"
                elif path in ("/positions/sell", "/positions/exempt"):
                    symbol = form.get("symbol", "")
                    if not SYMBOL_RE.fullmatch(symbol):
                        raise ValueError("That doesn't look like a stock symbol.")
                    if path == "/positions/sell":
                        manual_sell(client_factory(), symbol)
                        saved = "sold"
                    else:
                        alerts.set_stop_loss_exempt(symbol, form.get("exempt") == "1")
                        saved = "exempt"
                    anchor = "#account"
                else:
                    return self._send(404, b"not found")
            except (ValueError, KeyError) as e:
                body = f"<section><p class=err>{escape(str(e))}</p><a href='/'>Back</a></section>"
                return self._send(400, page(body, "Couldn't do that"))
            self._send(303, location=f"/?saved={saved}{anchor}")

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
