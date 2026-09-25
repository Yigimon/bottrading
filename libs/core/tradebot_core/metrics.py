"""Gemeinsame Performance-Kennzahlen (Backtests, Live-Paper und Dashboard nutzen dieselben Formeln)."""
import math

DAY_MS = 86_400_000


def max_drawdown(start: float, equity: list[float]) -> float:
    peak, mdd = start, 0.0
    for e in equity:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak) if peak else 0.0
    return mdd


def daily_returns(start: float, times_ms: list[int], equity: list[float]) -> list[float]:
    daily = {t // DAY_MS: e for t, e in zip(times_ms, equity)}  # letzter Stand je UTC-Tag
    vals = [start] + [daily[k] for k in sorted(daily)]
    return [vals[i + 1] / vals[i] - 1 for i in range(len(vals) - 1)]


def sharpe(start: float, times_ms: list[int], equity: list[float], periods: int = 365) -> float:
    rets = daily_returns(start, times_ms, equity)
    if len(rets) < 2:
        return 0.0
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
    return m / sd * math.sqrt(periods) if sd > 0 else 0.0


def trade_stats(pnls: list[float]) -> dict:
    """Kennzahlen aus realisierten Ergebnissen je abgeschlossenem Trade (nach Gebühren)."""
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p <= 0]
    gross_loss = abs(sum(losses))
    return {
        "trades": len(pnls),
        "win_rate": len(wins) / len(pnls) if pnls else None,
        "profit_factor": (sum(wins) / gross_loss) if gross_loss else (None if not wins else float("inf")),
        "avg_win": sum(wins) / len(wins) if wins else None,
        "avg_loss": sum(losses) / len(losses) if losses else None,
        "expectancy": sum(pnls) / len(pnls) if pnls else None,
        "best": max(pnls) if pnls else None,
        "worst": min(pnls) if pnls else None,
    }
