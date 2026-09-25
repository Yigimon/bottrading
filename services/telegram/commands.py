"""Telegram-Befehle (nach dem Vorbild von freqtrade). Jede Funktion liefert (Text, Inline-Tastatur | None).

Lesende Befehle nutzen dieselben Helfer wie das Dashboard (tradebot_core.state), damit die Zahlen übereinstimmen.
Steuerbefehle schreiben in die Tabelle `control`, die der Bot-Service alle 5 s liest.
"""
import datetime as dt
import json
import time
from collections import defaultdict

from fmt import coin, dur, esc, money, num, pct, price, signed, table, trend_icon, ts
from tradebot_core.docs import PARAMS
from tradebot_core.metrics import max_drawdown, trade_stats
from tradebot_core.models import Side
from tradebot_core.state import REASONS, add_event, broker_for, latest_prices, now_ms, round_trips

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
PERIOD_CMD = {"day": "daily", "week": "weekly", "month": "monthly"}
STRAT = {"trend": "Trend-Ausbruch", "meanrev": "Mean Reversion"}
NOTIFY_TYPES = {"entry": "Käufe", "exit": "Verkäufe", "warning": "Warnungen (Pausen, Ausfälle)", "error": "Fehler", "info": "Info-Ereignisse",
                "startup": "Start von Diensten", "daily": "Tagesbericht"}
NOTIFY_DEFAULT = {"entry": "on", "exit": "on", "warning": "on", "error": "on", "info": "silent", "startup": "silent", "daily": "on"}
KEYBOARD = {"keyboard": [["/status", "/wallets", "/profit"], ["/daily", "/trades", "/coins"], ["/pause", "/resume", "/help"]], "resize_keyboard": True, "is_persistent": True}

HELP = """<b>Tradebot · Befehle</b>

<b>Überblick</b>
/status [wallet] – offene Positionen
/wallets – alle Wallets mit Wert und Rendite
/count – belegte Positions-Plätze je Wallet
/coins – je Coin: Kurs, gehalten, Abstand zum Signal
/signals – wie nah jeder Coin am Kaufsignal ist
/prices – aktuelle Kurse

<b>Auswertung</b>
/profit [wallet] – Gewinn, Trefferquote, Profit-Faktor
/daily [n] · /weekly [n] · /monthly [n] – Ergebnis je Zeitraum
/performance [wallet] – Ergebnis je Coin
/stats [wallet] – Ergebnis je Ausstiegsgrund
/trades [n] [wallet] – letzte abgeschlossene Trades
/report – Tagesbericht jetzt senden

<b>Steuerung</b>
/pause [wallet|all] – keine neuen Einstiege
/resume [wallet|all] – wieder freigeben
/forceexit [wallet] – Position sofort verkaufen
/kill · /unkill – Kill-Switch (alles verkaufen)

<b>System</b>
/system – Dienste, Kursdaten, Pausen
/events [n] – letzte Ereignisse
/config [wallet] – Parameter einer Wallet
/notify [typ on|silent|off] – Benachrichtigungen
/topics · /route – Themen der Gruppe und Zuordnung

Wallet-Namen dürfen abgekürzt werden, z. B. <code>/profit trend4hL-1</code>."""


# ------------------------------------------------------------------ Hilfen
def btn(text, data):
    return {"text": text, "callback_data": data[:64]}


def rows(buttons, cols=2):
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


def refresh(cmd):
    return {"inline_keyboard": [[btn("↻ Aktualisieren", "r|" + cmd)]]}


