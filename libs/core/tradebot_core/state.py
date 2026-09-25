"""Gemeinsame Datenbank-Helfer für API, Master-Bot und Bot-Service (erwarten eine psycopg-Verbindung mit dict_row)."""
import time
from decimal import Decimal as D

from .models import Fill, Side
from .paper import PaperBroker


def now_ms() -> int:
    return int(time.time() * 1000)


def latest_prices(conn, symbols: list[str]) -> dict[str, dict]:
    rows = conn.execute("SELECT DISTINCT ON (symbol) symbol, close, open_time, close_time FROM candles "
                        "WHERE interval='15m' AND symbol = ANY(%s) ORDER BY symbol, open_time DESC", (symbols,)).fetchall()
    out = {}
    for r in rows:
        prev = conn.execute("SELECT close FROM candles WHERE symbol=%s AND interval='15m' AND open_time <= %s "
                            "ORDER BY open_time DESC LIMIT 1", (r["symbol"], r["open_time"] - 86_400_000)).fetchone()
        out[r["symbol"]] = {"price": r["close"], "close_time": r["close_time"],
                            "change_24h": (r["close"] / prev["close"] - 1) if prev else None}
    return out


def broker_for(conn, account: dict, prices: dict[str, dict]) -> PaperBroker:
    fills = conn.execute("SELECT order_id, symbol, side, qty, price, fee, realized_pnl, ts, bot, maker, reason FROM fills "
                         "WHERE account_id=%s ORDER BY ts, id", (account["id"],)).fetchall()
    b = PaperBroker(account["name"], account["start_cash"])
    b.restore([Fill(f["order_id"], f["symbol"], Side(f["side"]), f["qty"], f["price"], f["fee"], f["realized_pnl"],
                    f["ts"], f["bot"], f["maker"], f["reason"]) for f in fills])
    for s, p in prices.items():
        b.set_price(s, D(str(p["price"])))
    return b


def add_event(conn, source: str, level: str, message: str, wallet: str | None = None) -> None:
    """Protokolleintrag für das Dashboard (level: info | warn | error)."""
    conn.execute("INSERT INTO events (ts, level, source, wallet, message) VALUES (%s,%s,%s,%s,%s)",
                 (now_ms(), level, source, wallet, message))


def round_trips(fill_rows) -> list[dict]:
    """Abgeschlossene Trades (Long, Durchschnittseinstand) aus der zeitlich sortierten Fill-Folge (dict-Zeilen)."""
    open_: dict[str, dict] = {}
    out = []
    for x in fill_rows:
        o = open_.get(x["symbol"])
        if x["side"] == "buy":
            if not o:
                o = open_[x["symbol"]] = {"symbol": x["symbol"], "opened": x["ts"], "qty": 0.0, "cost": 0.0, "fees": 0.0, "entry_reason": x.get("reason", "")}
            o["qty"] += float(x["qty"]); o["cost"] += float(x["qty"] * x["price"]); o["fees"] += float(x["fee"])
        elif o:
            o["fees"] += float(x["fee"])
            entry = o["cost"] / o["qty"]
            out.append({"symbol": x["symbol"], "opened": o["opened"], "closed": x["ts"], "qty": float(x["qty"]), "entry": entry,
                        "exit": float(x["price"]), "pnl": float(x["realized_pnl"]), "pnl_pct": float(x["price"]) / entry - 1,
                        "hold_days": (x["ts"] - o["opened"]) / 86_400_000, "bot": x.get("bot", ""), "fees": o["fees"],
                        "entry_reason": o["entry_reason"], "exit_reason": x.get("reason", ""), "wallet": x.get("wallet")})
            if float(x["qty"]) >= o["qty"] - 1e-12:
                open_.pop(x["symbol"], None)
            else:
                o["cost"] *= 1 - float(x["qty"]) / o["qty"]; o["qty"] -= float(x["qty"])
    return out


REASONS = {"breakout": "Ausbruch", "oversold": "überverkauft", "channel_exit": "Kanal-Ausstieg", "stop_loss": "Stop-Loss",
           "mean_reached": "Mittelwert erreicht", "time_stop": "Zeitstopp", "force_exit": "manuell", "kill_switch": "Kill-Switch", "": "–"}
