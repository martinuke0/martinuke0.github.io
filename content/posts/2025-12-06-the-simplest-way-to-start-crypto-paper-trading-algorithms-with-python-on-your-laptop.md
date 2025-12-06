---
title: "The Simplest Way to Start Crypto Paper Trading Algorithms with Python on Your Laptop"
date: "2025-12-06T17:23:32.48"
draft: false
tags: ["python", "crypto", "algorithmic-trading", "paper-trading", "ccxt"]
---

## Introduction

If you want to learn algorithmic crypto trading without risking real money, paper trading is the safest, fastest way to start. In this guide, you'll build a minimal, efficient paper trading loop in Python that runs on your laptop, uses real-time market data, and simulates orders with fees and slippage—no exchange account or API keys required. We’ll use public market data (via CCXT) and a small “paper broker” to track positions, PnL, and trades.

The goal: keep it simple, robust, and extensible. You can be up and running in under an hour.

> Note: This article is educational, not financial advice. Trading involves risk. Paper trading may behave differently from real execution due to slippage, liquidity, market impact, and exchange rules.

## Table of Contents

- What is paper trading (and why do it)?
- Architecture: the simplest reliable setup
- Quick setup: environment and dependencies
- A minimal Python paper trading bot (full code)
- How to run it and what to expect
- Optional: Use exchange testnets (real APIs, fake money)
- Backtesting the same strategy
- Performance and reliability tips
- Common pitfalls and troubleshooting
- Where to go next
- Conclusion

## What is paper trading (and why do it)?

Paper trading is simulated trading with real market data but no real money. It lets you:
- Validate strategy logic without financial risk
- Test order sizing, fees, slippage, and PnL accounting
- Practice deploying and monitoring a bot
- Iterate faster before connecting to an exchange

Paper trading is not a guarantee of live performance, but it’s the safest starting point.

## Architecture: the simplest reliable setup

We’ll implement the minimal moving parts you need:
- Data: Public OHLCV (candles) from an exchange via CCXT (no API keys needed).
- Strategy: A simple moving average crossover on 1-minute candles (fast SMA vs. slow SMA).
- Broker: A local “paper broker” that simulates market orders, fees, and slippage, tracks cash and positions, and logs trades to CSV.
- Runner: A small loop that fetches the latest candle, updates signals, and executes orders.

This keeps dependencies light, avoids fragile websockets, and runs well on any laptop.

## Quick setup: environment and dependencies

Requirements:
- Python 3.10+ (3.11 recommended)
- pip

Install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install ccxt pandas numpy
```

Optional but helpful:
```bash
pip install python-dotenv
```

Create a folder for your bot:
```bash
mkdir crypto-paper-bot && cd crypto-paper-bot
```

## A minimal Python paper trading bot (full code)

Save as file: bot.py

```python
import time
import math
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import ccxt
import pandas as pd
import numpy as np


class PaperBroker:
    """
    Minimal single-symbol paper broker with:
      - Cash (quote currency, e.g., USDT)
      - Position (base currency, e.g., BTC)
      - Market orders with fee and slippage
      - CSV trade log
    """
    def __init__(
        self,
        starting_cash: float = 1000.0,
        fee_rate: float = 0.001,          # 0.10% fee
        slippage_bp: float = 1.0,         # 1 basis point = 0.01%
        log_path: str = "trades.csv",
        quote: str = "USDT",
        base: str = "BTC",
    ):
        self.cash = float(starting_cash)
        self.base_qty = 0.0
        self.fee_rate = float(fee_rate)
        self.slippage = float(slippage_bp) / 10000.0
        self.log_path = log_path
        self.quote = quote
        self.base = base

        # Create CSV header if empty
        try:
            with open(self.log_path, "x") as f:
                f.write("ts,symbol,side,qty,price,fee,cash,base_qty,equity\n")
        except FileExistsError:
            pass

    def _log_trade(self, symbol: str, side: str, qty: float, price: float, fee: float, equity: float):
        ts = datetime.now(timezone.utc).isoformat()
        with open(self.log_path, "a") as f:
            f.write(f"{ts},{symbol},{side},{qty:.8f},{price:.2f},{fee:.6f},{self.cash:.2f},{self.base_qty:.8f},{equity:.2f}\n")

    def portfolio_value(self, last_price: float) -> float:
        return self.cash + self.base_qty * last_price

    def market_order(self, symbol: str, side: str, qty: float, mid_price: float) -> Dict[str, Any]:
        """
        Simulate a market order with slippage and fee.
        Assumes symbol like 'BTC/USDT' (base/quote).
        """
        if qty <= 0:
            return {"status": "rejected", "reason": "non-positive qty"}

        # Slippage: buy worse, sell worse (conservative)
        if side.lower() == "buy":
            exec_price = mid_price * (1 + self.slippage)
        elif side.lower() == "sell":
            exec_price = mid_price * (1 - self.slippage)
        else:
            return {"status": "rejected", "reason": "invalid side"}

        notional = exec_price * qty
        fee = notional * self.fee_rate

        if side.lower() == "buy":
            total_cost = notional + fee
            if self.cash < total_cost:
                return {"status": "rejected", "reason": "insufficient cash"}
            self.cash -= total_cost
            self.base_qty += qty

        else:  # sell
            if self.base_qty < qty:
                return {"status": "rejected", "reason": "insufficient position"}
            self.base_qty -= qty
            self.cash += (notional - fee)

        equity = self.portfolio_value(mid_price)
        self._log_trade(symbol, side, qty, exec_price, fee, equity)

        return {
            "status": "filled",
            "side": side,
            "qty": qty,
            "price": exec_price,
            "fee": fee,
            "cash": self.cash,
            "base_qty": self.base_qty,
            "equity": equity,
        }


