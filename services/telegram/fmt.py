"""Formatierung für Telegram (HTML-Modus): deutsche Zahlen, schmale Tabellen fürs Handy."""
import datetime as dt
import html


def esc(x) -> str:
    return html.escape(str(x), quote=False)


def num(x, d=2) -> str:
    if x is None:
        return "–"
    s = f"{x:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def money(x, d=None) -> str:
    if x is None:
        return "–"
    return num(x, d if d is not None else (0 if abs(x) >= 1000 else 2))


def price(x) -> str:
    return "–" if x is None else num(x, 4 if x < 1 else 3 if x < 100 else 2)


def pct(x, d=1, sign=True) -> str:
    if x is None:
        return "–"
    return ("+" if sign and x > 0 else "") + num(x * 100, d) + " %"


def signed(x, d=2) -> str:
    return "–" if x is None else ("+" if x > 0 else "") + num(x, d)


def coin(sym: str) -> str:
    return sym.replace("USDT", "")


def dur(days: float | None) -> str:
    if days is None:
        return "–"
    mins = int(round(days * 1440))
    d, rest = divmod(mins, 1440)
    hh, mm = divmod(rest, 60)
    if d:
        return f"{d} T {hh} h"
    return f"{hh} h {mm} min" if hh else f"{mm} min"


def ts(ms: int | None) -> str:
    if not ms:
        return "–"
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).astimezone(LOCAL).strftime("%d.%m. %H:%M")


try:
    from zoneinfo import ZoneInfo
    LOCAL = ZoneInfo("Europe/Berlin")
except Exception:  # pragma: no cover
    LOCAL = dt.timezone.utc


def table(headers: list[str], rows: list[list], align: str | None = None) -> str:
    """Monospace-Tabelle in <pre>. align: je Spalte 'l' oder 'r' (Standard: erste links, Rest rechts)."""
    align = align or "l" + "r" * (len(headers) - 1)
    cells = [[str(c) for c in r] for r in rows]
    w = [max([len(headers[i])] + [len(r[i]) for r in cells]) for i in range(len(headers))]
    fmt_row = lambda r: " ".join(c.ljust(w[i]) if align[i] == "l" else c.rjust(w[i]) for i, c in enumerate(r)).rstrip()
    lines = [fmt_row(headers)] + [fmt_row(r) for r in cells]
    return "<pre>" + esc("\n".join(lines)) + "</pre>"


def trend_icon(x) -> str:
    return "🟢" if x and x > 0 else "🔴" if x and x < 0 else "⚪"
