"""Master-Bot: überwacht System und Wallets, setzt harte Risikogrenzen durch und pflegt das Ereignisprotokoll.

Was er tut:
- Systemüberwachung: Heartbeats von market-data und bots sowie Frische der Kursdaten.
- Risiko je Wallet: Drawdown und Tagesverlust. Bei Überschreitung werden neue Einstiege pausiert (Position bleibt
  bestehen und wird von der Strategie normal ausgestiegen). Wieder-Freigabe nur manuell (Dashboard).
- Qualitätswarnung bei schlechten Kennzahlen (kein Auto-Stopp: Paper-Trading dient dem Lernen).
- Tagesbericht ins Ereignisprotokoll.
Der Kill-Switch ist bewusst manuell (Dashboard) und wird vom Bot-Service ausgeführt.
"""
import datetime as dt
import json
import logging
import os
import time
from decimal import Decimal as D

import psycopg
import redis
from psycopg.rows import dict_row

from tradebot_core.metrics import trade_stats
from tradebot_core.models import Side
from tradebot_core.state import add_event, broker_for, latest_prices, now_ms

DATABASE_URL, REDIS_URL = os.environ["DATABASE_URL"], os.environ["REDIS_URL"]
SYMBOLS = os.environ["SYMBOLS"].split(",")
INTERVAL_S = 30
RULES = {
    "max_drawdown": 0.35,          # ab -35 % vom bisherigen Höchststand: Wallet pausieren
    "daily_loss": 0.12,            # ab -12 % innerhalb von 24 h: Wallet pausieren
    "min_trades_for_quality": 20,  # ab so vielen Trades gilt die Qualitätswarnung
    "min_profit_factor": 0.7,
    "heartbeat_max_age_s": 60,
    "candle_max_age_s": 1500,      # 15-Minuten-Kerze plus Toleranz
}
SERVICES = ["market-data", "bots"]

log = logging.getLogger("master")
seen: dict[str, str] = {}  # letzter gemeldeter Zustand je Prüfung, damit nur Änderungen protokolliert werden


def transition(conn, key: str, state: str, level_bad: str, msg_bad: str, msg_ok: str, wallet: str | None = None) -> None:
    prev = seen.get(key)
    seen[key] = state
    if state == "bad" and prev != "bad":
        add_event(conn, "master", level_bad, msg_bad, wallet)
    elif state == "ok" and prev == "bad":
        add_event(conn, "master", "info", msg_ok, wallet)


def check_system(conn, r) -> dict:
    now, out = time.time(), {}
    for svc in SERVICES:
        v = r.get(f"heartbeat:{svc}")
        age = round(now - float(v), 1) if v else None
        out[svc] = age
        bad = age is None or age > RULES["heartbeat_max_age_s"]
        transition(conn, f"hb:{svc}", "bad" if bad else "ok", "error",
                   f"Dienst '{svc}' meldet sich nicht ({'kein Signal' if age is None else f'{age:.0f} s'})", f"Dienst '{svc}' läuft wieder")
    last = conn.execute("SELECT max(close_time) AS t FROM candles WHERE interval='15m'").fetchone()["t"]
    candle_age = round(now - last / 1000, 1) if last else None
    bad = candle_age is None or candle_age > RULES["candle_max_age_s"]
    transition(conn, "candles", "bad" if bad else "ok", "error", f"Kursdaten veraltet ({candle_age} s)", "Kursdaten sind wieder aktuell")
    return {"heartbeat_age_s": out, "candle_age_s": candle_age}


