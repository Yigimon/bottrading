"""Telegram-Bot: Befehle (Long Polling) und Benachrichtigungen (Trades, Warnungen, Ausfälle, Tagesbericht).

Konfiguration (.env):
  TELEGRAM_TOKEN          Token von @BotFather
  TELEGRAM_CHAT_ID        einzige Chat-ID (Direktchat oder Gruppe), die Befehle senden darf und Meldungen bekommt
  TELEGRAM_AUTHORIZED     kommagetrennte User-IDs, die steuern dürfen (in Gruppen dringend empfohlen)
In einer Gruppe mit Themen legt der Bot die Themen selbst an (siehe topics.py) und verteilt die Meldungen.
  TELEGRAM_DAILY_REPORT   Uhrzeit des Tagesberichts, deutsche Zeit (Standard 21:00)
Ohne TELEGRAM_CHAT_ID läuft der Bot im Einrichtungsmodus und nennt auf /start nur die Chat-ID.
"""
import datetime as dt
import json
import logging
import os
import threading
import time

import psycopg
import redis
from psycopg.rows import dict_row

import commands as C
import topics as T
from fmt import LOCAL, coin, dur, esc, money, num, pct, price, signed, table, trend_icon
from tg import TelegramAPI, TelegramError
from tradebot_core.state import REASONS, broker_for, latest_prices, round_trips

log = logging.getLogger("telegram")
DB = os.environ["DATABASE_URL"]
R = redis.Redis.from_url(os.environ["REDIS_URL"])
TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
AUTHORIZED = {x.strip() for x in os.environ.get("TELEGRAM_AUTHORIZED", "").split(",") if x.strip()}
DAILY_AT = os.environ.get("TELEGRAM_DAILY_REPORT", "21:00")
WATCH = ("market-data", "bots", "master")


def connect():
    return psycopg.connect(DB, row_factory=dict_row, autocommit=False)


# ------------------------------------------------------------------ Meldungstexte
def entry_message(conn, f) -> str:
    a = conn.execute("SELECT id, name, start_cash, strategy, interval, created_at, params FROM accounts WHERE name=%s", (f["wallet"],)).fetchone()
    b = broker_for(conn, a, latest_prices(conn, C.SYMBOLS))
    eq = float(b.equity()); stake = float(f["qty"] * f["price"])
    st = conn.execute("SELECT state FROM bot_state WHERE wallet=%s AND symbol=%s", (f["wallet"], f["symbol"])).fetchone()
    stop = ((st or {}).get("state") or {}).get("indicators", {}).get("stop") if st else None
    lines = [f"🔵 <b>Kauf · {coin(f['symbol'])}</b> · {esc(f['wallet'])}",
             f"Grund: {REASONS.get(f['reason'], f['reason'] or '–')} ({C.STRAT.get(a['strategy'], a['strategy'])}, {a['interval']})",
             f"Menge {num(float(f['qty']), 5)} @ {price(float(f['price']))}",
             f"Einsatz {money(stake)} USDT ({pct(stake / eq, 0, False)} des Wallets) · Gebühr {num(float(f['fee']), 2)}"]
    if stop:
        lines.append(f"Stop {price(stop)} ({pct(stop / float(f['price']) - 1)})")
    return "\n".join(lines)


def exit_message(conn, f) -> str:
    a = conn.execute("SELECT id, name, start_cash, strategy, interval, created_at, params FROM accounts WHERE name=%s", (f["wallet"],)).fetchone()
    fills = conn.execute("SELECT symbol, side, qty, price, fee, realized_pnl, ts, bot, reason FROM fills WHERE account_id=%s AND id <= %s ORDER BY ts, id", (a["id"], f["id"])).fetchall()
    trip = next((t for t in reversed(round_trips(fills)) if t["symbol"] == f["symbol"] and t["closed"] == f["ts"]), None)
    b = broker_for(conn, a, latest_prices(conn, C.SYMBOLS))
    eq, start = float(b.equity()), float(a["start_cash"])
    pnl = float(f["realized_pnl"])
    ratio = trip["pnl_pct"] if trip else None
    icon = "🚀" if ratio is not None and ratio >= 0.05 else "✳️" if pnl >= 0 else "⚠️" if f["reason"] == "stop_loss" else "❌"
    lines = [f"{icon} <b>Verkauf · {coin(f['symbol'])}</b> · {esc(f['wallet'])}",
             f"Ergebnis <b>{signed(pnl)} USDT</b>" + (f" ({pct(ratio)})" if ratio is not None else "") + " nach Gebühren",
             f"Grund: {REASONS.get(f['reason'], f['reason'] or '–')}"]
    if trip:
        lines.append(f"{price(trip['entry'])} → {price(trip['exit'])} · Dauer {dur(trip['hold_days'])}")
    lines.append(f"Wallet jetzt {money(eq)} USDT ({pct(eq / start - 1, 2)})")
    return "\n".join(lines)