class Ctx:
    """Datenzugriff für einen Befehl. conn: psycopg-Verbindung mit dict_row."""

    def __init__(self, conn):
        self.conn = conn
        self._accts = None
        self._prices = None

    def accounts(self):
        if self._accts is None:
            self._accts = self.conn.execute("SELECT id, name, start_cash, strategy, interval, created_at, params FROM accounts ORDER BY name").fetchall()
        return self._accts

    def prices(self):
        if self._prices is None:
            self._prices = latest_prices(self.conn, SYMBOLS)
        return self._prices

    def resolve(self, arg: str | None):
        """Wallet-Name (auch abgekürzt, ohne Groß/Klein) -> Konto; None wenn nicht eindeutig."""
        if not arg:
            return None
        names = self.accounts()
        exact = [a for a in names if a["name"].lower() == arg.lower()]
        if exact:
            return exact[0]
        pre = [a for a in names if a["name"].lower().startswith(arg.lower())]
        return pre[0] if len(pre) == 1 else None

    def broker(self, a):
        return broker_for(self.conn, a, self.prices())

    def fills(self, a=None):
        q = ("SELECT a.name AS wallet, f.symbol, f.side, f.qty, f.price, f.fee, f.realized_pnl, f.ts, f.bot, f.reason, f.id FROM fills f "
             "JOIN accounts a ON a.id=f.account_id " + ("WHERE f.account_id=%s " if a else "") + "ORDER BY f.ts, f.id")
        return self.conn.execute(q, (a["id"],) if a else ()).fetchall()

    def trips(self, a=None):
        out = []
        by_wallet = defaultdict(list)
        for f in self.fills(a):
            by_wallet[f["wallet"]].append(f)
        for w, fs in by_wallet.items():
            for t in round_trips(fs):
                t["wallet"] = w
                out.append(t)
        return sorted(out, key=lambda t: t["closed"])

    def control(self):
        return {r["key"]: r for r in self.conn.execute("SELECT key, value, reason FROM control").fetchall()}

    def states(self, wallet):
        return {r["symbol"]: r["state"] for r in self.conn.execute("SELECT symbol, state FROM bot_state WHERE wallet=%s", (wallet,)).fetchall()}


def unknown_wallet(ctx, arg):
    return f"Wallet <code>{esc(arg)}</code> nicht gefunden oder nicht eindeutig.\nVorhanden: " + ", ".join(f"<code>{esc(a['name'])}</code>" for a in ctx.accounts()), None


# ------------------------------------------------------------------ Überblick
def cmd_status(ctx, args):
    accts = [ctx.resolve(args[0])] if args else ctx.accounts()
    if args and not accts[0]:
        return unknown_wallet(ctx, args[0])
    blocks = []
    for a in accts:
        b = ctx.broker(a)
        if not b.positions:
            continue
        st = ctx.states(a["name"])
        opened = {}
        for f in b.fills:
            if f.side == Side.BUY:
                opened[f.symbol] = f.ts
        for sym, p in b.positions.items():
            px = float(b.prices[sym]); cost = float(p.cost); val = float(p.qty) * px
            ind = (st.get(sym) or {}).get("indicators", {})
            stop = ind.get("stop")
            lines = [f"<b>{esc(a['name'])}</b> · {coin(sym)}",
                     f"{num(float(p.qty), 5)} @ {price(float(p.avg_cost))} → {price(px)}",
                     f"{trend_icon(val - cost)} {signed(val - cost)} USDT ({pct(val / cost - 1)}) · seit {dur((now_ms() - opened.get(sym, now_ms())) / 864e5)}"]
            if stop:
                lines.append(f"Stop {price(stop)} ({pct(stop / px - 1)})")
            blocks.append("\n".join(lines))
    if not blocks:
        return ("📭 Keine offenen Positionen." + (f" {esc(accts[0]['name'])} wartet auf ein Signal." if args else " Alle Wallets warten auf Signale.")
                + "\nWie nah die Signale sind: /signals"), refresh("/status " + " ".join(args))
    return f"📊 <b>Offene Positionen ({len(blocks)})</b>\n\n" + "\n\n".join(blocks), refresh("/status " + " ".join(args))


def cmd_wallets(ctx, args):
    rows_, ctrl = [], ctx.control()
    for a in ctx.accounts():
        b = ctx.broker(a); eq = float(b.equity()); start = float(a["start_cash"])
        flag = "⏸" if f"pause:{a['name']}" in ctrl or "kill" in ctrl else ""
        rows_.append([a["name"] + flag, money(eq), pct(eq / start - 1, 2)])
    return "💼 <b>Wallets</b> (virtuelles Geld)\n" + table(["Wallet", "Wert", "Rendite"], rows_) + "\n⏸ = pausiert", refresh("/wallets")


def cmd_count(ctx, args):
    rows_ = []
    for a in ctx.accounts():
        b = ctx.broker(a)
        rows_.append([a["name"], f"{len(b.positions)}/{len(SYMBOLS)}", ", ".join(coin(s) for s in b.positions) or "–"])
    return "🔢 <b>Belegte Plätze</b> (max. 1 Position je Coin)\n" + table(["Wallet", "Plätze", "Coins"], rows_, "lrl"), refresh("/count")


