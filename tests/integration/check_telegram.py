"""Integrationstest des Telegram-Bots ohne echtes Telegram: alle Befehle, Knöpfe und Benachrichtigungen gegen die echte DB.

  docker compose run --rm --no-deps -e TELEGRAM_CHAT_ID=4242 -v ./tests/integration:/itest:ro telegram python /itest/check_telegram.py
Legt eine Wegwerf-Wallet 'itest-tg' an und räumt danach auf.
"""
import os
import re
import sys
import time

sys.path.insert(0, "/app")
os.environ.setdefault("TELEGRAM_CHAT_ID", "4242")
import commands as C  # noqa: E402
import main as M  # noqa: E402

CHAT = int(os.environ["TELEGRAM_CHAT_ID"])
RESULTS = []
ALLOWED_TAGS = {"b", "i", "code", "pre", "a"}


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"[{'OK ' if ok else 'FEHLER'}] {name}" + (f"  ({detail})" if detail else ""), flush=True)


class FakeAPI:
    def __init__(self, forum=False):
        self.sent, self.edits, self.answers, self.forum, self.next_thread = [], [], [], forum, 100

    def call(self, method, **p):
        if method == "getChat":
            return {"id": CHAT, "type": "supergroup", "is_forum": self.forum}
        if method == "createForumTopic":
            self.next_thread += 1
            return {"message_thread_id": self.next_thread, "name": p["name"]}
        return {}

    def send(self, chat_id, text, markup=None, silent=False, thread_id=None):
        self.sent.append({"chat": chat_id, "text": text, "markup": markup, "silent": silent, "thread": thread_id}); return [{}]

    def edit(self, chat_id, mid, text, markup=None):
        self.edits.append({"chat": chat_id, "text": text, "markup": markup})

    def answer(self, cid, text=None):
        self.answers.append(text)


def html_ok(text):
    """Nur von Telegram erlaubte Tags, alle geschlossen, keine unmaskierten < >."""
    stack = []
    for m in re.finditer(r"<(/?)([a-z]+)(?: [^>]*)?>", text):
        close, tag = m.group(1), m.group(2)
        if tag not in ALLOWED_TAGS:
            return False
        if close:
            if not stack or stack.pop() != tag:
                return False
        else:
            stack.append(tag)
    stripped = re.sub(r"</?[a-z]+(?: [^>]*)?>", "", text)
    return not stack and "<" not in stripped and ">" not in stripped


def cleanup(conn):
    a = conn.execute("SELECT id FROM accounts WHERE name='itest-tg'").fetchone()
    if a:
        conn.execute("DELETE FROM fills WHERE account_id=%s", (a["id"],))
        conn.execute("DELETE FROM equity_snapshots WHERE account_id=%s", (a["id"],))
        conn.execute("DELETE FROM accounts WHERE id=%s", (a["id"],))
    conn.execute("DELETE FROM bot_state WHERE wallet='itest-tg'")
    conn.execute("DELETE FROM events WHERE wallet='itest-tg' OR (source='telegram' AND ts > %s)", (START_MS,))
    conn.execute("DELETE FROM control WHERE key LIKE '%%itest-tg%%' OR key IN ('telegram:itest')")
    conn.commit()


START_MS = int(time.time() * 1000)


