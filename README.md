# AI-Trader

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-GPL--3.0-green)](LICENSE)

[中文版說明 (Chinese Subpage)](README_zh.md)

A professional, config-driven backtesting framework for algorithmic trading, built on Backtrader. Seamlessly test, optimize, and integrate trading strategies with Large Language Models (LLMs) across stocks, crypto, and forex markets.

![Demo GIF](data/demo.gif)

## Key Features

- **Config-Driven Workflows**: Define and manage backtests with version-controllable YAML files for reproducible results.
- **Seamless LLM Integration**: Built-in MCP (Model Context Protocol) server allows AI assistants like Claude to run backtests, fetch data, and analyze strategies.
- **Multi-Market Support**: Test strategies on US stocks, Taiwan stocks, cryptocurrencies, and forex.
- **Extensive Strategy Library**: Comes with over 20 built-in strategies, from classic indicators to advanced adaptive models.
- **Powerful CLI**: A rich command-line interface to run backtests, fetch market data, and list strategies.
- **Developer Friendly**: Easily create and test custom strategies with simple helpers and a clear structure.

## Quick Start

**1. Installation**

**Option A: Install from PyPI (Recommended for using the CLI)**
```bash
pip install ai-trader
```
Use this if you want to:
- Use the CLI commands: `ai-trader run`, `ai-trader fetch`, `ai-trader quick`
- Run backtests on your own data files
- Use as a library in your Python projects

**Option B: Install from Source (Recommended for examples and config templates)**
```bash
git clone https://github.com/whchien/ai-trader.git
cd ai-trader

# Install dependencies (choose one method)
uv sync        # Recommended (fastest, modern tool)
# poetry install   # Or use Poetry
# pip install -e .  # Or traditional pip with editable install
```
Use this if you want to:
- Run the config-based examples in `config/backtest/`
- Use the example data files in `data/`
- Run the example scripts in `scripts/examples/`
- Contribute or customize strategies

**2. Run a Backtest via CLI**

**If you cloned from source**, run a predefined backtest using a configuration file:
```bash
# Run a backtest from a config file (requires source installation)
ai-trader run config/backtest/classic/sma_example.yaml
```

Or, run a quick backtest on any data file (works with both pip and source installation):
```bash
# Quick backtest on your own data file
ai-trader quick CrossSMAStrategy your_data.csv --cash 100000
```

**3. Fetch Market Data**

Download historical data for any supported market:
```bash
# US Stock (default: saves to CSV)
ai-trader fetch TSM --market us_stock --start-date 2020-01-01

# Taiwan Stock (台灣股票)
ai-trader fetch 2330 --market tw_stock --start-date 2020-01-01

# Cryptocurrency
ai-trader fetch BTC-USD --market crypto --start-date 2020-01-01

# With SQLite persistent caching (NEW!)
ai-trader fetch AAPL --market us_stock --start-date 2024-01-01 --storage sqlite

# Save to both CSV and SQLite
ai-trader fetch AAPL --market us_stock --start-date 2024-01-01 --storage both
```

**Persistent Data Storage with SQLite**

By default, `ai-trader fetch` saves data to CSV. For faster repeated backtests, use SQLite:

```bash
# First fetch: Downloads from API and caches in SQLite (~2-3 seconds)
ai-trader fetch AAPL --market us_stock --start-date 2024-01-01 --storage sqlite

# Repeated fetch: Loads from cache (~50ms, no API call)
ai-trader fetch AAPL --market us_stock --start-date 2024-01-01 --storage sqlite

# Check cached data
ai-trader data list
ai-trader data info

# Clean old data
ai-trader data clean --market us_stock --before 2020-01-01
```

