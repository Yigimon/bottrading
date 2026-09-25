"""Live-Paper-Runner: fährt die Strategien mit echten Live-Kerzen und virtuellem Geld.

Unabhängige Wallets (Strategie x Intervall x Startkapital), damit die Ergebnisse direkt mit den Backtests
vergleichbar sind. Zustand (Fills, Equity) liegt in Postgres und wird nach einem Neustart wiederhergestellt.
Steuerung: Tabelle `control` (Pause je Wallet, globaler Kill-Switch), geschrieben vom Dashboard/Master-Bot.
"""
import asyncio
import inspect
import json
import logging
import os
import time
from decimal import Decimal as D

import psycopg
import redis.asyncio as aioredis
from psycopg.rows import dict_row

from tradebot_core import PaperBroker
from tradebot_core.models import Fill, OrderType, Side
from tradebot_core.runner import BotRunner
from tradebot_core.state import add_event, now_ms
from tradebot_core.strategy import STRATEGIES, Candle

DATABASE_URL, REDIS_URL = os.environ["DATABASE_URL"], os.environ["REDIS_URL"]
SYMBOLS = os.environ["SYMBOLS"].split(",")
# (Strategie, Intervall, Startkapital, Namens-Zusatz, abweichende Parameter).
# Namen: "trend-10000" (4h, Standard), "trend1d-10000", "trend4hL-10000" (4h, lange Kanäle, siehe research.py).
TREND_4H_LONG = {"entry_n": 150, "exit_n": 40, "atr_mult": 4.0}
WALLETS = [("trend", "4h", 10000, "", {}), ("meanrev", "4h", 10000, "", {}), ("trend", "4h", 100, "", {}), ("meanrev", "4h", 100, "", {}),
           ("trend", "1d", 10000, "1d", {}), ("trend", "1d", 100, "1d", {}),
           ("trend", "4h", 10000, "4hL", TREND_4H_LONG), ("trend", "4h", 100, "4hL", TREND_4H_LONG)]
INTERVALS = sorted({w[1] for w in WALLETS})
WARMUP_CANDLES = 600
FRACTION = 0.33
FEE, SLIPPAGE_BPS = "0.001", "5"

log = logging.getLogger("bots")
COLS = "symbol, interval, open_time, close_time, open, high, low, close, volume"


def wallet_name(strategy, capital, suffix=""):
    return f"{strategy}{suffix}-{capital}"


class Wallet:
    def __init__(self, strategy: str, interval: str, capital: int, account_id: int, suffix: str = "", params: dict | None = None):
        self.name, self.account_id, self.strategy, self.interval = wallet_name(strategy, capital, suffix), account_id, strategy, interval
        self.params = {**strategy_params(strategy), **(params or {})}
        self.broker = PaperBroker(self.name, capital, fee_rate=FEE, slippage_bps=SLIPPAGE_BPS)
        self.runner = BotRunner(self.broker, lambda: STRATEGIES[strategy](**self.params), SYMBOLS, FRACTION, name=strategy, immediate=True)
        self.persisted = 0


def strategy_params(name: str) -> dict:
    return {k: v.default for k, v in inspect.signature(STRATEGIES[name].__init__).parameters.items() if k != "self"}


def candles_from(db, sql, params):
    with db.cursor() as cur:
        cur.execute(sql, params)
        return [Candle(s, i, int(o), int(ct), float(op), float(h), float(lo), float(cl), float(v))
                for s, i, o, ct, op, h, lo, cl, v in cur.fetchall()]