def signal_text(strategy, s):
    ind, c = s.get("indicators", {}), s.get("close")
    if s.get("in_position"):
        return "Position" + (f", Stop {pct(ind['stop'] / c - 1, 1)}" if ind.get("stop") and c else "")
    if strategy == "trend" and ind.get("entry_level") and c:
        return pct(ind["entry_level"] / c - 1, 1)
    if strategy == "meanrev" and ind.get("rsi") is not None:
        return "RSI " + num(ind["rsi"], 0)
    return "–"


def cmd_signals(ctx, args):
    lines = ["🎯 <b>Abstand zum nächsten Signal</b>", "Trend: fehlender Anstieg bis zum Ausbruch · Mean Reversion: RSI (Kauf unter 30)", ""]
    groups = {}  # Wallets mit gleicher Strategie und gleichen Parametern haben dieselben Signale
    for a in ctx.accounts():
        st = ctx.states(a["name"])
        parts = " · ".join(f"{coin(sym)} {signal_text(a['strategy'], st[sym])}" for sym in SYMBOLS if sym in st)
        key = (a["strategy"], a["interval"], json.dumps((a["params"] or {}).get("strategy_params"), sort_keys=True), parts)
        groups.setdefault(key, []).append(a["name"])
    for (strategy, interval, _, parts), names in groups.items():
        lines.append(f"<b>{' / '.join(esc(n) for n in names)}</b>\n  {parts or 'noch kein Zustand'}")
    return "\n".join(lines), refresh("/signals")


GROUP_LABEL = {("trend", "4h", ""): "Trend 4h", ("trend", "4h", "4hL"): "Trend 4h lang", ("trend", "1d", "1d"): "Trend 1d", ("meanrev", "4h", ""): "Mean Rev."}


def strategy_groups(ctx):
    """Eine repräsentative Wallet je Strategie-Variante (die mit dem größten Kapital)."""
    groups = {}
    for a in ctx.accounts():
        key = (a["strategy"], a["interval"], json.dumps((a["params"] or {}).get("strategy_params"), sort_keys=True))
        if key not in groups or float(a["start_cash"]) > float(groups[key]["start_cash"]):
            groups[key] = a
    out = []
    for a in groups.values():
        suffix = a["name"].split("-")[0][len(a["strategy"]):]
        out.append((GROUP_LABEL.get((a["strategy"], a["interval"], suffix), f"{a['strategy']} {a['interval']}"), a))
    return sorted(out, key=lambda x: x[0])


def coins_block(ctx) -> str:
    prices, lines = ctx.prices(), []
    held = defaultdict(list)
    for a in ctx.accounts():
        for sym in ctx.broker(a).positions:
            held[sym].append(a["name"])
    groups = strategy_groups(ctx)
    for sym in SYMBOLS:
        p = prices.get(sym, {})
        h = held.get(sym, [])
        sig = " · ".join(f"{label} {signal_text(a['strategy'], ctx.states(a['name']).get(sym, {}))}" for label, a in groups)
        lines.append(f"<b>{coin(sym)}</b> {price(p.get('price'))} ({pct(p.get('change_24h'), 1)})\n"
                     f"  {'gehalten in ' + str(len(h)) + ' Wallet' + ('s' if len(h) != 1 else '') if h else 'nicht gehalten'}\n  {sig}")
    return "\n".join(lines)


def cmd_coins(ctx, args):
    return ("🪙 <b>Je Coin</b>\nKurs (24 h) · gehalten · Abstand zum Kaufsignal je Strategie\n\n" + coins_block(ctx)), refresh("/coins")


def cmd_topics(ctx, args):
    import topics as T
    r, silent = T.routing(ctx.conn), T.silent_topics(ctx.conn)
    ids = {}
    row = ctx.conn.execute("SELECT value FROM control WHERE key='telegram:topics'").fetchone()
    if row:
        ids = json.loads(row["value"])
    lines = ["🗂 <b>Themen und Zuordnung</b>", ""]
    for key, (name, _) in T.TOPICS.items():
        lines.append(f"• <b>{esc(name)}</b> <code>{key}</code>{' 🔕 stumm' if key in silent else ''}{'' if key in ids else ' (noch nicht angelegt)'}")
    lines += ["", "<b>Welche Meldung wohin</b>"] + [f"• {esc(T.ROUTE_LABELS[k])} → {esc(T.TOPICS.get(v, (v,))[0])}" for k, v in r.items()]
    lines += ["", "Ändern: <code>/route warning overview</code>", "Stumm schalten: <code>/route silent trades_big on</code>"]
    return "\n".join(lines), None