def event_type(e) -> str:
    if "gestartet" in e["message"]:
        return "startup"
    return {"error": "error", "warn": "warning"}.get(e["level"], "info")


def event_message(e) -> str:
    icon = {"error": "❌", "warn": "⚠️"}.get(e["level"], "ℹ️")
    return f"{icon} <b>{esc(e['source'])}</b>" + (f" · {esc(e['wallet'])}" if e["wallet"] else "") + f"\n{esc(e['message'])}"


def daily_report(conn) -> str:
    ctx = C.Ctx(conn)
    rep = conn.execute("SELECT value FROM control WHERE key='master_report'").fetchone()
    day = {w["wallet"]: w for w in (json.loads(rep["value"]).get("wallets", []) if rep else [])}
    rows_, open_pos = [], 0
    for a in ctx.accounts():
        b = ctx.broker(a); eq = float(b.equity()); open_pos += len(b.positions)
        rows_.append([a["name"], money(eq), pct(eq / float(a["start_cash"]) - 1, 1), pct((day.get(a["name"]) or {}).get("day_change"), 1)])
    since = int((time.time() - 86400) * 1000)
    trips = [t for t in ctx.trips() if t["closed"] >= since]
    prices = ctx.prices()
    now = dt.datetime.now(LOCAL)
    lines = [f"📋 <b>Tagesbericht {now:%d.%m.%Y}</b>", "",
             table(["Wallet", "Wert", "Gesamt", "24 h"], rows_), "",
             f"Trades in 24 h: {len(trips)}" + (f" · Ergebnis {signed(sum(t['pnl'] for t in trips))} USDT" if trips else ""),
             f"Offene Positionen: {open_pos}",
             "", "<b>Je Coin</b>", C.coins_block(ctx)]
    text, _ = C.cmd_system(ctx, [], R)
    problems = [l for l in text.split("\n") if l.startswith("🔴")]
    lines.append("")
    lines.append("System: " + ("alles in Ordnung" if not problems else "Störung – " + "; ".join(p[2:] for p in problems)))
    return "\n".join(lines)


