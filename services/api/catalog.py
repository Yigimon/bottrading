"""Beschreibung aller Strategien für die Dashboard-Seite "Strategien" (Texte in Deutsch)."""

COSTS_CRYPTO = "0,1 % Gebühr (Binance Spot) und 5 Basispunkte Slippage je Seite"

# Ergebnisse aus services/backtest/research.py (Stand 25.09.2026): 4 Jahre, erste Hälfte (H1, 09/2022–09/2024), zweite Hälfte (H2, 09/2024–09/2026)
FINDINGS_1D = [
    "4 Jahre: +148 % bei 26 % max. Drawdown, Sharpe 0,90, 41 Trades. Buy & Hold: +228 % bei 63 % Drawdown.",
    "Die Rendite stammt fast ganz aus der ersten Hälfte (H1 +95 %). In der zweiten Hälfte (Seitwärtsmarkt) −9 %, während Buy & Hold +3 % bei 63 % Drawdown erzielte.",
    "Parameter-Varianten (Kanal 40/70, Ausstieg 10/30, Stop 2/4 ATR) liegen alle bei Sharpe 0,83–0,95: Es gibt keine robust bessere Einstellung, deshalb bleiben die Standardwerte.",
    "Ein engerer Stop (2 ATR) halbiert den Drawdown (14 %) bei weniger Rendite (+106 %) und gleichem Sharpe. Das ist eine Frage der Risikoneigung, kein Vorteil.",
    "Volatilitätsbasierte Positionsgröße (vol_target) senkt Rendite und Drawdown im gleichen Verhältnis, der Sharpe bleibt unverändert.",
    "Unempfindlich gegenüber Gebühren: bei 0,15 % statt 0,1 % nur 3 Prozentpunkte weniger Rendite.",
]
FINDINGS_4H = [
    "Mit den Standardkanälen (55/20) sehr viele Trades (223 in 4 Jahren) und Gebühren von fast einem Viertel des Startkapitals. Sharpe nur 0,60.",
    "Längere Kanäle sind robust besser, siehe Variante 'lange Kanäle'. Diese Wallet läuft als Vergleich mit den Standardwerten weiter.",
    "Auf 1h-Kerzen war die Strategie im Backtest klar negativ, deshalb wird 1h nicht live gefahren.",
]
FINDINGS_4H_LONG = [
    "Ergebnis der Schwachstellen-Analyse vom 25.09.2026: Einstiegskanal 150, Ausstiegskanal 40, Stop 4 ATR.",
    "4 Jahre: +116 % (Standard 4h: +64 %), Sharpe 0,86 (0,60), 107 statt 223 Trades, Gebühren 1.470 statt 2.363 USDT.",
    "Robust: alle Nachbar-Varianten (Einstieg 120–180, Ausstieg 30–60, Stop 4–5 ATR) liegen bei Sharpe 0,80–0,92. Ein Plateau, kein Zufallstreffer.",
    "Auch mit 0,15 % Gebühr (+108 %) und mit 100 USDT Kapital (+116 %) praktisch gleich.",
    "Schwäche bleibt: max. Drawdown 34 %, in der zweiten Hälfte (Seitwärtsmarkt) nur −4 % bis +8 % je nach Variante.",
]


def trend_card(interval: str, variant: str = "") -> dict:
    daily = interval == "1d"
    long_ = variant == "L"
    return {
        "backtest_key": "trend", "interval": interval, "wallet_prefix": "trend" + ("1d" if daily else "4hL" if long_ else ""),
        "params": {"entry_n": 150, "exit_n": 40, "atr_mult": 4.0} if long_ else {}, "family": "Krypto", "market": "Binance Spot, BTC/ETH/SOL",
        "title": f"Trend-Ausbruch ({'Tageskerzen' if daily else '4-Stunden-Kerzen, lange Kanäle' if long_ else '4-Stunden-Kerzen'})",
        "summary": "Folgt Ausbrüchen: kauft, wenn der Kurs das Hoch der letzten Wochen überschreitet, und bleibt investiert, bis der Trend bricht.",
        "how_it_works": [
            "Die Strategie wartet, bis der Schlusskurs höher liegt als jedes Hoch der letzten 55 Kerzen (Donchian-Kanal). Das gilt als Beginn eines Aufwärtstrends.",
            "Danach hält sie die Position, solange der Trend trägt. Ein mitlaufender Stop (3 × ATR unter dem Schlusskurs, zieht nur nach oben) sichert Gewinne ab.",
            "Sie verdient an wenigen großen Bewegungen und zahlt in Seitwärtsphasen mit vielen kleinen Verlusten für Fehlausbrüche. Die Trefferquote ist deshalb niedrig, ein einzelner Gewinner ist groß.",
        ],
        "entry": ["Schlusskurs über dem höchsten Hoch der letzten 55 Kerzen (ohne die aktuelle Kerze)", "Optional: nur über dem EMA (Trendfilter, standardmäßig aus)"],
        "exit": ["Schlusskurs unter dem tiefsten Tief der letzten 20 Kerzen", "Oder: mitlaufender ATR-Stop (Schlusskurs − 3 × ATR(14)), wird bei Berührung innerhalb der Kerze ausgeführt (bei Kurslücke zum Open)"],
        "sizing": "33 % des aktuellen Wallet-Werts je Position, maximal 3 Positionen (BTC, ETH, SOL). Nur Long, kein Hebel.",
        "execution": f"Signal bei Kerzenschluss, Marktorder sofort zum aktuellen Kurs. Kosten: {COSTS_CRYPTO}.",
        "parameters": [
            {"name": "entry_n", "value": 55, "meaning": "Kanallänge für den Einstieg (Kerzen)"},
            {"name": "exit_n", "value": 20, "meaning": "Kanallänge für den Ausstieg (Kerzen)"},
            {"name": "atr_n", "value": 14, "meaning": "Periode des ATR (durchschnittliche Schwankung)"},
            {"name": "atr_mult", "value": 3.0, "meaning": "Abstand des mitlaufenden Stops in ATR"},
            {"name": "trend_n", "value": 0, "meaning": "EMA-Trendfilter, 0 = aus"},
        ],
        "suited_for": "Anhaltende Aufwärtstrends mit klaren Ausbrüchen. Bei Spot wird nur die Aufwärtsseite gehandelt.",
        "weaknesses": ["Viele Fehlausbrüche und Kleinverluste im Seitwärtsmarkt", "Gibt beim Trendwechsel einen Teil der Gewinne zurück",
                       "Einstieg erst nach bereits erfolgter Bewegung", "Gebühren sind ein großer Kostenfaktor" + (" (4h: über 200 Trades in 4 Jahren)" if not daily else "")],
        "findings": (FINDINGS_1D if daily else FINDINGS_4H_LONG if long_ else FINDINGS_4H),
    }


