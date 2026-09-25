"""Inkrementelle Indikatoren (eine Kerze nach der anderen), identisch im Backtest und im Live-Betrieb."""
from collections import deque
from math import sqrt


class EMA:
    def __init__(self, n: int):
        self.n, self.k, self.value, self._count = n, 2 / (n + 1), None, 0

    def update(self, x: float) -> float:
        self._count += 1
        self.value = x if self.value is None else self.value + self.k * (x - self.value)
        return self.value

    @property
    def ready(self) -> bool:
        return self._count >= self.n


class RSI:
    """Wilder-RSI."""

    def __init__(self, n: int = 14):
        self.n, self.prev, self.avg_gain, self.avg_loss, self._count, self.value = n, None, 0.0, 0.0, 0, None

    def update(self, close: float):
        if self.prev is None:
            self.prev = close
            return None
        change, self.prev = close - self.prev, close
        gain, loss = max(change, 0.0), max(-change, 0.0)
        self._count += 1
        if self._count <= self.n:
            self.avg_gain += gain / self.n
            self.avg_loss += loss / self.n
            if self._count < self.n:
                return None
        else:
            self.avg_gain = (self.avg_gain * (self.n - 1) + gain) / self.n
            self.avg_loss = (self.avg_loss * (self.n - 1) + loss) / self.n
        self.value = 100.0 if self.avg_loss == 0 else 100 - 100 / (1 + self.avg_gain / self.avg_loss)
        return self.value


class ATR:
    """Wilder-ATR."""

    def __init__(self, n: int = 14):
        self.n, self.prev_close, self.value, self._count, self._sum = n, None, None, 0, 0.0

    def update(self, high: float, low: float, close: float):
        tr = high - low if self.prev_close is None else max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
        self.prev_close = close
        self._count += 1
        if self._count <= self.n:
            self._sum += tr
            if self._count == self.n:
                self.value = self._sum / self.n
        else:
            self.value = (self.value * (self.n - 1) + tr) / self.n
        return self.value


class Window:
    """Gleitendes Fenster über die letzten n Werte: Mittelwert, Standardabweichung, Max, Min."""

    def __init__(self, n: int):
        self.n, self.q = n, deque(maxlen=n)

    def push(self, x: float) -> None:
        self.q.append(x)

    @property
    def full(self) -> bool:
        return len(self.q) == self.n

    @property
    def mean(self) -> float:
        return sum(self.q) / len(self.q)

    @property
    def std(self) -> float:
        m = self.mean
        return sqrt(sum((x - m) ** 2 for x in self.q) / len(self.q))

    @property
    def max(self) -> float:
        return max(self.q)

    @property
    def min(self) -> float:
        return min(self.q)
