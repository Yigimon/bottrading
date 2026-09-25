from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    OPEN = "open"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass
class Order:
    id: int
    symbol: str
    side: Side
    type: OrderType
    qty: Decimal
    limit_price: Decimal | None = None
    bot: str = ""
    status: OrderStatus = OrderStatus.OPEN
    reject_reason: str = ""
    reason: str = ""  # Signalgrund, z. B. breakout, stop_loss, channel_exit, force_exit


@dataclass(frozen=True)
class Fill:
    order_id: int
    symbol: str
    side: Side
    qty: Decimal
    price: Decimal
    fee: Decimal
    realized_pnl: Decimal  # nach Gebühren; bei Käufen 0
    ts: int  # Millisekunden UTC
    bot: str = ""
    maker: bool = False
    reason: str = ""


@dataclass
class Position:
    symbol: str
    qty: Decimal
    cost: Decimal  # Einstandswert inkl. Kaufgebühren

    @property
    def avg_cost(self) -> Decimal:
        return self.cost / self.qty if self.qty else Decimal(0)
