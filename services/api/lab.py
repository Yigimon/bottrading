"""Analyse-Labor: Backtests mit frei gewählten Parametern, Parameter-Sensitivität, Kennzahlen, Monatsrenditen.

Nutzt denselben Backtester (services/backtest/backtest.py) wie die Kommandozeile, also denselben BotRunner und PaperBroker.
"""
import datetime as dt
import math
import threading
import time
from collections import defaultdict

import backtest as bt
from tradebot_core.metrics import DAY_MS, daily_returns, max_drawdown, sharpe, trade_stats
from tradebot_core.models import Side
from tradebot_core.strategy import STRATEGIES

LOCK = threading.Lock()  # bt.FEE/bt.SLIP sind Modulvariablen
_CACHE: dict[tuple, tuple[float, list]] = {}
INTERVALS = ("1h", "4h", "1d")
MAX_SWEEP = 8


def candles(symbols: tuple, interval: str) -> list:
    key = (symbols, interval)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    data = bt.load(list(symbols), interval, 0)
    _CACHE[key] = (time.time(), data)
    return data


def round_trips(fills) -> list[dict]:
    open_, out = {}, []
    for f in fills:
        o = open_.get(f.symbol)
        if f.side == Side.BUY:
            if not o:
                o = open_[f.symbol] = {"opened": f.ts, "qty": 0.0, "cost": 0.0}
            o["qty"] += float(f.qty); o["cost"] += float(f.qty * f.price)
        elif o:
            entry = o["cost"] / o["qty"]
            out.append({"symbol": f.symbol, "opened": o["opened"], "closed": f.ts, "entry": entry, "exit": float(f.price),
                        "pnl": float(f.realized_pnl), "pnl_pct": float(f.price) / entry - 1, "hold_days": (f.ts - o["opened"]) / DAY_MS})
            open_.pop(f.symbol, None)
    return out


def monthly(times: list[int], equity: list[float], start: float) -> list[dict]:
    last: dict[str, float] = {}
    for t, e in zip(times, equity):
        last[dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).strftime("%Y-%m")] = e
    out, prev = [], start
    for m in sorted(last):
        out.append({"month": m, "return": last[m] / prev - 1})
        prev = last[m]
    return out


def summarize(capital, times, equity, fills, bh=None, n_symbols: int = 3) -> dict:
    trips = round_trips(fills)
    ts = trade_stats([t["pnl"] for t in trips])
    years = (times[-1] - times[0]) / (365 * DAY_MS) if len(times) > 1 else 0
    ret = equity[-1] / capital - 1
    mdd = max_drawdown(capital, equity)
    cagr = (equity[-1] / capital) ** (1 / years) - 1 if years > 0.05 and equity[-1] > 0 else None
    dr = daily_returns(capital, times, equity)
    vol = (sum((r - sum(dr) / len(dr)) ** 2 for r in dr) / (len(dr) - 1)) ** 0.5 * math.sqrt(365) if len(dr) > 2 else None
    fees = sum(float(f.fee) for f in fills)
    # Investitionsgrad: durchschnittlicher Anteil der Coins, die gerade gehalten werden
    in_market = 0.0
    if trips and years > 0:
        in_market = min(1.0, sum(t["hold_days"] for t in trips) / (years * 365) / n_symbols)
    peak, dd = capital, []
    for t, e in zip(times, equity):
        peak = max(peak, e)
        dd.append([t, -(peak - e) / peak])
    per_symbol = defaultdict(list)
    for t in trips:
        per_symbol[t["symbol"]].append(t["pnl"])
    out = {
        "return": ret, "cagr": cagr, "max_drawdown": mdd, "sharpe": sharpe(capital, times, equity), "volatility": vol,
        "calmar": (cagr / mdd) if cagr is not None and mdd > 0 else None, "fees": fees, "exposure": in_market,
        "avg_hold": sum(t["hold_days"] for t in trips) / len(trips) if trips else None,
        **{k: (None if isinstance(v, float) and math.isinf(v) else v) for k, v in ts.items()},
        "end_equity": equity[-1], "period": [times[0], times[-1]] if times else None,
        "per_symbol": {s: {"trades": len(p), "pnl": sum(p), "win_rate": sum(x > 0 for x in p) / len(p)} for s, p in per_symbol.items()},
    }
    if bh is not None:
        out["bh_return"], out["bh_max_drawdown"] = bh
    return out, trips, dd


def thin(points, n=600):
    step = max(1, len(points) // n)
    pts = points[::step]
    if points and pts[-1] is not points[-1]:
        pts.append(points[-1])
    return pts


def run(req: dict) -> dict:
    strategy, interval = req["strategy"], req.get("interval", "1d")
    if strategy not in STRATEGIES or interval not in INTERVALS:
        raise ValueError("unbekannte Strategie oder Intervall")
    symbols = tuple(req.get("symbols") or ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    capital = float(req.get("capital", 10000))
    fraction = float(req.get("fraction", 0.33))
    days = int(req.get("days", 1460))
    params = {k: v for k, v in (req.get("params") or {}).items() if v is not None}
    all_c = candles(symbols, interval)
    if not all_c:
        raise ValueError("keine Kursdaten")
    end = all_c[-1].close_time
    cs = [c for c in all_c if c.close_time >= end - days * DAY_MS]
    with LOCK:
        bt.FEE, bt.SLIP = str(req.get("fee", "0.001")), str(req.get("slippage_bps", "5"))
        broker, times, equity = bt.run(cs, strategy, params, capital, list(symbols), fraction)
        bh_r, bh_dd, bh_pairs = bt.buy_hold(cs, list(symbols), capital)
    m, trips, dd = summarize(capital, times, equity, broker.fills, (bh_r, bh_dd), len(symbols))
    bh_times, bh_eq = [t for t, _ in bh_pairs], [e for _, e in bh_pairs]
    return {
        "request": {"strategy": strategy, "interval": interval, "symbols": list(symbols), "capital": capital, "fraction": fraction,
                    "days": days, "params": {**bt.STRATEGY_DEFAULTS(strategy), **params}, "fee": req.get("fee", "0.001"), "slippage_bps": req.get("slippage_bps", "5")},
        "metrics": m,
        "curve": thin([[t, e / capital - 1] for t, e in zip(times, equity)]),
        "bh_curve": thin([[t, e / capital - 1] for t, e in bh_pairs]),
        "drawdown": thin(dd),
        "monthly": monthly(times, equity, capital),
        "bh_monthly": monthly(bh_times, bh_eq, capital),
        "trades": trips[::-1][:500],
    }


def sweep(req: dict) -> dict:
    param, values = req["param"], list(req["values"])[:MAX_SWEEP]
    rows = []
    for v in values:
        r = run({**req, "params": {**(req.get("params") or {}), param: v}})
        m = r["metrics"]
        rows.append({"value": v, **{k: m.get(k) for k in ("return", "cagr", "max_drawdown", "sharpe", "calmar", "trades", "win_rate", "profit_factor", "fees")},
                     "curve": thin(r["curve"], 200)})
    return {"param": param, "rows": rows, "bh_return": r["metrics"].get("bh_return") if values else None}