def cmd_route(ctx, args):
    import topics as T
    if len(args) == 3 and args[0] == "silent" and args[1] in T.TOPICS and args[2] in ("on", "off"):
        T.set_silent_topic(ctx.conn, args[1], args[2] == "on")
        return cmd_topics(ctx, [])
    if len(args) == 2 and args[0] in T.ROUTE_LABELS and args[1] in T.TOPICS:
        T.set_route(ctx.conn, args[0], args[1])
        return cmd_topics(ctx, [])
    return ("Aufruf: <code>/route art thema</code> oder <code>/route silent thema on|off</code>\nArten: " + ", ".join(f"<code>{k}</code>" for k in T.ROUTE_LABELS)
            + "\nThemen: " + ", ".join(f"<code>{k}</code>" for k in T.TOPICS)), None


def cmd_prices(ctx, args):
    rows_ = [[coin(s), price(p["price"]), pct(p["change_24h"], 2)] for s, p in ctx.prices().items()]
    return "💱 <b>Kurse</b> (Binance, USDT)\n" + table(["Coin", "Kurs", "24 h"], rows_), refresh("/prices")


# ------------------------------------------------------------------ Auswertung
def wallet_stats(ctx, a):
    b = ctx.broker(a)
    start, eq = float(a["start_cash"]), float(b.equity())
    snaps = [float(r["equity"]) for r in ctx.conn.execute("SELECT equity FROM equity_snapshots WHERE account_id=%s ORDER BY ts", (a["id"],)).fetchall()]
    trips = [t for t in ctx.trips(a)]
    ts_ = trade_stats([t["pnl"] for t in trips])
    return b, start, eq, snaps, trips, ts_


def cmd_profit(ctx, args):
    if args:
        a = ctx.resolve(args[0])
        if not a:
            return unknown_wallet(ctx, args[0])
        b, start, eq, snaps, trips, s = wallet_stats(ctx, a)
        unreal = eq - float(b.cash) - sum(float(p.cost) for p in b.positions.values())
        pf = s["profit_factor"]
        lines = [f"💰 <b>{esc(a['name'])}</b> · {STRAT.get(a['strategy'], a['strategy'])} · {a['interval']}",
                 f"Wert {money(eq)} USDT ({pct(eq / start - 1, 2)})",
                 f"Realisiert {signed(float(b.realized_pnl))} · unrealisiert {signed(unreal)}",
                 f"Gebühren {money(float(b.fees_paid))}",
                 "",
                 f"Trades {s['trades']} · Treffer {pct(s['win_rate'], 0, False)}",
                 f"Profit-Faktor {'∞' if pf == float('inf') else num(pf)} · Erwartung {signed(s['expectancy'])} je Trade",
                 f"Ø Gewinn {signed(s['avg_win'])} · Ø Verlust {signed(s['avg_loss'])}",
                 f"Bester {signed(s['best'])} · schlechtester {signed(s['worst'])}",
                 f"Ø Haltedauer {dur(sum(t['hold_days'] for t in trips) / len(trips)) if trips else '–'}",
                 f"Max. Drawdown {pct(-dd) if (dd := max_drawdown(start, snaps + [eq])) else '0,0 %'}",
                 f"Seit {ts(int(a['created_at'].timestamp() * 1000))}"]
        return "\n".join(lines), refresh("/profit " + a["name"])
    rows_ = []
    for a in ctx.accounts():
        b, start, eq, snaps, trips, s = wallet_stats(ctx, a)
        rows_.append([a["name"], pct(eq / start - 1, 2), str(s["trades"]), pct(s["win_rate"], 0, False) if s["win_rate"] is not None else "–"])
    return "💰 <b>Ergebnis je Wallet</b>\n" + table(["Wallet", "Rendite", "Tr.", "Treffer"], rows_) + "\nDetails: /profit &lt;wallet&gt;", refresh("/profit")


def period_key(ms, unit):
    d = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date()
    if unit == "day":
        return d.isoformat(), d.strftime("%d.%m.")
    if unit == "week":
        y, w, _ = d.isocalendar()
        return f"{y}-{w:02d}", f"KW {w}"
    return d.strftime("%Y-%m"), d.strftime("%m/%Y")


