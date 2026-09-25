from dataclasses import dataclass
from decimal import Decimal as D


@dataclass(frozen=True)
class SymbolRules:
    step: D  # Mengenschritt (LOT_SIZE)
    min_qty: D
    min_notional: D  # Mindest-Ordervolumen in Quote-Währung
    tick: D  # Preisschritt

    def round_qty(self, qty: D) -> D:
        return (qty // self.step) * self.step  # immer abrunden

    def round_price(self, price: D) -> D:
        return (price // self.tick) * self.tick


# Werte aus Binance exchangeInfo (Spot), Stand 2026-09-25.
DEFAULT_RULES: dict[str, SymbolRules] = {
    "BTCUSDT": SymbolRules(D("0.00001"), D("0.00001"), D("5"), D("0.01")),
    "ETHUSDT": SymbolRules(D("0.0001"), D("0.0001"), D("5"), D("0.01")),
    "SOLUSDT": SymbolRules(D("0.001"), D("0.001"), D("5"), D("0.01")),
}