def main():
    conn = M.connect()
    cleanup(conn)
    saved = {k: conn.execute("SELECT value FROM control WHERE key=%s", (k,)).fetchone() for k in
             ("telegram:notify", "telegram:topics", "telegram:routing", "telegram:silent_topics")}
    for k in ("telegram:topics", "telegram:routing", "telegram:silent_topics"):
        conn.execute("DELETE FROM control WHERE key=%s", (k,))
    conn.commit()
    try:
        # Wegwerf-Wallet mit einem abgeschlossenen und einem offenen Trade
        aid = conn.execute("INSERT INTO accounts (name, start_cash, strategy, interval, params) VALUES ('itest-tg', 10000, 'trend', '4h', %s) RETURNING id",
                           ('{"strategy_params": {"entry_n": 55}, "position_fraction": 0.33, "fee_rate": "0.001", "slippage_bps": "5", "symbols": ["BTCUSDT"]}',)).fetchone()["id"]
        conn.commit()
        api = FakeAPI()
        n = M.Notifier(api)
        n.state = {"last_fill": conn.execute("SELECT coalesce(max(id),0) m FROM fills").fetchone()["m"],
                   "last_event": conn.execute("SELECT coalesce(max(id),0) m FROM events").fetchone()["m"], "last_daily": "2999-01-01", "down": {}}
        n.save_state = lambda: None  # Test verändert den echten Melder-Zustand nicht
        t0 = int(time.time() * 1000) - 5 * 864e5
        for oid, side, qty, px, fee, pnl, ts, reason in ((1, "buy", "0.04", "80000", "3.2", "0", t0, "breakout"), (2, "sell", "0.04", "84000", "3.36", "153.44", t0 + 2 * 864e5, "stop_loss"),
                                                          (3, "buy", "0.03", "83000", "2.49", "0", t0 + 3 * 864e5, "breakout")):
            conn.execute("INSERT INTO fills (account_id, bot, order_id, symbol, side, qty, price, fee, realized_pnl, maker, ts, reason) VALUES (%s,'trend',%s,'BTCUSDT',%s,%s,%s,%s,%s,false,%s,%s)",
                         (aid, oid, side, qty, px, fee, pnl, int(ts), reason))
        conn.execute("INSERT INTO bot_state (wallet, symbol, updated_ts, state) VALUES ('itest-tg','BTCUSDT',%s,'{\"close\": 84000, \"in_position\": true, \"indicators\": {\"stop\": 79000, \"entry_level\": 86000}}')", (START_MS,))
        conn.execute("INSERT INTO events (ts, level, source, wallet, message) VALUES (%s,'warn','master','itest-tg','Auto-Pause: Test')", (START_MS,))
        conn.execute("INSERT INTO events (ts, level, source, wallet, message) VALUES (%s,'info','bots','itest-tg','KAUF 0.03 BTCUSDT @ 83000')", (START_MS,))
        conn.commit()

        # ---- Benachrichtigungen
        n.tick()
        texts = [s["text"] for s in api.sent]
        if os.environ.get("SHOW"):
            print("\n\n".join(texts[:3]), "\n")
        check("Kaufmeldung", any("Kauf · BTC" in t and "Ausbruch" in t and "Stop" in t for t in texts))
        check("Verkaufsmeldung mit Ergebnis, Grund und Dauer", any("Verkauf · BTC" in t and "+153,44" in t and "Stop-Loss" in t and "Dauer 2 T" in t for t in texts))
        check("Warn-Ereignis weitergeleitet", any("Auto-Pause: Test" in t for t in texts))
        check("Trade-Protokoll nicht doppelt gemeldet", not any("KAUF 0.03" in t for t in texts))
        check("Alle Meldungen gültiges Telegram-HTML", all(html_ok(t) for t in texts))
        api.sent.clear()
        conn.execute("INSERT INTO control (key, value) VALUES ('telegram:notify', '{\"exit\": \"off\", \"entry\": \"silent\"}') ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value")
        conn.execute("INSERT INTO fills (account_id, bot, order_id, symbol, side, qty, price, fee, realized_pnl, maker, ts, reason) VALUES (%s,'trend',4,'BTCUSDT','sell','0.03','85000','2.5','57.5',false,%s,'channel_exit')", (aid, START_MS))
        conn.execute("INSERT INTO fills (account_id, bot, order_id, symbol, side, qty, price, fee, realized_pnl, maker, ts, reason) VALUES (%s,'trend',5,'BTCUSDT','buy','0.01','85000','0.85','0',false,%s,'breakout')", (aid, START_MS + 1))
        conn.commit()
        n.tick()
        check("Einstellung off unterdrückt Verkaufsmeldung", not any("Verkauf" in s["text"] for s in api.sent))
        check("Einstellung silent sendet ohne Ton", any("Kauf" in s["text"] and s["silent"] for s in api.sent))

        # ---- Gruppe mit Themen: Anlegen und Verteilung
        conn.execute("DELETE FROM control WHERE key='telegram:notify'"); conn.commit()
        fapi = FakeAPI(forum=True)
        topics = M.T.Topics(fapi, conn, CHAT); topics.setup()
        check("Vier Themen werden angelegt", topics.forum and set(topics.ids) == {"overview", "trades_big", "trades_small", "alarms"}, str(topics.ids))
        small = conn.execute("INSERT INTO accounts (name, start_cash, strategy, interval, params) VALUES ('itest-tg-100', 100, 'trend', '4h', '{}') RETURNING id").fetchone()["id"]
        conn.commit()
        n2 = M.Notifier(fapi, topics); n2.save_state = lambda: None
        n2.state = {"last_fill": conn.execute("SELECT coalesce(max(id),0) m FROM fills").fetchone()["m"],
                    "last_event": conn.execute("SELECT coalesce(max(id),0) m FROM events").fetchone()["m"], "last_daily": "2999-01-01", "down": {}}
        conn.execute("INSERT INTO fills (account_id, bot, order_id, symbol, side, qty, price, fee, realized_pnl, maker, ts, reason) VALUES (%s,'trend',9,'BTCUSDT','buy','0.01','85000','0.85','0',false,%s,'breakout')", (aid, START_MS + 2))
        conn.execute("INSERT INTO fills (account_id, bot, order_id, symbol, side, qty, price, fee, realized_pnl, maker, ts, reason) VALUES (%s,'trend',1,'BTCUSDT','buy','0.0003','85000','0.03','0',false,%s,'breakout')", (small, START_MS + 3))
        conn.execute("INSERT INTO events (ts, level, source, wallet, message) VALUES (%s,'error','master','itest-tg','Dienst test meldet sich nicht')", (START_MS,))
        conn.execute("INSERT INTO events (ts, level, source, wallet, message) VALUES (%s,'info','bots','itest-tg','Bot-Service gestartet: Test')", (START_MS,))
        conn.commit()
        n2.tick()
        by = {s["text"].split("\n")[0]: s for s in fapi.sent}
        th = topics.ids
        big = next((s for s in fapi.sent if s["text"].split("\n")[0].endswith("· itest-tg")), None)
        smallmsg = next((s for s in fapi.sent if "itest-tg-100" in s["text"]), None)
        alarm = next((s for s in fapi.sent if "meldet sich nicht" in s["text"]), None)
        start = next((s for s in fapi.sent if "gestartet" in s["text"]), None)
        check("Trades der 10.000er-Wallet → Thema Trades 10.000", big and big["thread"] == th["trades_big"] and not big["silent"])
        check("Trades der 100er-Wallet → Thema Trades 100, ohne Ton", smallmsg and smallmsg["thread"] == th["trades_small"] and smallmsg["silent"])
        check("Fehler → Thema Alarme", alarm and alarm["thread"] == th["alarms"])
        check("Dienst-Start → Thema Übersicht, ohne Ton", start and start["thread"] == th["overview"] and start["silent"])
        fapi.sent.clear()
        topics.send("daily", "Test"); check("Tagesbericht → Thema Übersicht", fapi.sent[-1]["thread"] == th["overview"])
        M.T.set_route(conn, "daily", "alarms"); topics.send("daily", "Test"); check("/route ändert die Zuordnung", fapi.sent[-1]["thread"] == th["alarms"])
        conn.execute("DELETE FROM fills WHERE account_id=%s", (small,)); conn.execute("DELETE FROM accounts WHERE id=%s", (small,)); conn.commit()

        # ---- Befehle
        bot = M.Bot(FakeAPI())
        cmds = ["/start", "/help", "/status", "/status itest-tg", "/wallets", "/balance", "/count", "/signals", "/prices", "/profit", "/profit itest-tg",
                "/daily", "/daily 3 itest-tg", "/weekly", "/monthly 2", "/performance", "/performance itest-tg", "/stats", "/stats itest-tg", "/trades",
                "/trades 5 itest-tg", "/system", "/events 5", "/config", "/config itest-tg", "/notify", "/report", "/pause", "/resume", "/forceexit",
                "/forceexit itest-tg", "/gibtsnicht", "/profit xyz", "/status@tradebot_bot", "/coins", "/topics", "/route", "/route warning overview", "/route silent alarms on"]
        bad = []
        for c in cmds:
            try:
                t, mk = bot.run_command(c)
                if not html_ok(t) or not t.strip():
                    bad.append(c + " (HTML)")
                if mk and "inline_keyboard" in mk and any(len(b["callback_data"].encode()) > 64 for r in mk["inline_keyboard"] for b in r):
                    bad.append(c + " (Knopf zu lang)")
            except Exception as e:
                bad.append(f"{c}: {type(e).__name__}: {e}")
                conn.rollback()
        check(f"Alle {len(cmds)} Befehle laufen fehlerfrei mit gültigem HTML", not bad, "; ".join(bad))
        if os.environ.get("SHOW"):
            for c in ("/status itest-tg", "/wallets", "/daily 3", "/signals", "/profit itest-tg"):
                print(bot.run_command(c)[0], "\n")
        t, _ = bot.run_command("/profit itest-tg")
        check("/profit zeigt richtige Kennzahlen", "Trades 2" in t and "Treffer 100 %" in t, t.split("\n")[5] if len(t.split("\n")) > 5 else t)
        t, _ = bot.run_command("/status itest-tg")
        check("/status zeigt offene Position mit Stop", "itest-tg" in t and "Stop 79.000" in t)
        t, _ = bot.run_command("/stats itest-tg")
        check("/stats gruppiert nach Ausstiegsgrund", "Stop-Loss" in t and "Kanal-Ausstieg" in t)
        t, _ = bot.run_command("/profit xyz")
        check("Unbekannte Wallet wird freundlich abgelehnt", "nicht gefunden" in t)

        # ---- Knöpfe und Steuerung (auf der Wegwerf-Wallet)
        fake = bot.api
        def cb(data):
            bot.on_callback({"id": "1", "data": data, "from": {"id": 1}, "message": {"message_id": 7, "chat": {"id": CHAT}}})
        cb("p|itest-tg")
        check("Pause über Knopf setzt Steuerung", conn.execute("SELECT 1 FROM control WHERE key='pause:itest-tg'").fetchone() is not None)
        cb("u|itest-tg")
        conn.commit()
        check("Freigabe über Knopf entfernt Pause", conn.execute("SELECT 1 FROM control WHERE key='pause:itest-tg'").fetchone() is None)
        cb("fx|itest-tg|BTCUSDT")
        check("Verkaufen fragt nach Bestätigung", "jetzt verkaufen?" in fake.edits[-1]["text"] and fake.edits[-1]["markup"])
        cb("fxy|itest-tg|BTCUSDT")
        conn.commit()
        check("Bestätigter Verkauf erzeugt Auftrag für den Bot-Service", conn.execute("SELECT 1 FROM control WHERE key='forceexit:itest-tg:BTCUSDT'").fetchone() is not None)
        cb("no")
        check("Abbrechen", fake.edits[-1]["text"] == "Abgebrochen.")
        cb("r|/wallets")
        check("Aktualisieren-Knopf bearbeitet die Nachricht", "Wallets" in fake.edits[-1]["text"])

        # ---- Zugriffsschutz
        before = len(fake.sent)
        bot.on_message({"chat": {"id": 999}, "from": {"id": 999}, "text": "/kill"})
        bot.on_callback({"id": "2", "data": "ky", "from": {"id": 999}, "message": {"message_id": 1, "chat": {"id": 999}}})
        conn.commit()
        check("Fremde Chats werden ignoriert (auch Knöpfe)", len(fake.sent) == before and conn.execute("SELECT 1 FROM control WHERE key='kill'").fetchone() is None)

        # ---- Bot-Service führt den manuellen Verkauf aus: wartet auf die Verarbeitung (Wallet ist dem Dienst unbekannt -> Hinweis)
        deadline = time.time() + 20
        while time.time() < deadline and conn.execute("SELECT 1 FROM control WHERE key='forceexit:itest-tg:BTCUSDT'").fetchone():
            conn.commit(); time.sleep(1)
        conn.commit()
        check("Bot-Service verarbeitet Verkaufsauftrag", conn.execute("SELECT 1 FROM control WHERE key='forceexit:itest-tg:BTCUSDT'").fetchone() is None)
    finally:
        for k, v in saved.items():  # echte Einstellungen wiederherstellen
            conn.execute("DELETE FROM control WHERE key=%s", (k,))
            if v:
                conn.execute("INSERT INTO control (key, value) VALUES (%s, %s)", (k, v["value"]))
        conn.commit()
        cleanup(conn)
    print(f"\n{sum(RESULTS)} von {len(RESULTS)} Prüfungen bestanden.")
    sys.exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    main()
