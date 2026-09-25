"""Integrationstests gegen die echte Datenbank. Nutzt nur Wegwerf-Wallets (Präfix 'itest-') und räumt danach auf.

  docker compose run --rm --no-deps -v ./tests/integration:/itest:ro bots python /itest/check_system.py
"""
import json
import os
import random
import sys
import time
from decimal import Decimal as D

import psycopg

sys.path.insert(0, "/app")
import main as bots  # noqa: E402  Bot-Service
from tradebot_core import PaperBroker  # noqa: E402
from tradebot_core.models import Side  # noqa: E402
from tradebot_core.runner import BotRunner  # noqa: E402
from tradebot_core.strategy import STRATEGIES, Candle  # noqa: E402

DB = os.environ["DATABASE_URL"]
SYMBOLS = bots.SYMBOLS
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'OK ' if ok else 'FEHLER'}] {name}" + (f"  ({detail})" if detail else ""), flush=True)


def load(conn, interval, since_ms=0):
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, interval, open_time, close_time, open, high, low, close, volume FROM candles "
                    "WHERE symbol = ANY(%s) AND interval=%s AND open_time >= %s ORDER BY close_time, symbol", (SYMBOLS, interval, since_ms))
        return [Candle(*r) for r in cur.fetchall()]


def cleanup(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM accounts WHERE name LIKE 'itest-%'")
        ids = [r[0] for r in cur.fetchall()]
        for t in ("fills", "equity_snapshots"):
            cur.execute(f"DELETE FROM {t} WHERE account_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM accounts WHERE id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM bot_state WHERE wallet LIKE 'itest-%'")
        cur.execute("DELETE FROM events WHERE wallet LIKE 'itest-%'")
        cur.execute("DELETE FROM control WHERE key LIKE 'pause:itest-%'")
    conn.commit()


# ------------------------------------------------------------------ 1. Datenqualität
def test_data(conn):
    step = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
    with conn.cursor() as cur:
        for iv, ms in step.items():
            cur.execute("""SELECT count(*) FROM (SELECT open_time, lead(open_time) OVER (PARTITION BY symbol ORDER BY open_time) nxt
                           FROM candles WHERE interval=%s) t WHERE nxt - open_time > %s""", (iv, ms))
            gaps = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM candles WHERE interval=%s AND (high < low OR high < greatest(open, close) OR low > least(open, close) OR close <= 0)", (iv,))
            bad = cur.fetchone()[0]
            # Bekannte Binance-Wartungspause 24.03.2023 erzeugt je Symbol genau eine Lücke in 15m/1h
            check(f"Kerzen {iv}: keine ungültigen Kerzen, Lücken nur Binance-Wartung", bad == 0 and gaps <= 3, f"ungültig {bad}, Lücken {gaps}")
        cur.execute("SELECT max(close_time) FROM candles WHERE interval='15m'")
        age = time.time() - cur.fetchone()[0] / 1000
        check("Live-Kursdaten aktuell (15m-Kerze < 20 min alt)", age < 1200, f"{age:.0f} s")
        cur.execute("SELECT account_id, order_id, count(*) FROM fills GROUP BY 1,2 HAVING count(*) > 1")
        check("Keine doppelt gebuchten Orders", not cur.fetchall())


# ------------------------------------------------------------------ 2. Live-Code == Backtest
def run_backtest(candles, strategy, params, immediate):
    b = PaperBroker("x", 10000)
    r = BotRunner(b, lambda: STRATEGIES[strategy](**params), SYMBOLS, 0.33, name=strategy, immediate=immediate)
    for c in candles:
        r.on_candle(c)
    return b


def test_live_vs_backtest(conn):
    for strategy, iv, params in (("trend", "1d", {}), ("trend", "4h", bots.TREND_4H_LONG), ("meanrev", "4h", {})):
        cs = load(conn, iv)
        live, bt = run_backtest(cs, strategy, params, True), run_backtest(cs, strategy, params, False)
        rl, rb = float(live.equity()) / 10000 - 1, float(bt.equity()) / 10000 - 1
        nl, nb = len(live.fills), len(bt.fills)
        # Live führt zum Schluss der Signalkerze aus, der Backtest zum Open der nächsten; bei Krypto (24/7) sind beide Preise fast gleich
        check(f"Live-Ausführung ≈ Backtest ({strategy} {iv})", abs(rl - rb) < 0.05 and abs(nl - nb) <= 2, f"live {rl:+.1%} / {nl} Orders, backtest {rb:+.1%} / {nb} Orders")


# ------------------------------------------------------------------ 3. Neustart-Festigkeit des Bot-Service
def make_wallet(conn, name, strategy, interval, params, created_ms):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO accounts (name, start_cash, strategy, interval, params, created_at) VALUES (%s, 10000, %s, %s, %s, to_timestamp(%s)) RETURNING id",
                    (name, strategy, interval, json.dumps({"strategy_params": params}), created_ms / 1000))
        aid = cur.fetchone()[0]
    conn.commit()
    return aid