def get_exchange(name: str = "binance"):
    name = name.lower()
    if name == "binance":
        return ccxt.binance({"enableRateLimit": True})
    if name == "bybit":
        return ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    if name == "okx":
        return ccxt.okx({"enableRateLimit": True})
    if name == "kraken":
        return ccxt.kraken({"enableRateLimit": True})
    # Fallback
    return ccxt.binance({"enableRateLimit": True})


def fetch_ohlcv_df(exchange, symbol: str, timeframe: str = "1m", limit: int = 200) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    return df


def compute_signals(df: pd.DataFrame, fast: int = 10, slow: int = 30) -> pd.DataFrame:
    out = df.copy()
    out["sma_fast"] = out["close"].rolling(fast, min_periods=fast).mean()
    out["sma_slow"] = out["close"].rolling(slow, min_periods=slow).mean()
    out["cross_up"] = (out["sma_fast"] > out["sma_slow"]) & (out["sma_fast"].shift(1) <= out["sma_slow"].shift(1))
    out["cross_dn"] = (out["sma_fast"] < out["sma_slow"]) & (out["sma_fast"].shift(1) >= out["sma_slow"].shift(1))
    return out


def round_qty(qty: float, decimals: int = 6) -> float:
    factor = 10 ** decimals
    return math.floor(qty * factor) / factor


def run(
    symbol: str = "BTC/USDT",
    exchange_name: str = "binance",
    timeframe: str = "1m",
    starting_cash: float = 1000.0,
    fee_rate: float = 0.001,
    slippage_bp: float = 1.0,
    fast: int = 10,
    slow: int = 30,
    risk_fraction: float = 0.98,  # invest up to 98% of available cash on long entry
    poll_seconds: int = 15
):
    base, quote = symbol.split("/")
    ex = get_exchange(exchange_name)

    print(f"Using exchange={exchange_name}, symbol={symbol}, timeframe={timeframe}")
    print("Fetching initial candles...")
    df = fetch_ohlcv_df(ex, symbol, timeframe=timeframe, limit=max(200, slow + 5))
    df = compute_signals(df, fast=fast, slow=slow)

    broker = PaperBroker(
        starting_cash=starting_cash,
        fee_rate=fee_rate,
        slippage_bp=slippage_bp,
        quote=quote,
        base=base,
    )

    last_seen_ts: Optional[pd.Timestamp] = df.index[-1] if not df.empty else None
    print(f"Starting portfolio: cash={broker.cash:.2f} {quote}, position={broker.base_qty:.6f} {base}")

    try:
        while True:
            # Re-fetch small window to catch latest candle(s)
            latest = fetch_ohlcv_df(ex, symbol, timeframe=timeframe, limit=max(200, slow + 5))
            latest = compute_signals(latest, fast=fast, slow=slow)
            if latest.empty:
                time.sleep(poll_seconds)
                continue

            # Only act on a new closed candle
            new_ts = latest.index[-1]
            if last_seen_ts is not None and new_ts == last_seen_ts:
                time.sleep(poll_seconds)
                continue

            # Merge (optional) and set last_seen
            df = latest
            last_seen_ts = new_ts

            row = df.iloc[-1]
            price = float(row["close"])
            equity = broker.portfolio_value(price)

            cross_up = bool(row.get("cross_up", False))
            cross_dn = bool(row.get("cross_dn", False))

            # Strategy: long-only crossover
            if cross_up and broker.base_qty <= 1e-8:
                buy_cash = broker.cash * risk_fraction
                qty = buy_cash / price if price > 0 else 0.0
                qty = round_qty(qty, decimals=6)
                if qty > 0:
                    res = broker.market_order(symbol, "buy", qty, price)
                    print(f"[{new_ts}] BUY {qty} @ ~{price:.2f} | status={res['status']} | equity={res.get('equity', equity):.2f}")
                else:
                    print(f"[{new_ts}] BUY signal but qty=0 (price or cash constraint)")

            elif cross_dn and broker.base_qty > 1e-8:
                qty = round_qty(broker.base_qty, decimals=6)
                res = broker.market_order(symbol, "sell", qty, price)
                print(f"[{new_ts}] SELL {qty} @ ~{price:.2f} | status={res['status']} | equity={res.get('equity', equity):.2f}")

            else:
                print(f"[{new_ts}] HOLD | price={price:.2f} | cash={broker.cash:.2f} | pos={broker.base_qty:.6f} | equity={equity:.2f}")

            time.sleep(poll_seconds)

    except KeyboardInterrupt:
        last_price = float(df["close"].iloc[-1]) if not df.empty else 0.0
        print("\nInterrupted by user.")
        print(f"Final: cash={broker.cash:.2f} {quote}, pos={broker.base_qty:.6f} {base}, equity={broker.portfolio_value(last_price):.2f} {quote}")
        print(f"Trades logged to {broker.log_path}")
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(2)
        raise