# ------------------------------------------------------------------ Bot
class Bot:
    def __init__(self, api: TelegramAPI):
        self.api = api
        self.conn = connect()

    def authorized(self, chat_id, user_id) -> bool:
        return bool(CHAT_ID) and str(chat_id) == CHAT_ID and (not AUTHORIZED or str(user_id) in AUTHORIZED)

    def run_command(self, text: str):
        parts = text.strip().split()
        cmd = parts[0].lstrip("/").split("@")[0].lower()
        args = parts[1:]
        ctx = C.Ctx(self.conn)
        if cmd in ("start", "help"):
            return C.HELP, C.KEYBOARD
        if cmd == "system":
            return C.cmd_system(ctx, args, R)
        if cmd == "report":
            return daily_report(self.conn), None
        fn = C.COMMANDS.get(cmd)
        if not fn:
            return f"Unbekannter Befehl <code>/{esc(cmd)}</code>. Übersicht: /help", None
        return fn(ctx, args)

    def on_message(self, m):
        chat, user, text = m["chat"]["id"], (m.get("from") or {}).get("id"), m.get("text") or ""
        if not text.startswith("/"):
            return
        thread = m.get("message_thread_id") if m.get("is_topic_message") else None
        if not CHAT_ID:
            if text.startswith("/start"):
                kind = m["chat"].get("type"); forum = m["chat"].get("is_forum")
                self.api.send(chat, f"👋 Einrichtung\nChat-ID: <code>{chat}</code> ({esc(kind)}{', Themen aktiv' if forum else ''})\nDeine User-ID: <code>{user}</code>\n\n"
                                    "Diese Werte werden in der .env eingetragen (TELEGRAM_CHAT_ID und TELEGRAM_AUTHORIZED). Bis dahin nimmt der Bot keine Befehle an.", thread_id=thread)
            log.info("Einrichtungsmodus: /start aus Chat %s (%s, Themen: %s) von User %s", chat, m["chat"].get("type"), m["chat"].get("is_forum"), user)
            return
        if not self.authorized(chat, user):
            log.warning("Nicht autorisierter Zugriff: Chat %s, User %s", chat, user)
            return
        text_out, markup = self.run_command(text)
        self.api.send(chat, text_out, markup, thread_id=thread)

    def on_callback(self, q):
        msg, data, user = q.get("message") or {}, q.get("data") or "", (q.get("from") or {}).get("id")
        chat = (msg.get("chat") or {}).get("id")
        if not self.authorized(chat, user):
            self.api.answer(q["id"], "Nicht erlaubt")
            return
        ctx = C.Ctx(self.conn)
        kind, _, rest = data.partition("|")
        mid = msg.get("message_id")
        if kind == "r":
            text_out, markup = self.run_command(rest)
            self.api.edit(chat, mid, text_out, markup); self.api.answer(q["id"], "Aktualisiert")
        elif kind in ("p", "u"):
            self.api.edit(chat, mid, C.do_pause(ctx, rest, kind == "p")); self.api.answer(q["id"])
        elif kind == "c":
            text_out, markup = C.cmd_config(ctx, [rest]); self.api.edit(chat, mid, text_out, markup); self.api.answer(q["id"])
        elif kind == "fx":
            w, s = rest.split("|"); text_out, markup = C.confirm_forceexit(w, s); self.api.edit(chat, mid, text_out, markup); self.api.answer(q["id"])
        elif kind == "fxy":
            w, s = rest.split("|"); self.api.edit(chat, mid, C.do_forceexit(ctx, w, s)); self.api.answer(q["id"], "Verkauf angefordert")
        elif kind == "ky":
            self.api.edit(chat, mid, C.do_kill(ctx)); self.api.answer(q["id"], "Kill-Switch aktiv")
        else:
            self.api.edit(chat, mid, "Abgebrochen."); self.api.answer(q["id"])

    def poll_forever(self):
        offset = None
        while True:
            try:
                for u in self.api.updates(offset):
                    offset = u["update_id"] + 1
                    try:
                        if "message" in u:
                            self.on_message(u["message"])
                        elif "callback_query" in u:
                            self.on_callback(u["callback_query"])
                    except Exception as e:  # ein fehlerhafter Befehl darf den Bot nicht stoppen
                        log.exception("Befehl fehlgeschlagen")
                        self.conn.rollback()
                        m = u.get("message") or (u.get("callback_query") or {}).get("message") or {}
                        chat = m.get("chat", {}).get("id")
                        if chat and str(chat) == CHAT_ID:
                            self.api.send(chat, f"❌ Fehler bei der Ausführung: <code>{esc(type(e).__name__)}: {esc(str(e)[:300])}</code>",
                                          thread_id=m.get("message_thread_id") if m.get("is_topic_message") else None)
                self.conn.rollback()  # keine offene Transaktion zwischen Abfragen halten
            except TelegramError as e:
                log.warning("Polling: %s", e)
                time.sleep(5)
            except Exception:
                log.exception("Polling-Fehler")
                time.sleep(5)