def cmd_period(ctx, args, unit):
    defaults = {"day": 7, "week": 8, "month": 6}
    n = defaults[unit]
    wallet = None
    for x in args:
        if x.isdigit():
            n = max(1, min(int(x), 60))
        else:
            wallet = ctx.resolve(x)
            if not wallet:
                return unknown_wallet(ctx, x)
    accts = [wallet] if wallet else ctx.accounts()
    now = now_ms()
    keys = []
    step = {"day": 864e5, "week": 7 * 864e5, "month": 30.4 * 864e5}[unit]
    for i in range(n * 2 + 2):  # genügend Zeitpunkte, um n verschiedene Perioden zu finden
        k = period_key(int(now - i * step), unit)
        if k not in keys:
            keys.append(k)
    keys = keys[:n + 1]  # eine Periode mehr als Vergleichsbasis für die älteste Zeile
    pnl, cnt = defaultdict(float), defaultdict(int)
    for t in ctx.trips(wallet):
        k = period_key(t["closed"], unit)[0]
        pnl[k] += t["pnl"]; cnt[k] += 1
    # Gesamtwert aller gewählten Wallets zum Periodenende (letzter Snapshot, sonst Startkapital)
    ends = {}
    for a in accts:
        vals = ctx.conn.execute("SELECT ts, equity FROM equity_snapshots WHERE account_id=%s ORDER BY ts", (a["id"],)).fetchall()
        for k, _ in keys:
            last = float(a["start_cash"])
            for v in vals:
                if period_key(v["ts"], unit)[0] <= k:
                    last = float(v["equity"])
            ends[k] = ends.get(k, 0.0) + last
    total_start = sum(float(a["start_cash"]) for a in accts)
    rows_ = []
    for i, (k, label) in enumerate(keys[:n]):
        prev = ends.get(keys[i + 1][0], total_start) if i + 1 < len(keys) else total_start
        rows_.append([label, str(cnt[k]), signed(pnl[k]), pct(ends[k] / prev - 1, 2) if prev else "–"])
    title = {"day": "Täglich", "week": "Wöchentlich", "month": "Monatlich"}[unit]
    scope = esc(wallet["name"]) if wallet else "alle Wallets"
    return (f"📅 <b>{title}</b> · {scope}\n" + table(["Zeitraum", "Tr.", "Realisiert", "Wert"], rows_)
            + "\nRealisiert = Summe abgeschlossener Trades (USDT) · Wert = Veränderung des Gesamtwerts"), refresh(f"/{PERIOD_CMD[unit]} " + " ".join(args))


def cmd_performance(ctx, args):
    a = ctx.resolve(args[0]) if args else None
    if args and not a:
        return unknown_wallet(ctx, args[0])
    by = defaultdict(list)
    for t in ctx.trips(a):
        by[t["symbol"]].append(t)
    if not by:
        return "📈 Noch keine abgeschlossenen Trades.", None
    rows_ = [[coin(s), str(len(ts_)), pct(sum(t["pnl"] > 0 for t in ts_) / len(ts_), 0, False), signed(sum(t["pnl"] for t in ts_))]
             for s, ts_ in sorted(by.items(), key=lambda kv: -sum(t["pnl"] for t in kv[1]))]
    return f"📈 <b>Ergebnis je Coin</b> · {esc(a['name']) if a else 'alle Wallets'}\n" + table(["Coin", "Tr.", "Treffer", "USDT"], rows_), refresh("/performance " + " ".join(args))


def cmd_stats(ctx, args):
    a = ctx.resolve(args[0]) if args else None
    if args and not a:
        return unknown_wallet(ctx, args[0])
    by = defaultdict(list)
    for t in ctx.trips(a):
        by[t["exit_reason"]].append(t)
    if not by:
        return "📊 Noch keine abgeschlossenen Trades.", None
    rows_ = [[REASONS.get(r, r), str(len(ts_)), pct(sum(t["pnl"] > 0 for t in ts_) / len(ts_), 0, False), pct(sum(t["pnl_pct"] for t in ts_) / len(ts_)),
              dur(sum(t["hold_days"] for t in ts_) / len(ts_))] for r, ts_ in by.items()]
    return f"📊 <b>Ergebnis je Ausstiegsgrund</b> · {esc(a['name']) if a else 'alle Wallets'}\n" + table(["Grund", "Tr.", "Treffer", "Ø %", "Ø Dauer"], rows_), refresh("/stats " + " ".join(args))


