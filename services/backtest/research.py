"""Robustheits-Prüfung von Strategie-Varianten: 4 Jahre gesamt, erste und zweite Hälfte, gleiche Kosten.

  docker compose run --rm --entrypoint python backtest /app/research.py
"""
import json
import sys

import backtest as bt
from tradebot_core.metrics import max_drawdown, sharpe, trade_stats
from tradebot_core.models import Side

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DAY = 86_400_000

VARIANTS = [
    # (Name, Strategie, Intervall, Parameter, Positionsgröße)
    ("trend 1d Standard", "trend", "1d", {}, 0.33),
    ("trend 1d vol 1 %", "trend", "1d", {"vol_target": 0.01}, 0.33),
    ("trend 1d vol 2 %", "trend", "1d", {"vol_target": 0.02}, 0.33),
    ("trend 1d vol 2 %, max 50 %", "trend", "1d", {"vol_target": 0.02}, 0.5),
    ("trend 1d entry 40", "trend", "1d", {"entry_n": 40}, 0.33),
    ("trend 1d entry 70", "trend", "1d", {"entry_n": 70}, 0.33),
    ("trend 1d exit 10", "trend", "1d", {"exit_n": 10}, 0.33),
    ("trend 1d exit 30", "trend", "1d", {"exit_n": 30}, 0.33),
    ("trend 1d atr 2", "trend", "1d", {"atr_mult": 2.0}, 0.33),
    ("trend 1d atr 4", "trend", "1d", {"atr_mult": 4.0}, 0.33),
    ("trend 4h Standard", "trend", "4h", {}, 0.33),
    ("trend 4h lang 150/40/4", "trend", "4h", {"entry_n": 150, "exit_n": 40, "atr_mult": 4.0}, 0.33),
    ("trend 4h lang 120/40/4", "trend", "4h", {"entry_n": 120, "exit_n": 40, "atr_mult": 4.0}, 0.33),
    ("trend 4h lang 180/40/4", "trend", "4h", {"entry_n": 180, "exit_n": 40, "atr_mult": 4.0}, 0.33),
    ("trend 4h lang 150/30/5", "trend", "4h", {"entry_n": 150, "exit_n": 30, "atr_mult": 5.0}, 0.33),
    ("trend 4h lang 150/60/4", "trend", "4h", {"entry_n": 150, "exit_n": 60, "atr_mult": 4.0}, 0.33),
    ("trend 4h lang + vol 2 %", "trend", "4h", {"entry_n": 150, "exit_n": 40, "atr_mult": 4.0, "vol_target": 0.02}, 0.33),
    ("meanrev 4h Standard", "meanrev", "4h", {}, 0.33),
    ("meanrev 4h ohne Filter", "meanrev", "4h", {"trend_filter": False}, 0.33),
    ("meanrev 4h RSI 35", "meanrev", "4h", {"rsi_entry": 35.0}, 0.33),
    ("meanrev 4h RSI 35, BB 1,5", "meanrev", "4h", {"rsi_entry": 35.0, "bb_k": 1.5}, 0.33),
    ("meanrev 1h RSI 30 ohne Filter", "meanrev", "1h", {"trend_filter": False}, 0.33),
]


def evaluate(candles, strategy, params, fraction, cap=10000.0):
    broker, times, equity = bt.run(candles, strategy, params, cap, SYMBOLS, fraction)
    pnls = [float(f.realized_pnl) for f in broker.fills if f.side == Side.SELL]
    ts = trade_stats(pnls)
    years = (times[-1] - times[0]) / (365 * DAY)
    cagr = (equity[-1] / cap) ** (1 / years) - 1
    mdd = max_drawdown(cap, equity)
    return {"ret": equity[-1] / cap - 1, "cagr": cagr, "mdd": mdd, "sharpe": sharpe(cap, times, equity), "calmar": cagr / mdd if mdd else None,
            "trades": ts["trades"], "pf": ts["profit_factor"], "fees": float(broker.fees_paid)}


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    data = {iv: bt.load(SYMBOLS, iv) for iv in ("1h", "4h", "1d")}
    rows = []
    for name, strategy, iv, params, frac in VARIANTS:
        if only and only not in name:
            continue
        cs = data[iv]
        mid = cs[0].close_time + (cs[-1].close_time - cs[0].close_time) // 2
        full = evaluate(cs, strategy, params, frac)
        h1 = evaluate([c for c in cs if c.close_time < mid], strategy, params, frac)
        h2 = evaluate([c for c in cs if c.close_time >= mid], strategy, params, frac)
        rows.append({"name": name, "full": full, "h1": h1, "h2": h2})
        f = lambda x: "  n/a " if x is None else f"{x:6.2f}"
        print(f"{name:32} | 4J: {full['ret']:+7.1%} CAGR {full['cagr']:+6.1%} DD {full['mdd']:5.1%} Sh {f(full['sharpe'])} Cal {f(full['calmar'])} T {full['trades']:4} PF {f(full['pf'])} Geb {full['fees']:6.0f}"
              f" | H1: {h1['ret']:+7.1%} Sh {f(h1['sharpe'])} DD {h1['mdd']:5.1%} | H2: {h2['ret']:+7.1%} Sh {f(h2['sharpe'])} DD {h2['mdd']:5.1%}", flush=True)
    bh = {}
    for iv in ("4h", "1d"):
        cs = data[iv]; mid = cs[0].close_time + (cs[-1].close_time - cs[0].close_time) // 2
        bh[iv] = [bt.buy_hold(part, SYMBOLS, 10000.0)[:2] for part in (cs, [c for c in cs if c.close_time < mid], [c for c in cs if c.close_time >= mid])]
    for iv, v in bh.items():
        print(f"Buy & Hold {iv:27} | 4J: {v[0][0]:+7.1%} DD {v[0][1]:5.1%} | H1: {v[1][0]:+7.1%} DD {v[1][1]:5.1%} | H2: {v[2][0]:+7.1%} DD {v[2][1]:5.1%}")
    with open("/tmp/research.json", "w") as fh:
        json.dump(rows, fh)


if __name__ == "__main__":
    main()
