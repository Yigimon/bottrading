from decimal import Decimal as D

import pytest

from tradebot_core import PaperBroker
from tradebot_core.indicators import ATR, EMA, RSI, Window
from tradebot_core.runner import BotRunner
from tradebot_core.strategy import Candle, MeanReversion, Signal, Strategy, TrendBreakout

H = 3_600_000


def candle(i, o, h=None, l=None, c=None, sym="SOLUSDT"):
    h = h if h is not None else max(o, c or o)
    l = l if l is not None else min(o, c or o)
    c = c if c is not None else o
    return Candle(sym, "1h", i * H, (i + 1) * H - 1, o, h, l, c, 1.0)


# ---- Indikatoren ----
def test_ema_constant_series():
    e = EMA(10)
    for _ in range(30):
        e.update(5.0)
    assert e.value == pytest.approx(5.0) and e.ready


def test_rsi_extremes():
    up, down = RSI(14), RSI(14)
    for i in range(40):
        up.update(100 + i)
        down.update(200 - i)
    assert up.value == 100.0
    assert down.value == pytest.approx(0.0, abs=1e-9)


def test_rsi_known_value():
    # Klassisches Beispiel: 14 Anstiege (+1) und Abfälle (-1) im Wechsel ergeben RSI 50
    r = RSI(14)
    price = 100
    for i in range(29):
        price += 1 if i % 2 == 0 else -1
        r.update(price)
    assert r.value == pytest.approx(50, abs=3)


def test_atr_constant_range():
    a = ATR(14)
    for _ in range(30):
        a.update(110, 100, 105)
    assert a.value == pytest.approx(10.0)


def test_window_stats():
    w = Window(4)
    for x in [1, 2, 3, 4, 5]:
        w.push(x)
    assert w.full and w.mean == 3.5 and w.max == 5 and w.min == 2


# ---- Strategien ----
def test_trend_breakout_compares_only_with_previous_candles():
    s = TrendBreakout(entry_n=5, exit_n=3, atr_n=3)
    # Seitwärts, dann Kerze deren Close über allen vorherigen Hochs liegt
    for i in range(6):
        assert s.on_candle(candle(i, 100, 101, 99, 100), False) is None
    sig = s.on_candle(candle(6, 100, 106, 100, 105), False)
    assert sig == Signal("enter", "breakout") and s.stop is not None and s.stop < 105


def test_trend_exit_on_channel_break():
    s = TrendBreakout(entry_n=5, exit_n=3, atr_n=3)
    for i in range(6):
        s.on_candle(candle(i, 100, 101, 99, 100), False)
    s.on_candle(candle(6, 100, 106, 100, 105), False)
    sig = s.on_candle(candle(7, 105, 105, 90, 91), True)
    assert sig == Signal("exit", "channel_exit")


def test_meanrev_enters_on_oversold_dip_below_band():
    s = MeanReversion(rsi_n=5, rsi_entry=30, bb_n=10, bb_k=1.5, trend_filter=False)
    for i in range(12):
        s.on_candle(candle(i, 100 + (i % 2)), False)
    sig = None
    for i, px in enumerate([97, 94, 90], start=12):
        sig = s.on_candle(candle(i, px), False) or sig
    assert sig == Signal("enter", "oversold") and s.stop is not None


# ---- Runner: Ausführung ohne Look-ahead ----
class AlwaysEnterOnce(Strategy):
    name = "test"

    def __init__(self, enter_at, exit_at=None, stop=None):
        self.enter_at, self.exit_at, self._stop_val, self.n = enter_at, exit_at, stop, 0

    def on_candle(self, c, in_position):
        self.n += 1
        if not in_position and self.n == self.enter_at:
            self.stop = self._stop_val
            return Signal("enter")
        if in_position and self.n == self.exit_at:
            return Signal("exit")
        return None


def make_runner(strategy, cash="10000", frac=0.5):
    b = PaperBroker("t", cash)
    return b, BotRunner(b, lambda: strategy, ["SOLUSDT"], position_fraction=frac, name="t")