def check_wallets(conn, prices) -> list[dict]:
    rows, now = [], now_ms()
    paused = {r["key"] for r in conn.execute("SELECT key FROM control WHERE key LIKE 'pause:%'").fetchall()}
    for a in conn.execute("SELECT id, name, start_cash FROM accounts ORDER BY name").fetchall():
        b = broker_for(conn, a, prices)
        start, eq = float(a["start_cash"]), float(b.equity())
        snaps = conn.execute("SELECT ts, equity FROM equity_snapshots WHERE account_id=%s ORDER BY ts", (a["id"],)).fetchall()
        peak = max([start] + [float(s["equity"]) for s in snaps] + [eq])
        dd = (peak - eq) / peak
        old = [float(s["equity"]) for s in snaps if s["ts"] <= now - 86_400_000]
        day_change = eq / (old[-1] if old else start) - 1
        sells = [float(f.realized_pnl) for f in b.fills if f.side == Side.SELL]
        ts = trade_stats(sells)
        status = "pausiert" if f"pause:{a['name']}" in paused else "aktiv"
        reason = None
        if status == "aktiv" and (dd > RULES["max_drawdown"] or day_change < -RULES["daily_loss"]):
            reason = (f"Drawdown {dd:.1%} > {RULES['max_drawdown']:.0%}" if dd > RULES["max_drawdown"]
                      else f"Tagesverlust {day_change:.1%} < -{RULES['daily_loss']:.0%}")
            conn.execute("INSERT INTO control (key, value, reason) VALUES (%s, '1', %s) ON CONFLICT (key) DO UPDATE SET value='1', reason=EXCLUDED.reason, updated_at=now()",
                         (f"pause:{a['name']}", f"Auto-Pause: {reason}"))
            add_event(conn, "master", "error", f"Auto-Pause: {reason}. Neue Einstiege gestoppt, Freigabe nur manuell.", a["name"])
            status = "pausiert"
        pf = ts["profit_factor"]
        weak = ts["trades"] >= RULES["min_trades_for_quality"] and pf is not None and pf < RULES["min_profit_factor"]
        transition(conn, f"quality:{a['name']}", "bad" if weak else "ok", "warn",
                   f"Schwache Kennzahlen: Profit-Faktor {pf:.2f} bei {ts['trades']} Trades (Warnung, kein Stopp)" if weak else "",
                   "Kennzahlen wieder ausreichend", a["name"])
        rows.append({"wallet": a["name"], "equity": eq, "return": eq / start - 1, "drawdown": dd, "day_change": day_change,
                     "trades": ts["trades"], "profit_factor": pf if pf is None or pf != float("inf") else None,
                     "status": status, "auto_pause_reason": reason})
    conn.commit()
    return rows


def save(conn, key: str, obj) -> None:
    conn.execute("INSERT INTO control (key, value, reason) VALUES (%s, %s, NULL) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()",
                 (key, json.dumps(obj, default=str)))


def daily_report(conn, wallets) -> None:
    lines = "; ".join(f"{w['wallet']} {w['return']:+.1%}" for w in wallets)
    add_event(conn, "master", "info", f"Tagesbericht: {lines}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    r = redis.Redis.from_url(REDIS_URL)
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False)
    add_event(conn, "master", "info", "Master-Bot gestartet")
    conn.commit()
    last_report_day = None
    while True:
        t0 = time.time()
        try:
            r.set("heartbeat:master", str(time.time()))
            system = check_system(conn, r)
            prices = latest_prices(conn, SYMBOLS)
            wallets = check_wallets(conn, prices)
            today = dt.datetime.now(dt.timezone.utc).date()
            if last_report_day != today and dt.datetime.now(dt.timezone.utc).time() >= dt.time(0, 5):
                if last_report_day is not None:  # nicht direkt beim Start
                    daily_report(conn, wallets)
                last_report_day = today
            save(conn, "master_report", {"updated_ms": now_ms(), "rules": RULES, "system": system, "wallets": wallets})
            conn.commit()
        except Exception as e:
            log.exception("Prüfung fehlgeschlagen: %s", e)
            conn.rollback()
        time.sleep(max(1.0, INTERVAL_S - (time.time() - t0)))


if __name__ == "__main__":
    main()