def setup(db) -> list[Wallet]:
    wallets = []
    with db.cursor() as cur:
        for strategy, interval, capital, suffix, overrides in WALLETS:
            name = wallet_name(strategy, capital, suffix)
            params = {"strategy_params": {**strategy_params(strategy), **overrides}, "position_fraction": FRACTION, "fee_rate": FEE,
                      "slippage_bps": SLIPPAGE_BPS, "symbols": SYMBOLS, "interval": interval, "long_only": True,
                      "execution": "Signal bei Kerzenschluss, Marktorder sofort zum aktuellen Kurs"}
            cur.execute("INSERT INTO accounts (name, start_cash, strategy, interval, params) VALUES (%s, %s, %s, %s, %s) "
                        "ON CONFLICT (name) DO UPDATE SET params = EXCLUDED.params", (name, capital, strategy, interval, json.dumps(params)))
            cur.execute("SELECT id FROM accounts WHERE name = %s", (name,))
            wallets.append(Wallet(strategy, interval, capital, cur.fetchone()[0], suffix, overrides))
    db.commit()
    return wallets


def last_processed(db, w: Wallet) -> dict[str, int]:
    """Je Coin: close_time der zuletzt verarbeiteten Kerze (aus bot_state), sonst der Startzeitpunkt der Wallet."""
    with db.cursor() as cur:
        cur.execute("SELECT (extract(epoch FROM created_at) * 1000)::bigint FROM accounts WHERE id=%s", (w.account_id,))
        created = int(cur.fetchone()[0])
        cur.execute("SELECT symbol, (state->>'candle_close_time')::bigint FROM bot_state WHERE wallet=%s", (w.name,))
        done = {s: int(t) for s, t in cur.fetchall() if t is not None}
    return {s: done.get(s, created) for s in SYMBOLS}


def restore_and_warm(db, w: Wallet, history: list[Candle]) -> list[Candle]:
    """Zustand wiederherstellen und Indikatoren bis zur zuletzt verarbeiteten Kerze aufwärmen.
    Gibt die danach geschlossenen Kerzen zurück; diese müssen regulär (mit Handel) nachgespielt werden."""
    cutoff = last_processed(db, w)
    with db.cursor() as cur:
        cur.execute("SELECT order_id, symbol, side, qty, price, fee, realized_pnl, ts, bot, maker, reason FROM fills "
                    "WHERE account_id = %s ORDER BY ts, id", (w.account_id,))
        fills = [Fill(o, s, Side(sd), D(q), D(p), D(f), D(r), t, b, m, rs) for o, s, sd, q, p, f, r, t, b, m, rs in cur.fetchall()]
    w.broker.restore(fills)
    w.persisted = len(w.broker.fills)
    entry_ts = {}  # Zeitpunkt des letzten Kaufs je Symbol, für den Strategiezustand
    for f in fills:
        if f.side == Side.BUY:
            entry_ts[f.symbol] = f.ts
    pending = []
    for c in history:
        if c.close_time > cutoff[c.symbol]:  # nach der letzten Verarbeitung geschlossen: nachspielen
            pending.append(c)
            continue
        in_pos = w.broker.position_qty(c.symbol) > 0 and c.close_time > entry_ts.get(c.symbol, float("inf"))
        w.runner.strategies[c.symbol].on_candle(c, in_position=in_pos)  # nur Indikatoren aufwärmen, keine Orders
        w.broker.set_price(c.symbol, c.close)
    log.info("%s: %d Fills wiederhergestellt, Cash %.2f, Positionen %s, %d Kerzen nachzuspielen", w.name, len(fills), w.broker.cash,
             {s: str(p.qty) for s, p in w.broker.positions.items()}, len(pending))
    return pending


def save_state(db, w: Wallet, c: Candle) -> None:
    """Indikatoren und Signalstatus je Wallet und Symbol für das Dashboard."""
    st, pos = w.runner.strategies[c.symbol], w.broker.positions.get(c.symbol)
    state = {"candle_close_time": c.close_time, "close": c.close, "in_position": bool(pos),
             "qty": float(pos.qty) if pos else 0.0, "avg_cost": float(pos.avg_cost) if pos else None,
             "indicators": st.indicators(), "last_signal": w.runner.last_signal.get(c.symbol),
             "entries_enabled": w.runner.entries_enabled}
    with db.cursor() as cur:
        cur.execute("INSERT INTO bot_state (wallet, symbol, updated_ts, state) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (wallet, symbol) DO UPDATE SET updated_ts = EXCLUDED.updated_ts, state = EXCLUDED.state",
                    (w.name, c.symbol, now_ms(), json.dumps(state)))