def wallet_obj(aid, name, strategy, interval, params):
    w = bots.Wallet(strategy, interval, 10000, aid, "", params)
    w.name = name  # Wegwerf-Name
    w.broker.name = name
    return w


def test_restart_replay(conn):
    """Die letzten ~120 Tageskerzen live verarbeiten, dabei 6-mal zufällig 'abstürzen' und neu starten (inkl. Nachspielen
    verpasster Kerzen). Ergebnis muss identisch mit einem ununterbrochenen Lauf sein."""
    strategy, iv, params = "trend", "4h", bots.TREND_4H_LONG
    allc = load(conn, iv)
    times = sorted({c.close_time for c in allc})
    start_t = times[-720]  # 120 Tage 4h-Kerzen live
    warm = [c for c in allc if c.close_time <= start_t][-bots.WARMUP_CANDLES * len(SYMBOLS):]
    live = [c for c in allc if c.close_time > start_t]
    results = {}
    random.seed(7)
    for mode in ("durchgehend", "mit_neustarts"):
        name = f"itest-{mode}"
        aid = make_wallet(conn, name, strategy, iv, params, start_t)
        crash_points = set(random.sample(range(len(live)), 6)) if mode == "mit_neustarts" else set()
        w = wallet_obj(aid, name, strategy, iv, params)
        bots.restore_and_warm(conn, w, warm)
        down_until = -1
        for i, c in enumerate(live):
            if i in crash_points:  # Dienst fällt aus; die nächsten 0 bis 5 Kerzen verpasst er
                down_until = i + random.randint(0, 5)
            if i <= down_until:
                continue
            if down_until >= 0 and i == down_until + 1:  # Neustart: Zustand aus der DB, verpasste Kerzen nachspielen
                w = wallet_obj(aid, name, strategy, iv, params)
                hist = warm + [x for x in live[:i]]
                for x in bots.restore_and_warm(conn, w, hist[-bots.WARMUP_CANDLES * len(SYMBOLS) * 2:]):
                    w.runner.on_candle(x); bots.persist(conn, w, x.close_time); bots.save_state(conn, w, x)
                conn.commit()
                down_until = -1
            w.runner.on_candle(c)
            bots.persist(conn, w, c.close_time)
            bots.save_state(conn, w, c)
            conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT symbol, side, qty, price FROM fills WHERE account_id=%s ORDER BY ts, id", (aid,))
            fills = cur.fetchall()
            cur.execute("SELECT equity FROM equity_snapshots WHERE account_id=%s ORDER BY ts DESC LIMIT 1", (aid,))
            eq = cur.fetchone()[0]
        results[mode] = (fills, eq)
    same = results["durchgehend"][0] == results["mit_neustarts"][0] and abs(results["durchgehend"][1] - results["mit_neustarts"][1]) < D("0.0001")
    check("Neustarts und verpasste Kerzen ändern nichts am Ergebnis", same,
          f"{len(results['durchgehend'][0])} Orders, Wert {float(results['durchgehend'][1]):.2f} gegen {len(results['mit_neustarts'][0])} Orders, Wert {float(results['mit_neustarts'][1]):.2f}")
    check("Neustart-Test hat tatsächlich gehandelt", len(results["durchgehend"][0]) > 0, f"{len(results['durchgehend'][0])} Orders")


# ------------------------------------------------------------------ 4. Master-Bot: Auto-Pause
def test_master_autopause(conn):
    aid = make_wallet(conn, "itest-master", "trend", "4h", {}, int(time.time() * 1000) - 86_400_000 * 3)
    with conn.cursor() as cur:  # Höchststand 20.000, aktueller Wert 10.000 -> 50 % Drawdown
        cur.execute("INSERT INTO equity_snapshots (account_id, ts, cash, equity) VALUES (%s, %s, 20000, 20000)", (aid, int(time.time() * 1000) - 86_400_000 * 2))
    conn.commit()
    deadline = time.time() + 90
    paused = None
    while time.time() < deadline:
        with conn.cursor() as cur:
            cur.execute("SELECT reason FROM control WHERE key='pause:itest-master'")
            paused = cur.fetchone()
        conn.commit()
        if paused:
            break
        time.sleep(3)
    check("Master pausiert Wallet bei Drawdown über der Grenze", bool(paused), paused[0] if paused else "keine Pause nach 90 s")


def main():
    conn = psycopg.connect(DB)
    cleanup(conn)
    try:
        test_data(conn)
        test_live_vs_backtest(conn)
        test_restart_replay(conn)
        test_master_autopause(conn)
    finally:
        cleanup(conn)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} von {len(RESULTS)} Prüfungen bestanden.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
