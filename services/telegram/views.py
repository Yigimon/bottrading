"""Gestaltung aller Telegram-Nachrichten. Aufbau jeder Nachricht:

  Symbol + Titel (fett)          ← worum geht es
  eine Kernzahl (fett)           ← das Wichtigste
  <blockquote> Details </blockquote>  ← abgesetzt, farbiger Balken
  Wallet · Zeit (kursiv, klein)  ← Herkunft

Keine breiten Tabellen: Telegram zeigt auf dem Handy nur ~35 Zeichen Monospace je Zeile.
"""
import re

from fmt import coin, dur, esc, num, pct, price, signed, ts
from tradebot_core.state import REASONS

SEP = " · "
STRATEGY_LABEL = {"trend": "Trend 4h", "trend4hL": "Trend 4h lang", "trend1d": "Trend 1d", "meanrev": "Mean Reversion"}
STRATEGY_ORDER = ["trend4hL", "trend1d", "trend", "meanrev"]
STRATEGY_SHORT = {"trend": "4h", "trend4hL": "4h lang", "trend1d": "1d", "meanrev": "MeanRev"}
REASON_SHORT = {"breakout": "Ausbruch", "oversold": "überverkauft", "channel_exit": "Kanal-Ausstieg", "stop_loss": "Stop",
                "mean_reached": "Mittelwert", "time_stop": "Zeitstopp", "force_exit": "manuell", "kill_switch": "Kill-Switch", "": "–"}
REASON_TEXT = {"breakout": "Ausbruch über das Kanal-Hoch", "oversold": "überverkauft (RSI und Bollinger)", "channel_exit": "Schluss unter dem Kanal-Tief",
               "stop_loss": "Stop erreicht", "mean_reached": "Mittelwert erreicht", "time_stop": "maximale Haltedauer", "force_exit": "manuell verkauft",
               "kill_switch": "Kill-Switch", "": "–"}


def usd(x, d=None) -> str:
    if x is None:
        return "–"
    return num(x, d if d is not None else (0 if abs(x) >= 1000 else 2)) + " $"


def usd_signed(x) -> str:
    return "–" if x is None else ("+" if x > 0 else "−" if x < 0 else "") + usd(abs(x))


def pct_s(x, d=1) -> str:
    """Prozent mit echtem Minuszeichen."""
    return "–" if x is None else pct(x, d).replace("-", "−")


def dot(x) -> str:
    return "🟢" if x and x > 0 else "🔴" if x and x < 0 else "⚪"


def bar(frac, n=5) -> str:
    """Balken für 'Nähe zum Signal' (1 = Signal erreicht)."""
    k = max(0, min(n, round((frac or 0) * n)))
    return "▰" * k + "▱" * (n - k)


def wallet_parts(name: str):
    """'trend4hL-10000' -> ('trend4hL', 10000)"""
    base, _, cap = name.rpartition("-")
    return base, int(cap) if cap.isdigit() else 0


def strategy_short(name: str) -> str:
    return STRATEGY_SHORT.get(wallet_parts(name)[0], wallet_parts(name)[0])


def plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def strategy_label(name: str) -> str:
    return STRATEGY_LABEL.get(wallet_parts(name)[0], wallet_parts(name)[0])


def size_label(name: str) -> str:
    cap = wallet_parts(name)[1]
    return "Kleinkonto" if cap < 1000 else f"{num(cap, 0)} $"


def footer(*parts) -> str:
    return "<i>" + esc(SEP.join(p for p in parts if p)) + "</i>"


def quote(lines) -> str:
    lines = [l for l in lines if l]
    return "<blockquote>" + "\n".join(lines) + "</blockquote>" if lines else ""


def join(*blocks) -> str:
    return "\n".join(b for b in blocks if b)


# ------------------------------------------------------------------ Trades
def entry(wallet, sym, qty, price_, fee, equity, stop, reason, when_ms) -> str:
    stake = qty * price_
    return join(
        f"🟦 <b>Kauf · {coin(sym)}</b>",
        f"<b>{usd(price_)}</b>{SEP}Einsatz {usd(stake)} ({pct(stake / equity, 0, False)})",
        quote([f"Stop {usd(stop)}{SEP}{pct_s(stop / price_ - 1)}" if stop else "",
               f"Signal: {esc(REASON_TEXT.get(reason, reason))}",
               f"Menge {num(qty, 5)}{SEP}Gebühr {usd(fee)}"]),
        footer(strategy_label(wallet), ts(when_ms)))


