from abc import ABC, abstractmethod
from decimal import Decimal

from .models import Order, OrderType, Side


class Broker(ABC):
    """Einzige Schnittstelle, über die Bots handeln. Ein echter Broker implementiert dasselbe Interface."""

    @abstractmethod
    def place_order(self, symbol: str, side: Side, qty: Decimal, type: OrderType = OrderType.MARKET,
                    limit_price: Decimal | None = None, ts: int = 0, bot: str = "") -> Order: ...

    @abstractmethod
    def cancel_order(self, order_id: int) -> bool: ...

    @abstractmethod
    def position_qty(self, symbol: str) -> Decimal: ...

    @abstractmethod
    def equity(self) -> Decimal: ...

    @abstractmethod
    def available_cash(self) -> Decimal: ...

    @abstractmethod
    def affordable_qty(self, symbol: str, notional) -> Decimal: ...

    @abstractmethod
    def set_price(self, symbol: str, price) -> None: ...

    @abstractmethod
    def on_candle(self, symbol: str, high, low, close, ts: int = 0) -> list: ...
