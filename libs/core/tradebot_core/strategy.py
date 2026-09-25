"""Strategie-Interface und die Start-Strategien (nur Long, Spot).

Eine Strategie-Instanz gehört genau zu einem Symbol. Sie sieht nur abgeschlossene Kerzen und
liefert am Kerzenende ein Signal. Die Ausführung übernimmt der BotRunner (zum nächsten Open).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .indicators import ATR, EMA, RSI, Window


@dataclass(frozen=True)
class Candle:
    symbol: str
    interval: str
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class Signal:
    action: str  # "enter" | "exit"
    reason: str = ""


class Strategy(ABC):
    name = ""
    vol_target = 0.0  # 0 = feste Positionsgröße
    stop: float | None = None  # aktueller Stop-Loss-Preis; der Runner prüft ihn innerhalb jeder Kerze

    @abstractmethod
    def on_candle(self, c: Candle, in_position: bool) -> Signal | None: ...

    def indicators(self) -> dict:
        """Aktuelle Indikatorwerte (Stand der letzten Kerze) für das Dashboard."""
        return {}


class TrendBreakout(Strategy):
    """Donchian-Ausbruch: Einstieg über dem Hoch der letzten entry_n Kerzen, Ausstieg unter dem Tief
    der letzten exit_n Kerzen oder am mitlaufenden ATR-Stop."""

    name = "trend"

    def __init__(self, entry_n=55, exit_n=20, atr_n=14, atr_mult=3.0, trend_n=0, vol_target=0.0):
        self.highs, self.lows, self.atr, self.atr_mult = Window(entry_n), Window(exit_n), ATR(atr_n), atr_mult
        self.vol_target = vol_target  # >0: Positionsgröße so, dass ein Stop-Treffer ca. diesen Anteil des Werts kostet
        self.trend = EMA(trend_n) if trend_n else None  # optionaler Trendfilter: Einstieg nur über dem EMA
        self.stop = None

    def on_candle(self, c, in_position):
        signal = None
        atr = self.atr.update(c.high, c.low, c.close)
        ema = self.trend.update(c.close) if self.trend else None
        if not in_position:
            self.stop = None
            trend_ok = self.trend is None or (self.trend.ready and c.close > ema)
            # Vergleich nur mit vorherigen Kerzen (aktuelle wird erst danach ins Fenster geschoben)
            if trend_ok and self.highs.full and atr is not None and c.close > self.highs.max:
                self.stop = c.close - self.atr_mult * atr
                signal = Signal("enter", "breakout")
        else:
            if self.lows.full and c.close < self.lows.min:
                signal = Signal("exit", "channel_exit")
            elif atr is not None:
                self.stop = max(self.stop or 0.0, c.close - self.atr_mult * atr)  # Trailing-Stop
        self.highs.push(c.high)
        self.lows.push(c.low)
        return signal

    def indicators(self):
        return {"entry_level": self.highs.max if self.highs.full else None, "exit_level": self.lows.min if self.lows.full else None,
                "atr": self.atr.value, "stop": self.stop,
                "trend_ema": self.trend.value if self.trend and self.trend.ready else None}


class MeanReversion(Strategy):
    """Dip kaufen: RSI überverkauft und Kurs unter dem unteren Bollinger-Band (optional nur im Aufwärtstrend).
    Ausstieg am mittleren Band, nach max_hold Kerzen oder am festen Stop."""

    name = "meanrev"

    def __init__(self, rsi_n=14, rsi_entry=30.0, bb_n=20, bb_k=2.0, trend_n=200, trend_filter=True,
                 stop_pct=0.04, max_hold=48):
        self.rsi, self.bb, self.trend = RSI(rsi_n), Window(bb_n), EMA(trend_n)
        self.rsi_entry, self.bb_k, self.trend_filter = rsi_entry, bb_k, trend_filter
        self.stop_pct, self.max_hold = stop_pct, max_hold
        self.stop, self.held = None, 0

    def on_candle(self, c, in_position):
        signal = None
        rsi = self.rsi.update(c.close)
        self.bb.push(c.close)
        ema = self.trend.update(c.close)
        if not in_position:
            self.stop, self.held = None, 0
            if rsi is not None and self.bb.full and (not self.trend_filter or (self.trend.ready and c.close > ema)):
                lower = self.bb.mean - self.bb_k * self.bb.std
                if rsi < self.rsi_entry and c.close < lower:
                    self.stop = c.close * (1 - self.stop_pct)
                    signal = Signal("enter", "oversold")
        else:
            self.held += 1
            if c.close >= self.bb.mean:
                signal = Signal("exit", "mean_reached")
            elif self.held >= self.max_hold:
                signal = Signal("exit", "time_stop")
        return signal

    def indicators(self):
        full = self.bb.full
        return {"rsi": self.rsi.value, "bb_mid": self.bb.mean if full else None,
                "bb_lower": self.bb.mean - self.bb_k * self.bb.std if full else None,
                "trend_ema": self.trend.value if self.trend.ready else None, "stop": self.stop, "held_candles": self.held}


STRATEGIES = {"trend": TrendBreakout, "meanrev": MeanReversion}

# Kleine Parameter-Raster für die Walk-Forward-Optimierung
GRIDS = {
    "trend": {"entry_n": [30, 55, 100, 150], "exit_n": [10, 20, 40], "atr_mult": [3.0, 4.0, 5.0], "trend_n": [0, 200]},
    "meanrev": {"rsi_entry": [25.0, 30.0, 35.0], "bb_k": [1.5, 2.0, 2.5], "stop_pct": [0.03, 0.05]},
}