def exit_(wallet, sym, pnl, ratio, entry_px, exit_px, hold_days, reason, equity, start, when_ms) -> str:
    icon = "🚀" if ratio is not None and ratio >= 0.05 else "✅" if pnl >= 0 else "🛑" if reason == "stop_loss" else "🔻"
    head = f"{icon} <b>Verkauf · {coin(sym)}</b>" + (f"   <b>{pct_s(ratio)}</b>" if ratio is not None else "")
    return join(
        head,
        f"<b>{usd_signed(pnl)}</b> nach Gebühren",
        quote([f"{usd(entry_px)} → {usd(exit_px)}{SEP}{dur(hold_days)}" if entry_px else "",
               f"Grund: {esc(REASON_TEXT.get(reason, reason))}",
               f"Wallet jetzt {usd(equity)}{SEP}{pct_s(equity / start - 1, 2)}"]),
        footer(strategy_label(wallet), ts(when_ms)))


# ------------------------------------------------------------------ Ereignisse in Klartext
def event(e) -> str | None:
    """Übersetzt ein Protokoll-Ereignis in eine lesbare Meldung. None = nicht senden (Doppelung oder unwichtig)."""
    msg, w, src = e["message"], e["wallet"], e["source"]
    if src == "master" and msg.startswith("Tagesbericht"):
        return None  # eigener Tagesbericht des Telegram-Bots ist ausführlicher
    if src == "bots" and msg.startswith(("Neue Einstiege pausiert", "Neue Einstiege wieder aktiv", "KAUF ", "VERKAUF ")):
        return None  # Bestätigungen des Bot-Service; die Ursache (Master, Dashboard) wird schon gemeldet
    if m := re.match(r"Auto-Pause: (Drawdown|Tagesverlust) (-?[\d.]+)% [<>] -?(\d+)%", msg):
        kind, val, lim = m.groups()
        return join(f"⏸️ <b>Auto-Pause · {esc(w)}</b>",
                    f"{kind} <b>{num(abs(float(val)), 1)} %</b> über der Grenze von {lim} %",
                    quote(["Keine neuen Einstiege mehr. Offene Positionen laufen mit ihren Stops normal weiter.",
                           f"Freigeben: /resume {esc(w)}"]),
                    footer("Master-Bot", ts(e["ts"])))
    if m := re.match(r"Schwache Kennzahlen: Profit-Faktor ([\d.]+) bei (\d+) Trades", msg):
        pf, n = m.groups()
        return join(f"📉 <b>Schwache Kennzahlen · {esc(w)}</b>",
                    f"Profit-Faktor <b>{num(float(pf), 2)}</b> nach {n} Trades",
                    quote(["Die Verluste sind größer als die Gewinne. Nur ein Hinweis, der Bot handelt weiter.", f"Details: /profit {esc(w)}"]),
                    footer("Master-Bot", ts(e["ts"])))
    if m := re.match(r"Dienst '([\w-]+)' meldet sich nicht", msg):
        return service_down(m.group(1), e["ts"], "Master-Bot")
    if m := re.match(r"Dienst '([\w-]+)' läuft wieder", msg):
        return service_up(m.group(1), e["ts"])
    if m := re.match(r"Kursdaten veraltet \(([\d.]+) s\)", msg):
        return join("📡 <b>Kursdaten veraltet</b>", f"Letzte Kerze vor <b>{int(float(m.group(1)) / 60)} min</b>",
                    quote(["Ohne frische Kurse treffen die Bots keine Entscheidungen.", "Zustand: /system"]), footer("Master-Bot", ts(e["ts"])))
    if msg.startswith("Kursdaten sind wieder aktuell"):
        return join("📡 <b>Kursdaten wieder aktuell</b>", footer("Master-Bot", ts(e["ts"])))
    if msg.startswith("KILL-SWITCH"):
        return join("🛑 <b>Kill-Switch ausgelöst</b>", "Alle Positionen werden verkauft",
                    quote(["Keine neuen Einstiege, bis der Kill-Switch aufgehoben wird.", "Aufheben: /unkill"]), footer(src.capitalize(), ts(e["ts"])))
    if msg.startswith("Kill-Switch: alle Positionen geschlossen"):
        return join("🛑 <b>Kill-Switch: alles verkauft</b>", quote(["Alle Wallets sind jetzt ohne Positionen.", "Übersicht: /wallets"]), footer("Bot-Service", ts(e["ts"])))
    if msg.startswith("Kill-Switch aufgehoben"):
        return join("▶️ <b>Kill-Switch aufgehoben</b>", quote(["Handel wieder erlaubt. Einzeln pausierte Wallets bleiben pausiert."]), footer(src.capitalize(), ts(e["ts"])))
    if msg.startswith("Manuell pausiert"):
        return join(f"⏸️ <b>Pausiert · {esc(w)}</b>", quote(["Keine neuen Einstiege. Offene Positionen laufen normal weiter.", f"Freigeben: /resume {esc(w)}"]),
                    footer(f"über {src.capitalize()}", ts(e["ts"])))
    if msg.startswith("Manuell freigegeben"):
        return join(f"▶️ <b>Freigegeben · {esc(w)}</b>", footer(f"über {src.capitalize()}", ts(e["ts"])))
    if m := re.match(r"(\d+) verpasste Kerzen nachverarbeitet", msg):
        return join(f"🔁 <b>Nachgeholt · {esc(w)}</b>", f"{m.group(1)} Kerzen aus einer Pause des Dienstes verarbeitet", footer("Bot-Service", ts(e["ts"])))
    if msg.startswith("Manueller Ausstieg: keine offene Position"):
        return join(f"ℹ️ <b>Nichts zu verkaufen · {esc(w)}</b>", quote(["Die Position war schon geschlossen."]), footer("Bot-Service", ts(e["ts"])))
    if msg.startswith("Manueller Ausstieg"):
        return None  # die Verkaufsmeldung selbst kommt im Trades-Thema
    if "gestartet" in msg:
        name = {"bots": "Bot-Service", "master": "Master-Bot", "telegram": "Telegram-Bot"}.get(src, src)
        return join(f"🔄 <b>{esc(name)} gestartet</b>", footer(ts(e["ts"])))
    icon = {"error": "❌", "warn": "⚠️"}.get(e["level"], "ℹ️")
    return join(f"{icon} <b>{esc(w or src.capitalize())}</b>", esc(msg), footer(src.capitalize(), ts(e["ts"])))


