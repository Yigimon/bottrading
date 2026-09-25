"""Erklärungen aller Parameter und Kennzahlen (Deutsch). Eine Quelle für Dashboard, Konfiguration und Analyse-Labor.

Jeder Parameter: label (Anzeigename), unit, what (was er ist), effect (was passiert, wenn man ihn erhöht),
range (sinnvoller Bereich für das Labor: min, max, step).
"""

PARAMS = {
    # ---------------------------------------------------------------- Trend-Ausbruch
    "trend.entry_n": {
        "label": "Einstiegskanal", "unit": "Kerzen",
        "what": "Wie viele vergangene Kerzen für den Ausbruch betrachtet werden. Gekauft wird, wenn der Schlusskurs höher liegt als das höchste Hoch dieser Kerzen (Donchian-Kanal).",
        "effect": "Größer: seltenere, dafür bedeutendere Ausbrüche, weniger Fehlsignale und Gebühren, aber späterer Einstieg. Kleiner: früher dabei, aber viel mehr Fehlausbrüche.",
        "range": [10, 200, 5]},
    "trend.exit_n": {
        "label": "Ausstiegskanal", "unit": "Kerzen",
        "what": "Verkauft wird, wenn der Schlusskurs unter das tiefste Tief dieser Anzahl vergangener Kerzen fällt.",
        "effect": "Größer: die Position hält länger durch Rücksetzer, gibt aber beim Trendende mehr Gewinn zurück. Kleiner: schnellerer Ausstieg, dafür häufiger zu früh raus.",
        "range": [5, 100, 5]},
    "trend.atr_n": {
        "label": "ATR-Periode", "unit": "Kerzen",
        "what": "Zeitraum für die Average True Range (ATR), die durchschnittliche Schwankungsbreite einer Kerze. Sie bestimmt den Abstand des Stops.",
        "effect": "Größer: der ATR reagiert träger auf Schwankungsänderungen. Kleiner: der Stop passt sich schneller an aktuelle Volatilität an.",
        "range": [5, 50, 1]},
    "trend.atr_mult": {
        "label": "Stop-Abstand", "unit": "× ATR",
        "what": "Wie viele ATR der mitlaufende Stop unter dem Schlusskurs liegt. Der Stop wird nur nach oben nachgezogen und sichert so Gewinne.",
        "effect": "Größer: mehr Luft für normale Schwankungen, weniger Ausstopp-Fehler, aber größere Verluste pro Trade. Kleiner: enger Stop, kleine Verluste, aber häufiges Ausstoppen kurz vor der Fortsetzung.",
        "range": [1.0, 8.0, 0.5]},
    "trend.trend_n": {
        "label": "Trendfilter (EMA)", "unit": "Kerzen (0 = aus)",
        "what": "Optionaler Filter: Ausbrüche werden nur gekauft, wenn der Kurs über dem exponentiellen gleitenden Durchschnitt dieser Länge liegt.",
        "effect": "An: weniger Einstiege in Abwärtsmärkten. Kostet in der Regel einige gute Ausbrüche am Beginn eines neuen Trends.",
        "range": [0, 300, 50]},
    "trend.vol_target": {
        "label": "Risiko je Trade", "unit": "Anteil des Wallet-Werts (0 = aus)",
        "what": "Volatilitätsbasierte Positionsgröße: Die Position wird so bemessen, dass ein Treffer des Stops ungefähr diesen Anteil des Wallet-Werts kostet. Die feste Positionsgröße gilt dann als Obergrenze.",
        "effect": "Größer: größere Positionen, höhere Rendite und höhere Schwankung. Bei 0 wird immer die feste Positionsgröße genutzt, egal wie stark der Coin schwankt.",
        "range": [0.0, 0.05, 0.005]},

    # ---------------------------------------------------------------- Mean Reversion
    "meanrev.rsi_n": {
        "label": "RSI-Periode", "unit": "Kerzen",
        "what": "Zeitraum des Relative-Stärke-Index. Der RSI misst von 0 bis 100, wie stark die jüngsten Kursbewegungen nach oben oder unten gingen.",
        "effect": "Größer: glatterer RSI, extreme Werte werden seltener. Kleiner: reagiert schneller, erzeugt mehr Signale.",
        "range": [2, 30, 1]},
    "meanrev.rsi_entry": {
        "label": "RSI-Kaufschwelle", "unit": "RSI-Punkte",
        "what": "Gekauft wird nur, wenn der RSI unter diesem Wert liegt (überverkauft).",
        "effect": "Größer (z. B. 35): mehr Trades, aber schwächere Rücksetzer. Kleiner (z. B. 20): nur tiefe Einbrüche, sehr selten.",
        "range": [10, 45, 1]},
    "meanrev.bb_n": {
        "label": "Bollinger-Länge", "unit": "Kerzen",
        "what": "Anzahl Kerzen für den gleitenden Durchschnitt (mittleres Band) und die Standardabweichung der Bollinger-Bänder.",
        "effect": "Größer: der Mittelwert, zu dem der Kurs zurückkehren soll, ist weiter weg; Ziele sind größer, Trades dauern länger.",
        "range": [10, 60, 1]},
    "meanrev.bb_k": {
        "label": "Bandbreite", "unit": "Standardabweichungen",
        "what": "Wie weit das untere Band unter dem Durchschnitt liegt. Gekauft wird nur unter dem unteren Band.",
        "effect": "Größer: nur extreme Ausreißer lösen aus (selten, oft stärkere Erholung). Kleiner: häufigere, schwächere Signale.",
        "range": [1.0, 3.5, 0.1]},
    "meanrev.trend_n": {
        "label": "Trendfilter (EMA)", "unit": "Kerzen",
        "what": "Länge des übergeordneten Trend-Durchschnitts. Bei aktivem Filter wird nur über diesem EMA gekauft.",
        "effect": "Größer: der Filter ist langfristiger und träger.",
        "range": [50, 400, 10]},
    "meanrev.trend_filter": {
        "label": "Trendfilter aktiv", "unit": "ja/nein",
        "what": "Wenn aktiv, kauft die Strategie Rücksetzer nur im übergeordneten Aufwärtstrend.",
        "effect": "Aus: deutlich mehr Trades, aber auch Käufe in fallende Märkte hinein ('ins fallende Messer greifen').",
        "range": None},
    "meanrev.stop_pct": {
        "label": "Stop-Loss", "unit": "Anteil unter Einstieg",
        "what": "Fester Stop unter dem Einstiegskurs, z. B. 0,04 = 4 %.",
        "effect": "Größer: mehr Geduld, aber größere Einzelverluste. Kleiner: Rücksetzer, die noch weiterlaufen, führen schnell zum Verlust.",
        "range": [0.01, 0.15, 0.005]},
    "meanrev.max_hold": {
        "label": "Maximale Haltedauer", "unit": "Kerzen",
        "what": "Zeitstopp: Hat sich der Kurs nach dieser Anzahl Kerzen nicht erholt, wird verkauft.",
        "effect": "Größer: gibt der Erholung mehr Zeit, bindet aber Kapital. Kleiner: schneller wieder frei, erwischt aber späte Erholungen nicht.",
        "range": [6, 200, 2]},

    # ---------------------------------------------------------------- Wallet / Broker
    "wallet.position_fraction": {
        "label": "Positionsgröße", "unit": "Anteil des Wallet-Werts je Coin",
        "what": "Wie viel des aktuellen Wallet-Werts höchstens pro Coin investiert wird. Bei 3 Coins und 0,33 kann das Wallet voll investiert sein.",
        "effect": "Größer: höhere Rendite und höhere Verluste (mehr Hebel auf die Strategie). Kleiner: ruhiger, mehr Bargeld.",
        "range": [0.05, 1.0, 0.01]},
    "wallet.fee_rate": {
        "label": "Gebühr je Order", "unit": "Anteil des Ordervolumens",
        "what": "Handelsgebühr pro Kauf und Verkauf. Binance Spot: 0,1 % (0,075 % bei Zahlung mit BNB).",
        "effect": "Jeder Round-Trip kostet zweimal die Gebühr. Strategien mit vielen Trades reagieren sehr empfindlich darauf.",
        "range": [0.0, 0.003, 0.00025]},
    "wallet.slippage_bps": {
        "label": "Slippage", "unit": "Basispunkte (1 bp = 0,01 %)",
        "what": "Angenommener Preisnachteil bei Marktorders, weil man über den Spread und ins Orderbuch hinein kauft.",
        "effect": "Wie die Gebühr: senkt jeden Trade um diesen Betrag. Für BTC/ETH/SOL sind 2 bis 10 bp realistisch.",
        "range": [0, 50, 1]},
    "wallet.symbols": {"label": "Handelbare Coins", "unit": "", "what": "Die Paare, die dieses Wallet handelt (je Coin eine eigene Strategie-Instanz).", "effect": "", "range": None},
    "wallet.interval": {"label": "Kerzenintervall", "unit": "", "what": "Zeitrahmen einer Kerze. Signale entstehen nur bei Kerzenschluss.", "effect": "Kürzer: mehr Signale und mehr Gebühren, mehr Rauschen. Länger: wenige, langsame Signale.", "range": None},
    "wallet.long_only": {"label": "Richtung", "unit": "", "what": "Nur Kaufpositionen (Spot, kein Hebel, keine Leerverkäufe).", "effect": "", "range": None},
    "wallet.execution": {"label": "Ausführung", "unit": "", "what": "Wie aus einem Signal eine Order wird.", "effect": "", "range": None},
}

