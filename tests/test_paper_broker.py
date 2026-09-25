from decimal import Decimal as D

import pytest

from tradebot_core import OrderStatus, OrderType, PaperBroker, Side


def broker(cash="10000", **kw):
    b = PaperBroker("t", cash, **kw)
    b.set_price("SOLUSDT", "100")
    b.set_price("BTCUSDT", "84000")
    return b


def test_market_buy_accounting():
    b = broker()
    o = b.place_order("SOLUSDT", Side.BUY, D("10"))
    assert o.status == OrderStatus.FILLED
    f = b.fills[0]
    assert f.price == D("100.05")  # 5 bp Slippage
    assert f.fee == D("1.0005")  # 0,1 % von 1000,5
    assert b.cash == D("10000") - D("1000.5") - D("1.0005")
    assert b.position_qty("SOLUSDT") == D("10")


def test_round_trip_at_same_price_costs_fees_and_slippage():
    b = broker()
    b.place_order("SOLUSDT", Side.BUY, D("10"))
    b.place_order("SOLUSDT", Side.SELL, D("10"))
    assert b.position_qty("SOLUSDT") == 0
    loss = b.start_cash - b.equity()
    assert loss == -b.realized_pnl  # alles realisiert, nichts offen
    assert loss == D("3")  # 2x0,1 % Gebühr + 2x0,05 % Slippage auf 1000 USDT = 0,3 %
    assert b.fees_paid > 0


def test_sell_realized_pnl_is_net_of_both_fees():
    b = broker()
    b.place_order("SOLUSDT", Side.BUY, D("10"))
    b.set_price("SOLUSDT", "110")
    b.place_order("SOLUSDT", Side.SELL, D("10"))
    cost = D("10") * D("100.05") * D("1.001")
    proceeds = D("10") * D("109.945") * D("0.999")
    assert b.realized_pnl == proceeds - cost
    assert b.cash == b.start_cash + b.realized_pnl


def test_qty_is_rounded_down_to_step():
    b = broker()
    o = b.place_order("SOLUSDT", Side.BUY, D("1.23789"))
    assert o.qty == D("1.237")


@pytest.mark.parametrize("qty,reason", [("0.0000001", "qty_below_min")])
def test_reject_qty_below_min(qty, reason):
    o = broker().place_order("BTCUSDT", Side.BUY, D(qty))
    assert o.status == OrderStatus.REJECTED and o.reject_reason == reason


def test_reject_below_min_notional():
    o = broker().place_order("BTCUSDT", Side.BUY, D("0.00001"))  # ca. 0,84 USDT
    assert o.reject_reason == "below_min_notional"


def test_reject_insufficient_cash_and_no_shorting():
    b = broker(cash="100")
    assert b.place_order("SOLUSDT", Side.BUY, D("2")).reject_reason == "insufficient_cash"
    assert b.place_order("SOLUSDT", Side.SELL, D("1")).reject_reason == "insufficient_position"


def test_equity_marks_to_market():
    b = broker()
    b.place_order("SOLUSDT", Side.BUY, D("10"))
    e1 = b.equity()
    b.set_price("SOLUSDT", "120")
    assert b.equity() - e1 == D("10") * D("20")


def test_limit_buy_fills_only_when_price_trades_through():
    b = broker()
    o = b.place_order("SOLUSDT", Side.BUY, D("10"), OrderType.LIMIT, D("95"))
    assert o.status == OrderStatus.OPEN and b.position_qty("SOLUSDT") == 0
    b.on_candle("SOLUSDT", high=101, low=95, close=98)  # berührt nur
    assert o.status == OrderStatus.OPEN
    fills = b.on_candle("SOLUSDT", high=99, low=94.9, close=96)
    assert o.status == OrderStatus.FILLED and fills[0].price == D("95") and fills[0].maker
    assert b.reserved_cash == 0


def test_limit_order_reserves_cash():
    b = broker(cash="1000")
    b.place_order("SOLUSDT", Side.BUY, D("9"), OrderType.LIMIT, D("95"))
    o2 = b.place_order("SOLUSDT", Side.BUY, D("9"), OrderType.LIMIT, D("95"))
    assert o2.reject_reason == "insufficient_cash"


def test_cancel_releases_reservation():
    b = broker(cash="1000")
    o = b.place_order("SOLUSDT", Side.BUY, D("9"), OrderType.LIMIT, D("95"))
    assert b.cancel_order(o.id) and b.reserved_cash == 0 and o.status == OrderStatus.CANCELLED


def test_affordable_qty_never_overspends():
    b = broker(cash="100")
    qty = b.affordable_qty("SOLUSDT", "100")
    assert b.place_order("SOLUSDT", Side.BUY, qty).status == OrderStatus.FILLED
    assert b.cash >= 0


def test_small_account_min_notional_limits_btc():
    """Mit 100 USDT ist BTC nur in sehr kleinen Mengen handelbar; 5 USDT Minimum gilt."""
    b = broker(cash="100")
    qty = b.affordable_qty("BTCUSDT", "50")
    assert qty == D("0.00059")
    assert b.place_order("BTCUSDT", Side.BUY, qty).status == OrderStatus.FILLED


def test_restore_rebuilds_identical_state():
    a = broker()
    a.place_order("SOLUSDT", Side.BUY, D("10"))
    a.set_price("SOLUSDT", "110")
    a.place_order("SOLUSDT", Side.SELL, D("4"))
    b = PaperBroker("t", "10000")
    b.restore(a.fills)
    assert (b.cash, b.realized_pnl, b.fees_paid) == (a.cash, a.realized_pnl, a.fees_paid)
    assert b.positions["SOLUSDT"].qty == a.positions["SOLUSDT"].qty
    assert b.positions["SOLUSDT"].avg_cost == a.positions["SOLUSDT"].avg_cost
    assert b.place_order("SOLUSDT", Side.SELL, D("1")).reject_reason == "no_price"  # Preise kommen aus Marktdaten


def test_partial_sell_keeps_average_cost():
    b = broker()
    b.place_order("SOLUSDT", Side.BUY, D("10"))
    avg = b.positions["SOLUSDT"].avg_cost
    b.place_order("SOLUSDT", Side.SELL, D("4"))
    assert b.positions["SOLUSDT"].avg_cost == avg and b.position_qty("SOLUSDT") == D("6")