if __name__ == "__main__":
    # Customize here if you want different symbols/exchanges/timeframes
    run(
        symbol="BTC/USDT",
        exchange_name="binance",   # alternatives: "bybit", "okx", "kraken"
        timeframe="1m",
        starting_cash=1000.0,
        fee_rate=0.001,            # 0.1% fee assumption
        slippage_bp=1.0,           # 1 bp slippage
        fast=10,
        slow=30,
        risk_fraction=0.98,
        poll_seconds=15
    )
```

### What this does

- Pulls latest 1-minute candles using CCXT public REST endpoints.
- Computes fast/slow moving averages and detects crossovers.
- On a bullish crossover and no position: buys with ~98% of cash.
- On a bearish crossover and a long position: sells all.
- Simulates market orders with fee and slippage; logs trades to trades.csv.
- Prints portfolio state on every new closed candle.

### Why this is efficient

- No keys, accounts, or websocket complexity required.
- Polling 1-minute candles is robust across exchanges and networks.
- Minimal state, few dependencies, tiny CPU/RAM footprint.
- Easy to extend and test.

## How to run it and what to expect

Run:
```bash
python bot.py
```

You’ll see lines like:
- HOLD when no signal
- BUY/SELL when crossovers occur
- Equity changes reflecting price, fees, slippage, and position

After stopping (Ctrl+C), open trades.csv to review fills and PnL snapshots.

> Tip: Change symbol, timeframe, fee, and slippage in the run() parameters to match your use case and assumptions.

## Optional: Use exchange testnets (real APIs, fake money)

Once you trust your strategy and loop, you can switch from a local paper broker to exchange testnets that accept orders with test funds. CCXT can route to many testnets via set_sandbox_mode(True).

Examples (remember to create testnet accounts and fund them with test assets):

### Bybit spot testnet
```python
import ccxt, os

ex = ccxt.bybit({
    "enableRateLimit": True,
    "options": {"defaultType": "spot"}
})
ex.set_sandbox_mode(True)
ex.apiKey = os.getenv("BYBIT_TESTNET_KEY")
ex.secret = os.getenv("BYBIT_TESTNET_SECRET")

# Place a small test order
# ex.create_order("BTC/USDT", "market", "buy", 0.001)
```

### OKX demo trading
```python
import ccxt, os

ex = ccxt.okx({"enableRateLimit": True})
ex.set_sandbox_mode(True)
ex.apiKey = os.getenv("OKX_API_KEY")
ex.secret = os.getenv("OKX_API_SECRET")
ex.password = os.getenv("OKX_API_PASS")  # required by OKX

# ex.create_order("BTC/USDT", "market", "buy", 0.001)
```

### Binance spot testnet (may require explicit URLs)
```python
import ccxt, os

ex = ccxt.binance({
    "enableRateLimit": True,
})
ex.set_sandbox_mode(True)
# If needed, override the API URLs:
# ex.urls["api"]["public"]  = "https://testnet.binance.vision/api"
# ex.urls["api"]["private"] = "https://testnet.binance.vision/api"