def persist(db, w: Wallet, ts: int) -> None:
    with db.cursor() as cur:
        for f in w.broker.fills[w.persisted:]:
            cur.execute("INSERT INTO fills (account_id, bot, order_id, symbol, side, qty, price, fee, realized_pnl, maker, ts, reason) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (w.account_id, f.bot, f.order_id, f.symbol, f.side.value, f.qty, f.price, f.fee, f.realized_pnl, f.maker, f.ts, f.reason))
            msg = f"{'KAUF' if f.side == Side.BUY else 'VERKAUF'} {f.qty} {f.symbol} @ {f.price} (Gebühr {f.fee:.4f}" + \
                  (f", Ergebnis {f.realized_pnl:+.4f})" if f.side == Side.SELL else ")") + (f" [{f.reason}]" if f.reason else "")
            log.info("%s: %s", w.name, msg)
            cur.execute("INSERT INTO events (ts, level, source, wallet, message) VALUES (%s,'info','bots',%s,%s)", (now_ms(), w.name, msg))
        w.persisted = len(w.broker.fills)
        cur.execute("INSERT INTO equity_snapshots (account_id, ts, cash, equity) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (account_id, ts) DO UPDATE SET cash = EXCLUDED.cash, equity = EXCLUDED.equity",
                    (w.account_id, ts, w.broker.cash, w.broker.equity()))
    # kein commit hier: Fills, Snapshot und bot_state werden vom Aufrufer gemeinsam bestätigt (kein doppeltes Buchen beim Nachspielen)


def close_position(dbc, w: Wallet, sym: str, reason: str) -> bool:
    """Position zum letzten 15-Minuten-Kurs schließen (Kill-Switch oder manueller Ausstieg)."""
    if w.broker.position_qty(sym) <= 0:
        return False
    row = dbc.execute("SELECT close FROM candles WHERE symbol=%s AND interval='15m' ORDER BY open_time DESC LIMIT 1", (sym,)).fetchone()
    if row:
        w.broker.set_price(sym, D(str(row["close"])))
    o = w.broker.place_order(sym, Side.SELL, w.broker.position_qty(sym), OrderType.MARKET, ts=now_ms(), bot=reason.replace("_", "-"), reason=reason)
    return o.status.value == "filled"


def liquidate(dbc, wallets: list[Wallet]) -> None:
    """Kill-Switch: alle offenen Positionen zum letzten 15-Minuten-Kurs schließen."""
    for w in wallets:
        for sym in list(w.broker.positions):
            close_position(dbc, w, sym, "kill_switch")
        persist(dbc, w, now_ms())
    add_event(dbc, "bots", "warn", "Kill-Switch: alle Positionen geschlossen")
    dbc.commit()


async def control_loop(wallets: list[Wallet]) -> None:
    """Liest alle 5 s die Steuerung: Pause je Wallet, globaler Kill-Switch und manuelle Ausstiege."""
    dbc = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    killed = False
    while True:
        try:
            ctrl = {r["key"]: r["value"] for r in dbc.execute("SELECT key, value FROM control").fetchall()}
            dbc.commit()
            kill = "kill" in ctrl
            for w in wallets:
                want = not (kill or f"pause:{w.name}" in ctrl)
                if want != w.runner.entries_enabled:
                    w.runner.entries_enabled = want
                    add_event(dbc, "bots", "warn" if not want else "info", "Neue Einstiege " + ("wieder aktiv" if want else "pausiert"), w.name)
                    dbc.commit()
            if kill and not killed:
                liquidate(dbc, wallets)
            killed = kill
            for key in [k for k in ctrl if k.startswith("forceexit:")]:  # manueller Ausstieg (Telegram/Dashboard)
                _, wname, target = key.split(":", 2)
                w = next((x for x in wallets if x.name == wname), None)
                closed = []
                if w:
                    for sym in (list(w.broker.positions) if target == "all" else [target]):
                        if close_position(dbc, w, sym, "force_exit"):
                            closed.append(sym)
                    persist(dbc, w, now_ms())
                dbc.execute("DELETE FROM control WHERE key=%s", (key,))
                add_event(dbc, "bots", "warn" if closed else "info",
                          f"Manueller Ausstieg: {', '.join(closed)} geschlossen" if closed else f"Manueller Ausstieg: keine offene Position ({target})", wname)
                dbc.commit()
        except Exception as e:  # Steuerung darf den Handel nie abstürzen lassen
            log.error("Steuerung: %s", e)
            dbc.rollback()
        await asyncio.sleep(5)


async def heartbeat(r):
    while True:
        await r.set("heartbeat:bots", str(time.time()))
        await asyncio.sleep(10)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    r = aioredis.from_url(REDIS_URL)
    hb = asyncio.create_task(heartbeat(r))
    db = psycopg.connect(DATABASE_URL)
    wallets = setup(db)

    last_seen: dict[tuple[str, str], int] = {}  # (Symbol, Intervall) -> open_time der letzten verarbeiteten Kerze
    history: dict[str, list[Candle]] = {}
    for iv in INTERVALS:
        history[iv] = []
        for sym in SYMBOLS:
            rows = candles_from(db, f"SELECT {COLS} FROM (SELECT {COLS} FROM candles WHERE symbol=%s AND interval=%s "
                                    f"ORDER BY open_time DESC LIMIT %s) t ORDER BY open_time", (sym, iv, WARMUP_CANDLES))
            history[iv] += rows
            last_seen[(sym, iv)] = rows[-1].open_time
        history[iv].sort(key=lambda c: (c.close_time, c.symbol))
    for w in wallets:
        replay = restore_and_warm(db, w, history[w.interval])
        for c in replay:  # während einer Pause des Dienstes geschlossene Kerzen regulär verarbeiten
            w.runner.on_candle(c)
            persist(db, w, c.close_time)
        if replay:
            add_event(db, "bots", "info", f"{len(replay)} verpasste Kerzen nachverarbeitet", w.name)
        for sym in SYMBOLS:
            save_state(db, w, [c for c in history[w.interval] if c.symbol == sym][-1])
    db.commit()
    add_event(db, "bots", "info", f"Bot-Service gestartet: {len(wallets)} Wallets, {', '.join(SYMBOLS)}")
    db.commit()
    log.info("Bereit: %d Wallets, %s, Intervalle %s", len(wallets), SYMBOLS, INTERVALS)
    ctl = asyncio.create_task(control_loop(wallets))

    pubsub = r.pubsub()
    await pubsub.subscribe("candles")
    async for msg in pubsub.listen():
        if msg["type"] != "message":
            continue
        d = json.loads(msg["data"])
        sym, iv = d["symbol"], d["interval"]
        if iv not in INTERVALS or sym not in SYMBOLS or d["open_time"] <= last_seen[(sym, iv)]:
            continue
        rows = candles_from(db, f"SELECT {COLS} FROM candles WHERE symbol=%s AND interval=%s AND open_time > %s "
                                f"AND open_time <= %s ORDER BY open_time", (sym, iv, last_seen[(sym, iv)], d["open_time"]))
        for c in rows:
            for w in (w for w in wallets if w.interval == iv):
                w.runner.on_candle(c)  # auch verpasste Kerzen normal verarbeiten (Stops und Ausstiege dürfen nicht verloren gehen)
                persist(db, w, c.close_time)
                save_state(db, w, c)
            db.commit()
            last_seen[(sym, iv)] = c.open_time
    await asyncio.gather(hb, ctl)


if __name__ == "__main__":
    asyncio.run(main())