def service_down(svc, when_ms, source="Telegram-Bot") -> str:
    name = {"bots": "Bot-Service", "market-data": "Kursdaten-Dienst", "master": "Master-Bot"}.get(svc, svc)
    return join(f"🔴 <b>{esc(name)} ausgefallen</b>", "Seit über 2 Minuten kein Lebenszeichen",
                quote(["Docker startet den Dienst normalerweise selbst neu. Kommt keine Entwarnung, bitte prüfen.", "Zustand: /system"]),
                footer(source, ts(when_ms)))


def service_up(svc, when_ms) -> str:
    name = {"bots": "Bot-Service", "market-data": "Kursdaten-Dienst", "master": "Master-Bot"}.get(svc, svc)
    return join(f"🟢 <b>{esc(name)} läuft wieder</b>", footer(ts(when_ms)))


# ------------------------------------------------------------------ Übersichten
def grouped_wallets(accts):
    """[(Strategie-Label, [Konten nach Kapital absteigend])] in fester Reihenfolge."""
    groups = {}
    for a in accts:
        groups.setdefault(wallet_parts(a["name"])[0], []).append(a)
    order = sorted(groups, key=lambda k: STRATEGY_ORDER.index(k) if k in STRATEGY_ORDER else 99)
    return [(STRATEGY_LABEL.get(k, k), sorted(groups[k], key=lambda a: -float(a["start_cash"]))) for k in order]