INDICATORS = {
    "entry_level": ("Ausbruchsniveau", "Höchstes Hoch des Einstiegskanals. Schließt der Kurs darüber, wird gekauft."),
    "exit_level": ("Kanal-Ausstieg", "Tiefstes Tief des Ausstiegskanals. Schließt der Kurs darunter, wird verkauft."),
    "atr": ("ATR", "Durchschnittliche Schwankungsbreite einer Kerze, in USDT."),
    "stop": ("Aktueller Stop", "Kurs, bei dem die offene Position verkauft wird."),
    "trend_ema": ("EMA-Trendfilter", "Gleitender Durchschnitt für den Trendfilter."),
    "rsi": ("RSI", "Relative Stärke von 0 bis 100. Unter 30 gilt als überverkauft."),
    "bb_mid": ("Bollinger Mitte", "Gleitender Durchschnitt; dort wird verkauft (Ziel der Rückkehr)."),
    "bb_lower": ("Bollinger unten", "Untere Bandgrenze; darunter ist ein Kauf möglich."),
    "held_candles": ("Gehaltene Kerzen", "Wie lange die aktuelle Position schon läuft."),
}

METRICS = {
    "return": ("Rendite", "Veränderung des Wallet-Werts gegenüber dem Startkapital, nach allen Kosten."),
    "max_drawdown": ("Max. Drawdown", "Größter Rückgang vom bisherigen Höchststand bis zum folgenden Tiefpunkt. Zeigt den schlimmsten Verlust, den man ausgehalten hätte."),
    "sharpe": ("Sharpe-Ratio", "Rendite im Verhältnis zur Schwankung (annualisiert, auf Tagesbasis). Über 1 ist gut, unter 0 verliert die Strategie."),
    "calmar": ("Calmar-Ratio", "Jahresrendite geteilt durch maximalen Drawdown. Wie viel Rendite pro Einheit schlimmstem Verlust."),
    "cagr": ("Rendite p. a.", "Durchschnittliche jährliche Wachstumsrate (CAGR)."),
    "volatility": ("Volatilität p. a.", "Annualisierte Standardabweichung der Tagesrenditen."),
    "win_rate": ("Trefferquote", "Anteil der abgeschlossenen Trades mit Gewinn nach Gebühren. Trendfolger haben oft unter 50 % und verdienen trotzdem, weil Gewinner größer sind."),
    "profit_factor": ("Profit-Faktor", "Summe aller Gewinne geteilt durch Summe aller Verluste. Über 1 = profitabel, über 1,5 = robust."),
    "expectancy": ("Erwartungswert", "Durchschnittliches Ergebnis pro Trade in USDT, nach Gebühren."),
    "exposure": ("Investitionsgrad", "Anteil der Zeit bzw. des Kapitals, der in Coins investiert ist."),
    "fees": ("Gebühren", "Summe aller gezahlten Handelsgebühren."),
    "trades": ("Trades", "Anzahl abgeschlossener Round-Trips (Kauf und Verkauf)."),
    "avg_hold": ("Ø Haltedauer", "Durchschnittliche Dauer eines Trades."),
    "bh_return": ("Buy & Hold", "Rendite, wenn man am Anfang gleichgewichtet BTC, ETH und SOL gekauft und nichts mehr getan hätte (mit denselben Kosten)."),
    "walkforward": ("Walk-Forward", "Test gegen Überanpassung: Parameter werden nur auf vergangenen Daten gewählt und dann auf dem folgenden, ungesehenen Zeitraum getestet."),
}


def strategy_param_docs(strategy: str) -> dict:
    return {k.split(".", 1)[1]: v for k, v in PARAMS.items() if k.startswith(strategy + ".")}


def wallet_param_docs() -> dict:
    return {k.split(".", 1)[1]: v for k, v in PARAMS.items() if k.startswith("wallet.")}
