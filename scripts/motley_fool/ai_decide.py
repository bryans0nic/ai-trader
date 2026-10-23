"""
Claude decision layer for the Motley Fool -> Alpaca pipeline.

Sends a new pick (or a Sell signal on a current holding), plus the current
portfolio, to Claude through the logged-in Claude Code CLI (`claude -p`, on
the subscription login -- same approach as the ClaudeOS repo).
The model returns a confidence score (0-100) and reasoning. Every call --
input, full reasoning, and final decision -- is appended to an append-only
JSONL trade-history log so past AI judgments can be reviewed later.
"""

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
MODEL = os.environ.get(
    "TRADER_CLAUDE_MODEL", "sonnet"
)  # alias; the model actually used is logged per decision
CLAUDE_TIMEOUT_S = 180

ACTIONS = ("buy", "ignore", "exit")

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "action": {"type": "string", "enum": list(ACTIONS)},
        "reasoning": {"type": "string"},
    },
    "required": ["confidence", "action", "reasoning"],
}

DECISIONS_LOG = Path(__file__).resolve().parents[2] / "data" / "motley_fool" / "decisions.jsonl"

SYSTEM_PROMPT = """You are a position-sizing assistant for a Motley Fool -> Alpaca paper-trading \
pipeline. You are given one new Motley Fool Stock Advisor signal (a Buy on a new pick, or a Sell \
on a stock currently held) plus a snapshot of the current auto-managed portfolio (max 10 \
positions, each holding has its own prior confidence score).

Respond with ONLY a single JSON object, no other text:
{
  "confidence": <integer 0-100, how strongly to weight this pick if it's a Buy; irrelevant for Sell>,
  "action": "buy" | "ignore" | "exit",
  "reasoning": "<2-4 sentences explaining the call, referencing specific data given>"
}

Guidance:
- "buy": recommend entering/increasing this position. Give it a confidence score.
- "ignore": the data doesn't justify action (e.g. weak signal, redundant with a much stronger \
existing holding, exceptionally high risk/drawdown estimate for the est. return offered).
- "exit": only for Sell signals on a symbol currently held -- recommend closing it.
- Be skeptical of hype; weigh est. return range against est. max drawdown, market cap, and \
how many times MF has recommended this stock across their history.
- You are not giving investment advice to a person; you are configuring an automated paper- \
trading system for testing. Be decisive."""


def _build_user_prompt(pick: dict, portfolio_context: dict) -> str:
    return json.dumps(
        {"new_signal": pick, "current_portfolio": portfolio_context}, indent=2, default=str
    )


def _call_claude(system_prompt: str, user_prompt: str) -> dict:
    """One headless Claude call, no tools/MCP/settings. Returns {"content", "reasoning", "model"}."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
    }
    for key in (
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_CHILD_SESSION",
        "CLAUDE_CODE_ENTRYPOINT",
    ):
        env.pop(key, None)  # don't look like a child of an enclosing Claude Code session
    args = [
        CLAUDE_BIN,
        "-p",
        "--output-format",
        "json",
        "--no-session-persistence",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--tools",
        "",
        "--model",
        MODEL,
        "--system-prompt",
        system_prompt,
        "--json-schema",
        json.dumps(DECISION_SCHEMA),
    ]
    proc = subprocess.run(
        args, input=user_prompt, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_S, env=env
    )
    try:
        res = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"claude exited {proc.returncode}: {proc.stderr.strip()[-400:]}"
        ) from None
    if res.get("is_error"):
        raise RuntimeError(f"claude error: {res.get('result')}")
    structured = res.get("structured_output")
    return {
        "content": json.dumps(structured) if structured is not None else res.get("result", ""),
        "reasoning": "",  # Claude's reasoning is the decision's own "reasoning" field
        "model": next(iter(res.get("modelUsage") or {}), MODEL),
    }


def _parse_decision(raw_content: str) -> dict:
    match = re.search(r"\{.*\}", raw_content, re.DOTALL)
    if not match:
        raise ValueError(f"Could not find JSON in model output: {raw_content!r}")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict) or parsed.get("action") not in ACTIONS:
        raise ValueError(f"Model output has no valid 'action': {parsed}")
    return parsed


def _price_now(symbol: str | None) -> float | None:
    """Last price, logged with the decision so later returns don't depend on a re-lookup."""
    try:
        from metrics import latest_price

        return latest_price(symbol) if symbol else None
    except Exception:
        return None  # a missing price must never block logging the decision


def _log_decision(pick: dict, portfolio_context: dict, model_output: dict, decision: dict) -> None:
    DECISIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "symbol": pick.get("symbol"),
        "price": _price_now(pick.get("symbol")),
        "signal": pick,
        "portfolio_snapshot": portfolio_context,
        "model": model_output["model"],
        "model_reasoning": model_output["reasoning"],
        "decision": decision,
    }
    with open(DECISIONS_LOG, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def decide(pick: dict, portfolio_context: dict) -> dict:
    """
    Ask Claude to evaluate a pick/signal. Returns the parsed decision
    dict ({"confidence", "action", "reasoning"}) and logs the full exchange
    to decisions.jsonl regardless
    of outcome, so every judgment call is auditable later.
    """
    user_prompt = _build_user_prompt(pick, portfolio_context)
    try:
        model_output = _call_claude(SYSTEM_PROMPT, user_prompt)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        # Claude unreachable / logged out / timed out: never trade on a failed call.
        model_output = {"content": "", "reasoning": "", "model": MODEL}
        decision = {"confidence": 0, "action": "ignore", "reasoning": f"CALL_ERROR: {e}"}
    else:
        try:
            decision = _parse_decision(model_output["content"])
        except (ValueError, json.JSONDecodeError) as e:
            decision = {"confidence": 0, "action": "ignore", "reasoning": f"PARSE_ERROR: {e}"}

    _log_decision(pick, portfolio_context, model_output, decision)
    return decision


def load_decision_history(symbol: str | None = None, limit: int = 50) -> list[dict]:
    """Read back past decisions from the trade-history log, most recent first."""
    if not DECISIONS_LOG.exists():
        return []
    records = []
    with open(DECISIONS_LOG) as f:
        for line in f:
            record = json.loads(line)
            if symbol is None or record.get("symbol") == symbol:
                records.append(record)
    return list(reversed(records))[:limit]