[**Learn more about SQLite Storage →**](agentic_ai_trader/trading-backtester/README.md#persistent-data-storage-with-sqlite)

## Core Workflows

### 1. Configuration-Based Backtesting

The most robust way to run backtests is with a YAML config file.

**`my_backtest.yaml`:**
```yaml
broker:
  cash: 1000000
  commission: 0.001425

data:
  file: "data/us_stock/TSM.csv"
  start_date: "2020-01-01"
  end_date: "2023-12-31"

strategy:
  class: "CrossSMAStrategy"
  params:
    fast: 10
    slow: 30

sizer:
  type: "percent"
  params:
    percents: 95
```
**Run it:**
```bash
ai-trader run my_backtest.yaml
```
See `config/backtest/` for more examples.

### 2. Python-Based Backtesting

For more granular control or integration into other Python scripts.

**Simple approach:**
```python
from ai_trader import run_backtest
from ai_trader.backtesting.strategies.classic.sma import CrossSMAStrategy

# Run backtest with example data
results = run_backtest(
    strategy=CrossSMAStrategy,
    data_source=None,  # Uses built-in example data
    cash=1000000,
    strategy_params={"fast": 10, "slow": 30}
)
```

**Step-by-step control:**
See `scripts/examples/02_step_by_step.py` for a detailed example.

### 3. LLM Integration (MCP Server)

Run `ai-trader` as a server to let AI assistants interact with your backtesting engine.

**Start the Server (for testing):**
```bash
python -m ai_trader.mcp
```

**Configure with Claude Desktop (Recommended):**

1. Locate your Claude Desktop configuration file:
   - **macOS/Linux**: `~/.config/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

2. Add the `ai-trader` MCP server to the `mcpServers` section:

```json
{
  "mcpServers": {
    "ai-trader": {
      "command": "python3",
      "args": ["-m", "ai_trader.mcp"],
      "cwd": "/path/to/ai-trader"
    }
  }
}
```

**Configuration Notes:**
- Replace `/path/to/ai-trader` with your actual ai-trader project directory
- If using a virtual environment, use the full path to the Python executable: `/path/to/.venv/bin/python3`
- Restart Claude Desktop after updating the config file

Once configured, you can use Claude to interact with your backtesting engine with natural language commands like:
- *"Run a backtest of the CrossSMAStrategy on TSM data from 2020-2022."*
- *"List all available trading strategies."*
- *"Fetch Apple stock data from 2021 to 2024."*

## Creating Custom Strategies

### Option 1: Using Claude Code Skills (Recommended)

The fastest way to create a new strategy is with the `/add-strategy` skill in Claude Code. The skill guides you through the process interactively:

```bash
/add-strategy classic
```

This will prompt you for:
- Strategy name (e.g., "MACDBBands")
- Description
- Parameters with defaults
- Entry and exit conditions
- Any custom indicators

The skill automatically handles:
- File creation with proper naming conventions
- Comprehensive docstrings
- Automatic registration in `__init__.py`
- Syntax validation

Learn more about Claude Code skills: https://code.claude.com/docs/en/skills

### Option 2: Manual Creation

Create a new file in `ai_trader/backtesting/strategies/classic/` and inherit from `BaseStrategy`.

```python
# ai_trader/backtesting/strategies/classic/my_strategy.py
import backtrader as bt
from ai_trader.backtesting.strategies.base import BaseStrategy

class MyCustomStrategy(BaseStrategy):
    params = dict(period=20)

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)

    def next(self):
        if not self.position and self.data.close[0] > self.sma[0]:
            self.buy()
        elif self.position and self.data.close[0] < self.sma[0]:
            self.close()
```

The new strategy is automatically available to the CLI and `run_backtest` function.

## Live Paper Trading (Experimental)

> **Status: paper trading only, no real money.** This is an active experiment being
> validated over a period of months before any live capital is considered. See
> [open issues](https://github.com/bryans0nic/ai-trader/issues) for the hardening
> work still planned before that's on the table.

Two ways to run strategies against a live (paper) brokerage account instead of historical data:

**1. Run any built-in strategy against Alpaca paper trading**

[`scripts/paper_trade_alpaca.py`](scripts/paper_trade_alpaca.py) polls Alpaca for
recent bars, replays them through an unmodified `ai-trader` strategy to get a
long/flat signal, and reconciles that against your Alpaca paper position.

```bash
uv run python scripts/paper_trade_alpaca.py --strategy NaiveSMAStrategy --symbol AAPL
```

Requires paper API keys from [alpaca.markets](https://alpaca.markets) in a local `.env`
(see [`.env.example`](.env.example)).

**2. Autonomous Motley Fool Stock Advisor -> local AI -> Alpaca pipeline**

[`scripts/motley_fool/`](scripts/motley_fool/) scrapes new Motley Fool Stock Advisor
picks (deterministically, via a saved login session -- no credentials stored), sends
each new signal to a locally-hosted LLM (Qwen, served via LM Studio) for a buy/ignore/exit
judgment with reasoning, and executes the resulting trade against Alpaca. Runs on a
schedule (see [`run_scheduled.ps1`](scripts/motley_fool/run_scheduled.ps1)); every
decision, including the model's full reasoning, is logged for later review.

```bash
# One-time: log into Motley Fool and save the session
uv run python scripts/motley_fool/login_and_save_session.py

# Check current portfolio / pending decisions
uv run python scripts/motley_fool/portfolio.py

# Review AI decision history with reasoning
uv run python scripts/motley_fool/view_history.py
```

Portfolio rule: max 10 positions, ranked by AI-assigned confidence; a new pick can
only enter by beating the lowest-confidence current holding. Position size scales
with confidence. No stop-loss or drawdown circuit breaker yet -- see open issues.

## Documentation & Resources

- **[Strategy Examples](ai_trader/backtesting/strategies/README.md)**: Details on built-in strategies.
- **[Example Scripts](scripts/examples/)**: 5 complete working examples for different use cases.
- **[Config Templates](config/backtest/)**: YAML configuration templates.
- **[Migration Guide](docs/MIGRATION_GUIDE.md)**: For upgrading from v0.1.x.

## Contributing

Contributions are welcome! Feel free to report bugs, suggest features, or submit pull requests.

## Show Your Support

If you find this project helpful, please give it a star !

## License

This project is licensed under the GNU General Public License v3 (GPL-3.0). See the [LICENSE](LICENSE) file for details.
 