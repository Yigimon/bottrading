"""Backtester und Walk-Forward. Nutzt exakt denselben BotRunner und PaperBroker wie der Live-Paper-Betrieb.

  docker compose run --rm backtest run --strategy trend --interval 4h --capital 10000 100
  docker compose run --rm backtest wf  --strategy meanrev --interval 1h --capital 10000
"""
import argparse
import itertools
import json
import math
import os
from bisect import bisect_left
from decimal import Decimal as D

import psycopg

from tradebot_core import PaperBroker
from tradebot_core.metrics import max_drawdown, sharpe, trade_stats
from tradebot_core.models import OrderStatus, Side
from tradebot_core.runner import BotRunner
from tradebot_core.strategy import GRIDS, STRATEGIES, Candle

DAY = 86_400_000


def STRATEGY_DEFAULTS(name):
    import inspect
    return {k: v.default for k, v in inspect.signature(STRATEGIES[name].__init__).parameters.items() if k != "self"}
FEE, SLIP = "0.001", "5"


def load(symbols, interval, since_ms=0):
    q = """SELECT symbol, interval, open_time, close_time, open, high, low, close, volume FROM candles
           WHERE symbol = ANY(%s) AND interval = %s AND open_time >= %s ORDER BY close_time, symbol"""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(q, (symbols, interval, since_ms))
        return [Candle(*r) for r in cur.fetchall()]


def run(candles, strategy, params, capital, symbols, fraction=0.33):
    broker = PaperBroker("bt", capital, fee_rate=FEE, slippage_bps=SLIP)
    runner = BotRunner(broker, lambda: STRATEGIES[strategy](**params), symbols, fraction, name=strategy)
    times, equity, cur_t = [], [], None
    for c in candles:
        if cur_t is not None and c.close_time != cur_t:
            times.append(cur_t)
            equity.append(float(broker.equity()))
        cur_t = c.close_time
        runner.on_candle(c)
    if cur_t is not None:
        times.append(cur_t)
        equity.append(float(broker.equity()))
    return broker, times, equity


def metrics(broker, times, equity, capital):
    sells = [f for f in broker.fills if f.side == Side.SELL]
    wins = [float(f.realized_pnl) for f in sells if f.realized_pnl > 0]
    losses = [float(f.realized_pnl) for f in sells if f.realized_pnl <= 0]
    return {
        "return": equity[-1] / capital - 1,
        "max_dd": max_drawdown(capital, equity),
        "sharpe": sharpe(capital, times, equity),
        "trades": len(sells),
        "win_rate": len(wins) / len(sells) if sells else 0.0,
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else (math.inf if wins else 0.0),
        **{k: v for k, v in trade_stats([float(f.realized_pnl) for f in sells]).items() if k in ("avg_win", "avg_loss", "expectancy", "best", "worst")},
        "fees": float(broker.fees_paid),
        "rejected": sum(1 for o in broker.orders.values() if o.status == OrderStatus.REJECTED),
        "end_equity": equity[-1],
    }


def buy_hold(candles, symbols, capital):
    """Gleichgewichtet kaufen und halten, mit denselben Kosten (Kauf am ersten Open, Bewertung zum Close)."""
    fee, slip = float(FEE), float(SLIP) / 10000
    first, units, last, equity, times, cur_t = {}, {}, {}, [], [], None
    for c in candles:
        first.setdefault(c.symbol, c.open)
    per = capital / len(symbols)
    for s in symbols:
        units[s] = per / (first[s] * (1 + slip) * (1 + fee))
    for c in candles:
        if cur_t is not None and c.close_time != cur_t:
            equity.append(sum(units[s] * last.get(s, first[s]) for s in symbols))
            times.append(cur_t)
        cur_t = c.close_time
        last[c.symbol] = c.close
    equity.append(sum(units[s] * last[s] * (1 - slip) * (1 - fee) for s in symbols))  # inkl. Verkaufskosten
    times.append(cur_t)
    return equity[-1] / capital - 1, max_drawdown(capital, equity), list(zip(times, equity))


