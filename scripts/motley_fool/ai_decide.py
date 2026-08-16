"""
Local-LLM decision layer for the Motley Fool -> Alpaca pipeline.

Sends a new pick (or a Sell signal on a current holding), plus the current
portfolio, to a local Qwen model served by LM Studio's OpenAI-compatible API.
The model returns a confidence score (0-100) and reasoning. Every call --
input, full reasoning, and final decision -- is appended to an append-only
JSONL trade-history log so past AI judgments can be reviewed later.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
MODEL = "qwen/qwen3.5-9b"

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
    return json.dumps({"new_signal": pick, "current_portfolio": portfolio_context}, indent=2, default=str)


def _call_qwen(system_prompt: str, user_prompt: str) -> dict:
    response = requests.post(
        LM_STUDIO_URL,
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    message = data["choices"][0]["message"]
    return {
        "content": message.get("content", ""),
        "reasoning": message.get("reasoning_content", ""),
    }


def _parse_decision(raw_content: str) -> dict:
    match = re.search(r"\{.*\}", raw_content, re.DOTALL)
    if not match:
        raise ValueError(f"Could not find JSON in model output: {raw_content!r}")
    parsed = json.loads(match.group(0))
    if "action" not in parsed:
        raise ValueError(f"Model output missing 'action': {parsed}")
    return parsed


def _log_decision(pick: dict, portfolio_context: dict, model_output: dict, decision: dict) -> None:
    DECISIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": pick.get("symbol"),
        "signal": pick,
        "portfolio_snapshot": portfolio_context,
        "model": MODEL,
        "model_reasoning": model_output["reasoning"],
        "decision": decision,
    }
    with open(DECISIONS_LOG, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def decide(pick: dict, portfolio_context: dict) -> dict:
    """
    Ask the local model to evaluate a pick/signal. Returns the parsed decision
    dict ({"confidence", "action", "reasoning"}) and logs the full exchange
    (including the model's raw chain of thought) to decisions.jsonl regardless
    of outcome, so every judgment call is auditable later.
    """
    user_prompt = _build_user_prompt(pick, portfolio_context)
    model_output = _call_qwen(SYSTEM_PROMPT, user_prompt)

    try:
        decision = _parse_decision(model_output["content"])
    except (ValueError, json.JSONDecodeError) as e:
        decision = {"confidence": 0, "action": "ignore", "reasoning": f"PARSE_ERROR: {e}"}

    _log_decision(pick, portfolio_context, model_output, decision)
    return decision


def load_decision_history(symbol: Optional[str] = None, limit: int = 50) -> list[dict]:
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