def test_signal_executes_at_next_open_not_at_signal_close():
    b, r = make_runner(AlwaysEnterOnce(enter_at=1))
    r.on_candle(candle(0, 100, 101, 99, 100))  # Signal am Ende dieser Kerze
    assert b.position_qty("SOLUSDT") == 0  # noch nicht ausgeführt
    r.on_candle(candle(1, 120, 125, 118, 122))  # Ausführung zum Open 120, nicht zum alten Close 100
    fill = b.fills[0]
    assert fill.price == D("120") * D("1.0005")


def test_immediate_mode_executes_at_signal_close():
    s = AlwaysEnterOnce(enter_at=1)
    b = PaperBroker("t", "10000")
    r = BotRunner(b, lambda: s, ["SOLUSDT"], position_fraction=0.5, name="t", immediate=True)
    r.on_candle(candle(0, 100, 101, 99, 103))
    assert b.fills[0].price == D("103") * D("1.0005")  # zum Close der Signalkerze, nicht erst zur nächsten


def test_position_sized_by_fraction_of_equity():
    b, r = make_runner(AlwaysEnterOnce(enter_at=1), cash="1000", frac=0.5)
    r.on_candle(candle(0, 100))
    r.on_candle(candle(1, 100))
    invested = b.fills[0].qty * b.fills[0].price
    assert D("495") < invested < D("500")


def test_stop_loss_fills_at_stop_within_candle():
    b, r = make_runner(AlwaysEnterOnce(enter_at=1, stop=95))
    r.on_candle(candle(0, 100))
    r.on_candle(candle(1, 100, 101, 99, 100))
    r.on_candle(candle(2, 100, 100, 90, 92))  # Tief unter dem Stop
    assert b.position_qty("SOLUSDT") == 0
    assert b.fills[-1].price == D("95") * D("0.9995")


def test_stop_loss_gap_fills_at_open_when_below_stop():
    b, r = make_runner(AlwaysEnterOnce(enter_at=1, stop=95))
    r.on_candle(candle(0, 100))
    r.on_candle(candle(1, 100, 101, 99, 100))
    r.on_candle(candle(2, 88, 90, 85, 86))  # Gap unter den Stop
    assert b.fills[-1].price == D("88") * D("0.9995")


def test_exit_signal_sells_next_open():
    b, r = make_runner(AlwaysEnterOnce(enter_at=1, exit_at=3))
    for i, px in enumerate([100, 100, 100, 110, 110]):  # Exit-Signal bei Kerze 2, Ausführung zum Open von Kerze 3
        r.on_candle(candle(i, px))
    sell = b.fills[-1]
    assert sell.side.value == "sell" and sell.price == D("110") * D("0.9995")


def test_small_account_skips_when_position_below_min_notional():
    b, r = make_runner(AlwaysEnterOnce(enter_at=1), cash="8", frac=0.33)  # 2,64 USDT < 5 Minimum
    for i in range(3):
        r.on_candle(candle(i, 100))
    assert b.fills == [] and b.position_qty("SOLUSDT") == 0


def test_vol_target_sizes_by_stop_distance():
    class Fixed(AlwaysEnterOnce):
        vol_target = 0.01  # 1 % Risiko

    s = Fixed(enter_at=1, stop=90)  # Stop 10 % unter 100
    b = PaperBroker("t", "10000")
    r = BotRunner(b, lambda: s, ["SOLUSDT"], position_fraction=0.5, name="t", immediate=True)
    r.on_candle(candle(0, 100, 101, 99, 100))
    invested = float(b.fills[0].qty * b.fills[0].price)
    assert 990 < invested < 1001  # 1 % von 10.000 = 100 USDT Risiko bei 10 USDT Abstand -> ~1.000 USDT, nicht 5.000


def test_vol_target_never_exceeds_fraction():
    class Fixed(AlwaysEnterOnce):
        vol_target = 0.05

    s = Fixed(enter_at=1, stop=99.9)  # sehr enger Stop würde riesige Position ergeben
    b = PaperBroker("t", "10000")
    r = BotRunner(b, lambda: s, ["SOLUSDT"], position_fraction=0.33, name="t", immediate=True)
    r.on_candle(candle(0, 100, 101, 99, 100))
    assert float(b.fills[0].qty * b.fills[0].price) <= 3300.1