def clean(o):
    """JSON-tauglich machen (inf/nan -> None)."""
    if isinstance(o, float) and (math.isinf(o) or math.isnan(o)):
        return None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


def curve(pairs, cap, n=400):
    step = max(1, len(pairs) // n)
    return [[t, e / cap - 1] for t, e in pairs[::step]]


def store_run(kind, strategy, interval, params, capital, metrics, note=""):
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("INSERT INTO backtest_runs (kind, strategy, interval, params, capital, metrics, note) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                     (kind, strategy, interval, json.dumps(clean(params)), capital, json.dumps(clean(metrics)), note))


def fmt(x, pct=True):
    if isinstance(x, float) and math.isinf(x):
        return "inf"
    return f"{x * 100:6.1f}%" if pct else f"{x:7.2f}"


def cmd_run(a):
    symbols = a.symbols.split(",")
    end_candles = load(symbols, a.interval, 0)
    last_t = end_candles[-1].close_time
    candles = [c for c in end_candles if c.close_time >= last_t - a.days * DAY]
    names = list(STRATEGIES) if a.strategy == "both" else [a.strategy]
    days = (candles[-1].close_time - candles[0].open_time) / DAY
    print(f"\n{a.interval}, {', '.join(symbols)}, {days:.0f} Tage, {len(candles)} Kerzen, Gebühr {FEE}, Slippage {SLIP} bp, "
          f"Positionsgröße {a.fraction:.0%} des Kapitals\n")
    head = f"{'Strategie':<22}{'Start':>8}{'Endwert':>10}{'Rendite':>9}{'MaxDD':>8}{'Sharpe':>8}{'Trades':>7}{'Trefferq.':>10}{'ProfitF.':>9}{'Gebühr':>8}{'Abgel.':>7}"
    print(head + "\n" + "-" * len(head))
    for cap in a.capital:
        for n in names:
            params = json.loads(a.params) if a.params else {}
            b, t, e = run(candles, n, params, cap, symbols, a.fraction)
            m = metrics(b, t, e, cap)
            print(f"{n:<22}{cap:>8}{m['end_equity']:>10.2f}{fmt(m['return']):>9}{fmt(m['max_dd']):>8}{m['sharpe']:>8.2f}"
                  f"{m['trades']:>7}{fmt(m['win_rate']):>10}{fmt(m['profit_factor'], False):>9}{m['fees']:>8.2f}{m['rejected']:>7}")
            if a.store:
                r_bh, dd_bh, bh_pairs = buy_hold(candles, symbols, cap)
                store_run("run", n, a.interval, {**STRATEGY_DEFAULTS(n), **params}, cap,
                          {**m, "period": [candles[0].open_time, candles[-1].close_time], "symbols": symbols, "fee": FEE, "slippage_bps": SLIP,
                           "position_fraction": a.fraction, "bh_return": r_bh, "bh_max_dd": dd_bh,
                           "curve": curve(list(zip(t, e)), cap), "bh_curve": curve(bh_pairs, cap)}, "Backtest 4 Jahre, Standardparameter")
        r, dd, _ = buy_hold(candles, symbols, cap)
        print(f"{'Buy & Hold (gleichgew.)':<22}{cap:>8}{cap * (1 + r):>10.2f}{fmt(r):>9}{fmt(dd):>8}")
        print()


def slice_time(candles, times, lo, hi):
    return candles[bisect_left(times, lo):bisect_left(times, hi)]


def cmd_wf(a):
    symbols = a.symbols.split(",")
    all_c = load(symbols, a.interval, 0)
    end = all_c[-1].close_time
    start = end - a.days * DAY
    all_c = [c for c in all_c if c.close_time >= start]
    times = [c.close_time for c in all_c]
    grid = [dict(zip(GRIDS[a.strategy], v)) for v in itertools.product(*GRIDS[a.strategy].values())]
    cap = a.capital[0]
    default = {}
    print(f"\nWalk-Forward {a.strategy} {a.interval}: Train {a.train_days} Tage, Test {a.test_days} Tage, {len(grid)} Parameter-Kombinationen\n")
    print(f"{'Test-Zeitraum ab':<18}{'gewählte Parameter':<46}{'OOS Optim.':>11}{'OOS Default':>12}{'Buy&Hold':>10}")
    compound = {"opt": 1.0, "def": 1.0, "bh": 1.0}
    windows = []
    s = start
    while s + (a.train_days + a.test_days) * DAY <= end:
        t0, t1 = s + a.train_days * DAY, s + (a.train_days + a.test_days) * DAY
        train, full = slice_time(all_c, times, s, t0), slice_time(all_c, times, s, t1)
        best, best_score = None, -1e18
        for p in grid:
            b, tt, ee = run(train, a.strategy, p, cap, symbols, a.fraction)
            m = metrics(b, tt, ee, cap)
            score = m["return"] / max(m["max_dd"], 0.05) if m["trades"] >= 5 else -1e9
            if score > best_score:
                best, best_score = p, score

        def oos(params):
            b, tt, ee = run(full, a.strategy, params, cap, symbols, a.fraction)
            k = bisect_left(tt, t0)  # letzter Stand vor Testbeginn
            return ee[-1] / ee[k - 1] - 1

        r_opt, r_def = oos(best or default), oos(default)
        r_bh, _, _ = buy_hold(slice_time(all_c, times, t0, t1), symbols, cap)
        compound["opt"] *= 1 + r_opt
        compound["def"] *= 1 + r_def
        compound["bh"] *= 1 + r_bh
        date = __import__("datetime").datetime.fromtimestamp(t0 / 1000, __import__("datetime").timezone.utc).strftime("%Y-%m-%d")
        print(f"{date:<18}{json.dumps(best):<46}{fmt(r_opt):>11}{fmt(r_def):>12}{fmt(r_bh):>10}")
        windows.append({"test_start": date, "params": best, "optimized": r_opt, "default": r_def, "buy_hold": r_bh})
        s += a.test_days * DAY
    print(f"\nKumuliert (nur Out-of-Sample): Optimiert {fmt(compound['opt'] - 1)}, Default {fmt(compound['def'] - 1)}, Buy&Hold {fmt(compound['bh'] - 1)}\n")
    if a.store:
        store_run("walkforward", a.strategy, a.interval, {"train_days": a.train_days, "test_days": a.test_days, "grid_size": len(grid), "grid": GRIDS[a.strategy]}, cap,
                  {"windows": windows, "cumulative": {k: v - 1 for k, v in compound.items()}}, "Parameter nur auf Vergangenheit gewählt, Test auf ungesehenen Daten")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("run", cmd_run), ("wf", cmd_wf)):
        s = sub.add_parser(name)
        s.set_defaults(fn=fn)
        s.add_argument("--strategy", default="both" if name == "run" else "trend")
        s.add_argument("--interval", default="4h")
        s.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
        s.add_argument("--capital", type=float, nargs="+", default=[10000, 100])
        s.add_argument("--days", type=int, default=1460)
        s.add_argument("--fraction", type=float, default=0.33)
        s.add_argument("--params", default="")
        s.add_argument("--train-days", type=int, default=365)
        s.add_argument("--test-days", type=int, default=90)
        s.add_argument("--fee", default="0.001", help="Gebühr je Order, z. B. 0.00075 mit BNB-Rabatt")
        s.add_argument("--slip", default="5", help="Slippage in Basispunkten")
        s.add_argument("--store", action="store_true", help="Ergebnis in der Datenbank speichern (für das Dashboard)")
    a = p.parse_args()
    global FEE, SLIP
    FEE, SLIP = a.fee, a.slip
    a.fn(a)


if __name__ == "__main__":
    main()