def cmd_trades(ctx, args):
    n, a = 10, None
    for x in args:
        if x.isdigit():
            n = max(1, min(int(x), 50))
        else:
            a = ctx.resolve(x)
            if not a:
                return unknown_wallet(ctx, x)
    trips = ctx.trips(a)[-n:][::-1]
    if not trips:
        return "🧾 Noch keine abgeschlossenen Trades.", None
    lines = [f"🧾 <b>Letzte {len(trips)} Trades</b> · {esc(a['name']) if a else 'alle Wallets'}", ""]
    for t in trips:
        lines.append(f"{trend_icon(t['pnl'])} <b>{coin(t['symbol'])}</b> {esc(t['wallet'])}\n   {signed(t['pnl'])} USDT ({pct(t['pnl_pct'])}) · {REASONS.get(t['exit_reason'], t['exit_reason'])} · {dur(t['hold_days'])} · {ts(t['closed'])}")
    return "\n".join(lines), refresh("/trades " + " ".join(args))


# ------------------------------------------------------------------ System
def cmd_system(ctx, args, redis=None):
    now = time.time()
    lines = ["🖥 <b>System</b>"]
    if redis is not None:
        for svc in ("market-data", "bots", "master", "telegram"):
            v = redis.get(f"heartbeat:{svc}")
            age = now - float(v) if v else None
            lines.append(f"{'🟢' if age is not None and age < 60 else '🔴'} {svc}: {'kein Signal' if age is None else f'vor {int(age)} s'}")
    last = ctx.conn.execute("SELECT max(close_time) AS t FROM candles WHERE interval='15m'").fetchone()["t"]
    age = now - last / 1000 if last else None
    lines.append(f"{'🟢' if age is not None and age < 1500 else '🔴'} Kursdaten: letzte 15-min-Kerze vor {int(age / 60) if age else '?'} min")
    ctrl = ctx.control()
    lines.append("")
    lines.append("🛑 <b>Kill-Switch AKTIV</b>" if "kill" in ctrl else "Kill-Switch: aus")
    paused = [k.split(":", 1)[1] for k in ctrl if k.startswith("pause:")]
    lines.append("Pausiert: " + (", ".join(esc(p) for p in paused) if paused else "keine"))
    return "\n".join(lines), refresh("/system")


def cmd_events(ctx, args):
    n = max(1, min(int(args[0]), 40)) if args and args[0].isdigit() else 10
    ev = ctx.conn.execute("SELECT ts, level, source, wallet, message FROM events ORDER BY id DESC LIMIT %s", (n,)).fetchall()
    icon = {"info": "ℹ️", "warn": "⚠️", "error": "❌"}
    lines = [f"📜 <b>Letzte {len(ev)} Ereignisse</b>", ""] + [f"{icon.get(e['level'], '•')} {ts(e['ts'])} {esc(e['source'])}{' · ' + esc(e['wallet']) if e['wallet'] else ''}\n   {esc(e['message'])}" for e in ev]
    return "\n".join(lines), refresh("/events " + " ".join(args))


def cmd_config(ctx, args):
    if not args:
        return "Welche Wallet?", {"inline_keyboard": rows([btn(a["name"], "c|" + a["name"]) for a in ctx.accounts()])}
    a = ctx.resolve(args[0])
    if not a:
        return unknown_wallet(ctx, args[0])
    p = a["params"] or {}
    lines = [f"⚙️ <b>{esc(a['name'])}</b> · {STRAT.get(a['strategy'], a['strategy'])} · {a['interval']}-Kerzen", ""]
    for k, v in (p.get("strategy_params") or {}).items():
        d = PARAMS.get(f"{a['strategy']}.{k}", {})
        lines.append(f"• <b>{esc(d.get('label', k))}</b> <code>{esc(k)}</code> = {esc(v)} {esc(d.get('unit', ''))}")
    lines += ["", f"• Positionsgröße {pct(p.get('position_fraction'), 0, False)} des Werts je Coin",
              f"• Gebühr {pct(float(p.get('fee_rate', 0)), 2, False)} · Slippage {esc(p.get('slippage_bps'))} bp",
              f"• Coins {', '.join(coin(s) for s in p.get('symbols', []))}", "", "Erklärungen zu allen Parametern: Dashboard → Glossar"]
    return "\n".join(lines), None


# ------------------------------------------------------------------ Steuerung
def set_control(conn, key, reason):
    conn.execute("INSERT INTO control (key, value, reason) VALUES (%s,'1',%s) ON CONFLICT (key) DO UPDATE SET value='1', reason=EXCLUDED.reason, updated_at=now()", (key, reason))