# ------------------------------------------------------------------ Benachrichtigungen
class Notifier:
    def __init__(self, api: TelegramAPI, topics=None):
        self.api = api
        self.conn = connect()
        self.topics = topics or T.Topics(api, self.conn, CHAT_ID)
        self.topics.conn = self.conn  # ab jetzt nur noch vom Melder-Thread genutzt
        self.state = self.load_state()

    def load_state(self):
        row = self.conn.execute("SELECT value FROM control WHERE key='telegram:state'").fetchone()
        if row:
            return json.loads(row["value"])
        f = self.conn.execute("SELECT coalesce(max(id), 0) AS m FROM fills").fetchone()["m"]
        e = self.conn.execute("SELECT coalesce(max(id), 0) AS m FROM events").fetchone()["m"]
        self.conn.commit()
        return {"last_fill": f, "last_event": e, "last_daily": dt.datetime.now(LOCAL).date().isoformat(), "down": {}}  # kein Nachsenden alter Einträge

    def save_state(self):
        self.conn.execute("INSERT INTO control (key, value) VALUES ('telegram:state', %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()", (json.dumps(self.state),))
        self.conn.commit()

    def send(self, kind: str, text: str, settings: dict, route: str | None = None):
        """kind: Einstellung aus /notify (entry, exit, warning ...); route: Zuordnung zum Thema (Standard = kind)."""
        mode = settings.get(kind, "on")
        if mode == "off" or not CHAT_ID:
            return
        self.topics.send(route or kind, text, silent=(mode == "silent"))

    def tick(self):
        settings = C.notify_settings(self.conn)
        fills = self.conn.execute("SELECT f.id, a.name AS wallet, a.start_cash, f.symbol, f.side, f.qty, f.price, f.fee, f.realized_pnl, f.ts, f.reason FROM fills f "
                                  "JOIN accounts a ON a.id=f.account_id WHERE f.id > %s ORDER BY f.id", (self.state["last_fill"],)).fetchall()
        for f in fills:
            route = "trades_big" if float(f["start_cash"]) >= 1000 else "trades_small"
            if f["side"] == "buy":
                self.send("entry", entry_message(self.conn, f), settings, route)
            else:
                self.send("exit", exit_message(self.conn, f), settings, route)
            self.state["last_fill"] = f["id"]; self.save_state()
        events = self.conn.execute("SELECT id, ts, level, source, wallet, message FROM events WHERE id > %s ORDER BY id", (self.state["last_event"],)).fetchall()
        for e in events:
            trade_log = e["source"] == "bots" and e["message"].startswith(("KAUF ", "VERKAUF "))  # kommt schon als Trade-Meldung
            if e["source"] != "telegram" and not trade_log:
                self.send(event_type(e), event_message(e), settings)
            self.state["last_event"] = e["id"]; self.save_state()
        self.watch_services(settings)
        now = dt.datetime.now(LOCAL)
        hh, mm = (int(x) for x in DAILY_AT.split(":"))
        if now.date().isoformat() != self.state.get("last_daily") and (now.hour, now.minute) >= (hh, mm):
            self.send("daily", daily_report(self.conn), settings)
            self.state["last_daily"] = now.date().isoformat(); self.save_state()
        self.conn.rollback()

    def watch_services(self, settings):
        """Eigene Überwachung: meldet, wenn ein Dienst länger als 2 Minuten schweigt (auch wenn der Master ausfällt)."""
        now, down = time.time(), self.state.setdefault("down", {})
        for svc in WATCH:
            v = R.get(f"heartbeat:{svc}")
            is_down = v is None or now - float(v) > 120
            if is_down and not down.get(svc):
                self.send("error", f"🔴 <b>Dienst {esc(svc)} meldet sich nicht</b>\nSeit mehr als 2 Minuten kein Lebenszeichen. Docker startet ihn in der Regel automatisch neu.", settings)
            elif not is_down and down.get(svc):
                self.send("info", f"🟢 Dienst <b>{esc(svc)}</b> läuft wieder.", settings)
            if bool(down.get(svc)) != is_down:
                down[svc] = is_down; self.save_state()

    def run_forever(self):
        while True:
            try:
                self.tick()
            except TelegramError as e:
                log.warning("Senden fehlgeschlagen: %s", e)
                self.conn.rollback()
            except Exception:
                log.exception("Benachrichtigung fehlgeschlagen")
                self.conn.rollback()
            time.sleep(5)


def heartbeat():
    while True:
        R.set("heartbeat:telegram", str(time.time()))
        time.sleep(10)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    threading.Thread(target=heartbeat, daemon=True).start()
    if not TOKEN:
        log.warning("TELEGRAM_TOKEN fehlt: Telegram ist deaktiviert (Dienst wartet).")
        while True:
            time.sleep(3600)
    api = TelegramAPI(TOKEN)
    me = api.call("getMe")
    log.info("Verbunden als @%s, %s", me.get("username"), "Chat-ID gesetzt" if CHAT_ID else "EINRICHTUNGSMODUS (keine Chat-ID)")
    api.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in C.MENU])
    if CHAT_ID:
        topics = T.Topics(api, connect(), CHAT_ID)
        topics.setup()
        log.info("Chat %s: %s", "Gruppe mit Themen" if topics.forum else "ohne Themen", topics.ids if topics.forum else "")
        threading.Thread(target=Notifier(api, topics).run_forever, daemon=True).start()
        topics.send("startup", "🤖 <b>Tradebot verbunden.</b> Befehle: /help" + ("\nMeldungen laufen in die Themen dieser Gruppe (/topics)." if topics.forum else ""),
                    silent=C.notify_settings(connect()).get("startup") == "silent", markup=C.KEYBOARD)
    if not AUTHORIZED and CHAT_ID.startswith("-"):
        log.warning("Gruppe ohne TELEGRAM_AUTHORIZED: jedes Gruppenmitglied könnte steuern.")
    Bot(api).poll_forever()


if __name__ == "__main__":
    main()
