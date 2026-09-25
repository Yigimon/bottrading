"""BotRunner: verbindet Strategien mit einem Broker. Wird im Backtest und im Live-Paper-Betrieb identisch genutzt.

Kein Look-ahead: Ein Signal entsteht am Ende einer Kerze und wird zum Open der NÄCHSTEN Kerze
ausgeführt (live entspricht das dem Kurs direkt nach Kerzenschluss).
"""
from collections.abc import Callable
from decimal import Decimal as D

from .broker import Broker
from .models import OrderType, Side
from .strategy import Candle, Signal, Strategy


class BotRunner:
    def __init__(self, broker: Broker, factory: Callable[[], Strategy], symbols: list[str],
                 position_fraction: float = 0.33, name: str = "bot", immediate: bool = False):
        # immediate=True (Live): Signale sofort zum aktuellen Kurs ausführen statt zum Open der nächsten Kerze
        self.broker, self.name, self.immediate = broker, name, immediate
        self.position_fraction = D(str(position_fraction))
        self.strategies = {s: factory() for s in symbols}
        self.pending: dict[str, Signal] = {}
        self.entries_enabled = True  # False = pausiert: keine neuen Einstiege, Ausstiege bleiben erlaubt
        self.last_signal: dict[str, dict] = {}

    def on_candle(self, c: Candle) -> None:
        b, sym, st = self.broker, c.symbol, self.strategies[c.symbol]

        sig = self.pending.pop(sym, None)  # 1. Signal der Vorkerze zum Open ausführen
        if sig:
            b.set_price(sym, c.open)
            self._execute(sig, c)

        qty = b.position_qty(sym)  # 2. Stop-Loss innerhalb der Kerze (bei Lücke zum Open)
        if qty > 0 and st.stop is not None and c.low <= st.stop:
            b.set_price(sym, min(st.stop, c.open))
            b.place_order(sym, Side.SELL, qty, OrderType.MARKET, ts=c.close_time, bot=self.name, reason="stop_loss")

        b.on_candle(sym, c.high, c.low, c.close, c.close_time)  # 3. Kurs und Limit-Orders aktualisieren

        sig = st.on_candle(c, in_position=b.position_qty(sym) > 0)  # 4. Strategie fragen
        if sig:
            self.last_signal[sym] = {"action": sig.action, "reason": sig.reason, "time": c.close_time}
            if self.immediate:
                b.set_price(sym, c.close)
                self._execute(sig, c)
            else:
                self.pending[sym] = sig

    def _execute(self, sig: Signal, c: Candle) -> None:
        b, sym = self.broker, c.symbol
        held = b.position_qty(sym)
        if sig.action == "enter" and held == 0:
            if not self.entries_enabled:
                return
            notional = self.position_fraction * b.equity()
            st = self.strategies[sym]
            price = b.prices.get(sym)
            if st.vol_target and st.stop is not None and price and D(str(st.stop)) < price:
                risk_per_unit = price - D(str(st.stop))  # Verlust je Einheit bis zum Stop
                notional = min(notional, D(str(st.vol_target)) * b.equity() / risk_per_unit * price)
            notional = min(notional, b.available_cash())
            qty = b.affordable_qty(sym, notional)
            b.place_order(sym, Side.BUY, qty, OrderType.MARKET, ts=c.close_time, bot=self.name, reason=sig.reason)
        elif sig.action == "exit" and held > 0:
            b.place_order(sym, Side.SELL, held, OrderType.MARKET, ts=c.close_time, bot=self.name, reason=sig.reason)