def wallet_buttons(ctx, prefix, with_all=True):
    b = [btn(a["name"], f"{prefix}|{a['name']}") for a in ctx.accounts()]
    if with_all:
        b.append(btn("Alle", f"{prefix}|*"))
    return {"inline_keyboard": rows(b)}


def do_pause(ctx, target, pause: bool, who="Telegram"):
    names = [a["name"] for a in ctx.accounts()] if target in ("*", "all", "alle") else [target]
    for n in names:
        if pause:
            set_control(ctx.conn, f"pause:{n}", f"Über {who} pausiert")
        else:
            ctx.conn.execute("DELETE FROM control WHERE key=%s", (f"pause:{n}",))
        add_event(ctx.conn, "telegram", "warn" if pause else "info", ("Manuell pausiert (keine neuen Einstiege)" if pause else "Manuell freigegeben") + f" über {who}", n)
    ctx.conn.commit()
    what = "alle Wallets" if len(names) > 1 else names[0]
    return (f"⏸ <b>{esc(what)} pausiert.</b> Keine neuen Einstiege; offene Positionen werden weiter von der Strategie verwaltet." if pause
            else f"▶️ <b>{esc(what)} freigegeben.</b> Neue Einstiege sind wieder erlaubt." + (" Achtung: Der Kill-Switch ist noch aktiv (/unkill)." if "kill" in ctx.control() else ""))


def cmd_pause(ctx, args, pause=True):
    if not args:
        return ("Welche Wallet pausieren?" if pause else "Welche Wallet freigeben?"), wallet_buttons(ctx, "p" if pause else "u")
    target = args[0]
    if target.lower() not in ("all", "alle", "*"):
        a = ctx.resolve(target)
        if not a:
            return unknown_wallet(ctx, target)
        target = a["name"]
    return do_pause(ctx, target, pause), None


def open_positions(ctx):
    out = []
    for a in ctx.accounts():
        b = ctx.broker(a)
        for sym, p in b.positions.items():
            val, cost = float(p.qty) * float(b.prices[sym]), float(p.cost)
            out.append((a["name"], sym, val / cost - 1))
    return out


def cmd_forceexit(ctx, args):
    pos = open_positions(ctx)
    if args:
        a = ctx.resolve(args[0])
        if not a:
            return unknown_wallet(ctx, args[0])
        pos = [p for p in pos if p[0] == a["name"]]
    if not pos:
        return "📭 Keine offene Position, die verkauft werden könnte.", None
    b = [btn(f"{w} · {coin(s)} ({pct(r)})", f"fx|{w}|{s}") for w, s, r in pos]
    return "Welche Position soll sofort zum aktuellen Kurs verkauft werden?", {"inline_keyboard": rows(b, 1) + [[btn("Abbrechen", "no")]]}


def confirm_forceexit(wallet, sym):
    return (f"⚠️ <b>{esc(wallet)} · {coin(sym)}</b> jetzt verkaufen?\nDer Verkauf läuft zum letzten 15-Minuten-Kurs, mit Gebühr und Slippage.",
            {"inline_keyboard": [[btn("✅ Ja, verkaufen", f"fxy|{wallet}|{sym}"), btn("Abbrechen", "no")]]})


def do_forceexit(ctx, wallet, sym):
    set_control(ctx.conn, f"forceexit:{wallet}:{sym}", "Über Telegram")
    add_event(ctx.conn, "telegram", "warn", f"Manueller Ausstieg angefordert: {coin(sym)}", wallet)
    ctx.conn.commit()
    return f"⏳ Verkauf von <b>{coin(sym)}</b> in {esc(wallet)} angefordert. Die Bestätigung kommt gleich als Verkaufsmeldung."


def cmd_kill(ctx, args):
    if "kill" in ctx.control():
        return "🛑 Der Kill-Switch ist bereits aktiv. Aufheben mit /unkill.", None
    return ("🛑 <b>Kill-Switch auslösen?</b>\nAlle Positionen aller Wallets werden sofort verkauft und es gibt keine neuen Einstiege, bis du /unkill sendest.",
            {"inline_keyboard": [[btn("🛑 Ja, alles verkaufen", "ky"), btn("Abbrechen", "no")]]})


