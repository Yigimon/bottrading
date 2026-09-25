"""Virtueller Broker mit realistischen Kosten.

Annahmen (bewusst konservativ, damit Paper-Ergebnisse nicht zu gut ausfallen):
- Gebühr: fee_rate auf das Ordervolumen (Binance Spot Standard 0,1 %), wird in der Quote-Währung
  abgezogen (Binance zieht sie real in der gekauften Währung, der Nettoeffekt ist nahezu gleich).
- Market-Orders füllen zum letzten Preis plus/minus Slippage (Standard 5 bp).
- Limit-Orders füllen erst, wenn der Kurs das Limit durchhandelt (strikt), zum Limitpreis, ohne Slippage.
- Kein Leerverkauf, kein Hebel. Einstandswert enthält Kaufgebühren, realisierter PnL ist netto.
"""
from decimal import Decimal

from .broker import Broker
from .models import Fill, Order, OrderStatus, OrderType, Position, Side
from .rules import DEFAULT_RULES, SymbolRules

D = Decimal
Q8 = D("0.00000001")


class PaperBroker(Broker):
    def __init__(self, name: str, start_cash, rules: dict[str, SymbolRules] | None = None,
                 fee_rate="0.001", slippage_bps="5"):
        self.name = name
        self.start_cash = D(start_cash)
        self.cash = self.start_cash
        self.rules = DEFAULT_RULES if rules is None else rules
        self.fee_rate = D(fee_rate)
        self.slippage = D(slippage_bps) / D(10000)
        self.positions: dict[str, Position] = {}
        self.prices: dict[str, D] = {}
        self.orders: dict[int, Order] = {}
        self._open: dict[int, Order] = {}  # nur offene Limit-Orders (schneller Zugriff pro Kerze)
        self.fills: list[Fill] = []
        self.realized_pnl = D(0)
        self.fees_paid = D(0)
        self.reserved_cash = D(0)
        self._reserved_qty: dict[str, D] = {}
        self._next_id = 1

    # ---- Abfragen ----
    def position_qty(self, symbol: str) -> D:
        p = self.positions.get(symbol)
        return p.qty if p else D(0)

    def available_cash(self) -> D:
        return self.cash - self.reserved_cash

    def equity(self) -> D:
        return self.cash + sum((p.qty * self.prices.get(p.symbol, D(0)) for p in self.positions.values()), D(0))

    def affordable_qty(self, symbol: str, notional) -> D:
        """Größte Menge, die für ~notional (inkl. Gebühr und Slippage) gekauft werden kann."""
        price = self.prices[symbol] * (1 + self.slippage)
        return self.rules[symbol].round_qty(D(notional) / (price * (1 + self.fee_rate)))

    def snapshot(self) -> dict:
        return {
            "name": self.name, "cash": self.cash, "equity": self.equity(),
            "realized_pnl": self.realized_pnl, "fees_paid": self.fees_paid,
            "positions": {s: (p.qty, p.avg_cost) for s, p in self.positions.items()},
        }

    # ---- Orders ----
    def place_order(self, symbol, side, qty, type=OrderType.MARKET, limit_price=None, ts=0, bot="") -> Order:
        order = Order(self._next_id, symbol, side, type, D(qty), None if limit_price is None else D(limit_price), bot)
        self._next_id += 1
        self.orders[order.id] = order
        rules = self.rules.get(symbol)
        if rules is None:
            return self._reject(order, "unknown_symbol")
        order.qty = rules.round_qty(order.qty)
        if order.qty < rules.min_qty:
            return self._reject(order, "qty_below_min")
        last = self.prices.get(symbol)
        if last is None:
            return self._reject(order, "no_price")
        if type == OrderType.LIMIT:
            if order.limit_price is None or order.limit_price <= 0:
                return self._reject(order, "invalid_limit_price")
            order.limit_price = rules.round_price(order.limit_price)

        # Ausführungspreis bei sofortiger Ausführung (taker)
        if side == Side.BUY:
            taker_price = last * (1 + self.slippage)
        else:
            taker_price = last * (1 - self.slippage)
        immediate = type == OrderType.MARKET
        exec_price = taker_price
        if type == OrderType.LIMIT:
            if side == Side.BUY and order.limit_price >= taker_price:
                immediate, exec_price = True, taker_price
            elif side == Side.SELL and order.limit_price <= taker_price:
                immediate, exec_price = True, taker_price
        check_price = exec_price if immediate else order.limit_price
        if order.qty * check_price < rules.min_notional:
            return self._reject(order, "below_min_notional")

        # Deckungsprüfung (offene Limit-Orders sind reserviert)
        if side == Side.BUY:
            need = order.qty * check_price * (1 + self.fee_rate)
            if need > self.available_cash():
                return self._reject(order, "insufficient_cash")
        else:
            if order.qty > self.position_qty(symbol) - self._reserved_qty.get(symbol, D(0)):
                return self._reject(order, "insufficient_position")

        if immediate:
            self._fill(order, exec_price.quantize(Q8), ts, maker=False)
        else:
            self._open[order.id] = order
            if side == Side.BUY:
                self.reserved_cash += order.qty * order.limit_price * (1 + self.fee_rate)
            else:
                self._reserved_qty[symbol] = self._reserved_qty.get(symbol, D(0)) + order.qty
        return order

    def cancel_order(self, order_id: int) -> bool:
        order = self.orders.get(order_id)
        if order is None or order.status != OrderStatus.OPEN:
            return False
        self._release(order)
        self._open.pop(order_id, None)
        order.status = OrderStatus.CANCELLED
        return True

    # ---- Marktdaten ----
    def on_candle(self, symbol: str, high, low, close, ts: int = 0) -> list[Fill]:
        """Kurs aktualisieren und offene Limit-Orders prüfen. Gibt neue Fills zurück."""
        high, low = D(str(high)), D(str(low))
        self.prices[symbol] = D(str(close))
        new = []
        for order in [o for o in self._open.values() if o.symbol == symbol]:
            crossed = low < order.limit_price if order.side == Side.BUY else high > order.limit_price
            if crossed:
                self._release(order)
                del self._open[order.id]
                new.append(self._fill(order, order.limit_price, ts, maker=True))
        return new

    def set_price(self, symbol: str, price) -> None:
        self.prices[symbol] = D(str(price))

    # ---- intern ----
    def _reject(self, order: Order, reason: str) -> Order:
        order.status, order.reject_reason = OrderStatus.REJECTED, reason
        return order

    def _release(self, order: Order) -> None:
        if order.side == Side.BUY:
            self.reserved_cash -= order.qty * order.limit_price * (1 + self.fee_rate)
        else:
            self._reserved_qty[order.symbol] -= order.qty

    def _fill(self, order: Order, price: D, ts: int, maker: bool) -> Fill:
        order.status = OrderStatus.FILLED
        return self._apply(order.id, order.symbol, order.side, order.qty, price, ts, order.bot, maker)

    def _apply(self, order_id: int, symbol: str, side: Side, qty: D, price: D, ts: int, bot: str, maker: bool,
               fee: D | None = None) -> Fill:
        """Bucht einen Fill (Cash, Position, Einstandswert, realisierter PnL)."""
        notional = qty * price
        fee = notional * self.fee_rate if fee is None else fee
        pos = self.positions.get(symbol) or Position(symbol, D(0), D(0))
        realized = D(0)
        if side == Side.BUY:
            self.cash -= notional + fee
            pos.qty += qty
            pos.cost += notional + fee
            self.positions[symbol] = pos
        else:
            basis = pos.avg_cost * qty
            proceeds = notional - fee
            realized = proceeds - basis
            self.cash += proceeds
            pos.qty -= qty
            pos.cost -= basis
            if pos.qty == 0:
                self.positions.pop(symbol, None)
        self.fees_paid += fee
        self.realized_pnl += realized
        fill = Fill(order_id, symbol, side, qty, price, fee, realized, ts, bot, maker)
        self.fills.append(fill)
        return fill

    def restore(self, fills: list[Fill]) -> None:
        """Zustand aus gespeicherten Fills (in zeitlicher Reihenfolge) wiederherstellen, z. B. nach einem Neustart."""
        for f in fills:
            self._apply(f.order_id, f.symbol, f.side, f.qty, f.price, f.ts, f.bot, f.maker, fee=f.fee)
        self._next_id = max([f.order_id for f in fills], default=0) + 1