ex.apiKey = os.getenv("BINANCE_TESTNET_KEY")
ex.secret = os.getenv("BINANCE_TESTNET_SECRET")

# ex.create_order("BTC/USDT", "market", "buy", 0.001)
```

> Important: Exchange testnets can differ from production in liquidity, symbols, and order rules. Read each exchange’s docs carefully.

## Backtesting the same strategy

Before running live or even paper trading, it’s wise to backtest. Here’s a tiny backtest using the same indicator logic:

```python
# quick_backtest.py
import ccxt
import pandas as pd
import numpy as np

def fetch(symbol="BTC/USDT", timeframe="1m", limit=2000):
    ex = ccxt.binance({"enableRateLimit": True})
    raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["ts","o","h","l","c","v"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df.set_index("ts", inplace=True)
    return df

def signals(df, fast=10, slow=30):
    out = df.copy()
    out["sf"] = out["c"].rolling(fast, min_periods=fast).mean()
    out["ss"] = out["c"].rolling(slow, min_periods=slow).mean()
    out["up"] = (out["sf"] > out["ss"]) & (out["sf"].shift(1) <= out["ss"].shift(1))
    out["dn"] = (out["sf"] < out["ss"]) & (out["sf"].shift(1) >= out["ss"].shift(1))
    return out

def backtest(df, fee=0.001, slip_bp=1.0, start_cash=1000.0):
    s = signals(df)
    cash, pos = start_cash, 0.0
    slip = slip_bp/10000.0
    for i in range(1, len(s)):
        price = s["c"].iloc[i]
        if s["up"].iloc[i] and pos == 0.0:
            # buy all-in
            exec_price = price*(1+slip)
            qty = (cash/(exec_price))*(1-fee)
            cash = 0.0
            pos = qty
        elif s["dn"].iloc[i] and pos > 0.0:
            # sell all
            exec_price = price*(1-slip)
            proceeds = pos*exec_price*(1-fee)
            cash = proceeds
            pos = 0.0
    equity = cash + pos*df["c"].iloc[-1]
    return equity

if __name__ == "__main__":
    d = fetch(limit=1500)
    eq = backtest(d)
    print(f"Ending equity: {eq:.2f}")
```

This simple backtest shares the indicator logic with your live loop. For richer analysis, consider libraries like vectorbt, Backtesting.py, or backtrader.

## Performance and reliability tips

- Use 1-minute candles to start; slower timeframes reduce noise and API calls.
- Recompute indicators from a small rolling window (e.g., last 200 candles) for speed.
- Log trades and key metrics to CSV for auditing and visualization.
- Handle errors gracefully; network hiccups are normal.
- Keep fees and slippage realistic (start at 10 bps fee, 1–5 bps slippage).
- Avoid overfitting—test across multiple symbols and periods.

## Common pitfalls and troubleshooting

- Region blocks: If you can’t reach Binance endpoints, switch to Bybit or OKX and adjust symbol names as needed.
- Symbol mismatches: Some exchanges use different tickers (e.g., Kraken often uses XBT/USD). CCXT normalizes many, but double-check.
- Rate limits: Don’t fetch too frequently. The sample polls every 15 seconds, which is fine for 1m candles.
- Data gaps: In case of temporary network issues, your loop will just skip until the next successful fetch.
- Quantity precision: Real exchanges enforce min size/step; our paper broker is lenient. If you later go live/testnet, conform to exchange precision.

## Where to go next

- Replace polling with websockets for lower latency (ccxt.pro or native SDKs).
- Add risk management: stop-loss, take-profit, position sizing by volatility.
- Portfolio trading: manage multiple symbols and allocations.
- Metrics dashboard: plot equity curve, drawdown, Sharpe, win rate.
- CI backtests: nightly backtests across assets and timeframes for regression safety.
- Move to a lightweight orchestrator (Docker + cron / systemd) for reliability.

## Conclusion

You don’t need heavy frameworks or exchange accounts to start learning algorithmic crypto trading. With a lightweight Python loop, public market data, and a simple paper broker, you can design, test, and iterate strategies safely on your laptop. Once you’re confident, graduate to exchange testnets—then, if appropriate, to a small live deployment.

The key is keeping the initial stack simple, observable, and reliable. Start small, measure everything, and iterate.

> Reminder: This is not financial advice. Always validate assumptions, test extensively, and understand the risks before trading real capital.