def do_kill(ctx):
    set_control(ctx.conn, "kill", "Über Telegram ausgelöst")
    add_event(ctx.conn, "telegram", "error", "KILL-SWITCH über Telegram ausgelöst: alle Positionen werden geschlossen")
    ctx.conn.commit()
    return "🛑 <b>Kill-Switch aktiv.</b> Alle Positionen werden geschlossen. Aufheben mit /unkill."


def cmd_unkill(ctx, args):
    if "kill" not in ctx.control():
        return "Der Kill-Switch ist nicht aktiv.", None
    ctx.conn.execute("DELETE FROM control WHERE key='kill'")
    add_event(ctx.conn, "telegram", "info", "Kill-Switch über Telegram aufgehoben")
    ctx.conn.commit()
    return "✅ Kill-Switch aufgehoben. Einzeln pausierte Wallets bleiben pausiert (/system).", None


# ------------------------------------------------------------------ Benachrichtigungen
def notify_settings(conn) -> dict:
    row = conn.execute("SELECT value FROM control WHERE key='telegram:notify'").fetchone()
    try:
        return {**NOTIFY_DEFAULT, **(json.loads(row["value"]) if row else {})}
    except (ValueError, TypeError):
        return dict(NOTIFY_DEFAULT)


def cmd_notify(ctx, args):
    cur = notify_settings(ctx.conn)
    if len(args) >= 2 and args[0] in NOTIFY_TYPES and args[1] in ("on", "silent", "off"):
        cur[args[0]] = args[1]
        ctx.conn.execute("INSERT INTO control (key, value) VALUES ('telegram:notify', %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()", (json.dumps(cur),))
        ctx.conn.commit()
    elif args:
        return "Aufruf: <code>/notify typ on|silent|off</code>\nTypen: " + ", ".join(f"<code>{k}</code>" for k in NOTIFY_TYPES), None
    icon = {"on": "🔔", "silent": "🔕", "off": "⛔"}
    lines = ["<b>Benachrichtigungen</b>", ""] + [f"{icon[cur[k]]} {v} <code>{k}</code>: {cur[k]}" for k, v in NOTIFY_TYPES.items()]
    lines += ["", "🔔 on = mit Ton · 🔕 silent = ohne Ton · ⛔ off = keine Nachricht", "Ändern z. B. <code>/notify info off</code>"]
    return "\n".join(lines), None


COMMANDS = {
    "start": None, "help": None, "status": cmd_status, "wallets": cmd_wallets, "balance": cmd_wallets, "count": cmd_count,
    "signals": cmd_signals, "prices": cmd_prices, "profit": cmd_profit, "daily": lambda c, a: cmd_period(c, a, "day"),
    "weekly": lambda c, a: cmd_period(c, a, "week"), "monthly": lambda c, a: cmd_period(c, a, "month"), "performance": cmd_performance,
    "stats": cmd_stats, "trades": cmd_trades, "events": cmd_events, "logs": cmd_events, "config": cmd_config,
    "pause": lambda c, a: cmd_pause(c, a, True), "stopentry": lambda c, a: cmd_pause(c, a, True), "resume": lambda c, a: cmd_pause(c, a, False),
    "forceexit": cmd_forceexit, "fx": cmd_forceexit, "kill": cmd_kill, "unkill": cmd_unkill, "notify": cmd_notify,
    "coins": cmd_coins, "topics": cmd_topics, "route": cmd_route,
}
MENU = [("status", "Offene Positionen"), ("wallets", "Wallets mit Wert und Rendite"), ("profit", "Gewinn und Kennzahlen"), ("daily", "Ergebnis je Tag"),
        ("weekly", "Ergebnis je Woche"), ("monthly", "Ergebnis je Monat"), ("trades", "Letzte Trades"), ("performance", "Ergebnis je Coin"),
        ("stats", "Ergebnis je Ausstiegsgrund"), ("coins", "Überblick je Coin"), ("signals", "Abstand zum Kaufsignal"), ("count", "Belegte Plätze"), ("prices", "Kurse"),
        ("pause", "Wallet pausieren"), ("resume", "Wallet freigeben"), ("forceexit", "Position verkaufen"), ("kill", "Kill-Switch"),
        ("unkill", "Kill-Switch aufheben"), ("system", "Systemzustand"), ("events", "Letzte Ereignisse"), ("config", "Parameter einer Wallet"),
        ("report", "Tagesbericht senden"), ("notify", "Benachrichtigungen"), ("topics", "Themen und Zuordnung"), ("route", "Zuordnung ändern"), ("help", "Hilfe")]