CARDS = {
    "trend:1d": trend_card("1d"),
    "trend:4hL": trend_card("4h", "L"),
    "trend:4h": trend_card("4h"),
    "meanrev:4h": {
        "backtest_key": "meanrev", "interval": "4h", "wallet_prefix": "meanrev", "params": {}, "family": "Krypto", "market": "Binance Spot, BTC/ETH/SOL",
        "title": "Mean Reversion (4-Stunden-Kerzen)",
        "summary": "Kauft überverkaufte Rücksetzer im Aufwärtstrend und verkauft, sobald der Kurs zum Durchschnitt zurückkehrt.",
        "how_it_works": [
            "Die Idee: Nach einem starken, kurzfristigen Absturz schwingt der Kurs oft wieder Richtung Mittelwert zurück.",
            "Die Strategie kauft nur, wenn drei Dinge zusammenkommen: der RSI ist überverkauft, der Kurs liegt unter dem unteren Bollinger-Band und der übergeordnete Trend zeigt nach oben (Kurs über EMA 200).",
            "Der Trendfilter verhindert, dass sie in einen fallenden Markt hineinkauft. Der Preis dafür: Sie handelt sehr selten.",
        ],
        "entry": ["RSI(14) unter 30", "Schlusskurs unter dem unteren Bollinger-Band (20 Kerzen, 2 Standardabweichungen)", "Schlusskurs über dem EMA(200) (Trendfilter)"],
        "exit": ["Schlusskurs erreicht das mittlere Band (SMA 20)", "Oder: Zeitstopp nach 48 Kerzen", "Oder: fester Stop 4 % unter dem Einstieg"],
        "sizing": "33 % des aktuellen Wallet-Werts je Position, maximal 3 Positionen. Nur Long, kein Hebel.",
        "execution": f"Signal bei Kerzenschluss, Marktorder sofort zum aktuellen Kurs. Kosten: {COSTS_CRYPTO}.",
        "parameters": [
            {"name": "rsi_n / rsi_entry", "value": "14 / 30", "meaning": "RSI-Periode und Schwelle für 'überverkauft'"},
            {"name": "bb_n / bb_k", "value": "20 / 2,0", "meaning": "Bollinger-Band: Länge und Breite in Standardabweichungen"},
            {"name": "trend_n / trend_filter", "value": "200 / an", "meaning": "Einstieg nur über dem EMA 200"},
            {"name": "stop_pct", "value": "4 %", "meaning": "Fester Stop unter dem Einstiegskurs"},
            {"name": "max_hold", "value": 48, "meaning": "Zeitstopp in Kerzen"},
        ],
        "suited_for": "Seitwärts- und leicht steigende Märkte mit kurzen Rücksetzern.",
        "weaknesses": ["Sehr wenige Trades: die Statistik ist dünn und wenig aussagekräftig", "Kann in starken Abwärtsbewegungen 'ins fallende Messer' kaufen",
                       "Bleibt in Bärenphasen komplett draußen (durch den Trendfilter)"],
        "findings": ["Im Backtest nur 19 Trades in 4 Jahren (+3 %), kaum besser als Bargeld, dafür sehr geringer Drawdown (8 %).",
                     "Erste Hälfte +10 %, zweite Hälfte −6 %: kein stabiler Vorteil.",
                     "Jede Lockerung der Filter macht sie klar negativ: ohne Trendfilter −55 %, RSI-Schwelle 35 −13 %, auf 1h-Kerzen −77 %. In diesen Märkten hat Mean Reversion keinen Vorteil.",
                     "Läuft als Kontrollgruppe weiter; eine Ausweitung ist nicht zu empfehlen."],
    },
}

STRATEGY_CATALOG = CARDS
