
from .models import MarketSnapshot, Signal, Side


def evaluate(
    snapshot: MarketSnapshot,
    min_confidence=55.0,
    min_rr=2.0,
    max_spread_pct=1.5,
):
    """Research signal filter. Not a prediction or profit guarantee."""

    prices = (snapshot.ltp, snapshot.bid, snapshot.ask)

    if not all(
        isinstance(value, (int, float)) and value > 0
        for value in prices
    ):
        return None, "Invalid or missing market prices"

    if snapshot.ask < snapshot.bid:
        return None, "Crossed order book"

    if min_rr < 2.0:
        return None, "Minimum risk/reward must be at least 2:1"

    midpoint = (snapshot.ask + snapshot.bid) / 2
    spread_pct = (
        (snapshot.ask - snapshot.bid) / midpoint
    ) * 100

    if spread_pct > max_spread_pct:
        return None, f"Spread too wide: {spread_pct:.2f}%"

    if snapshot.vwap <= 0:
        return None, "VWAP data unavailable"

    if snapshot.sma_fast <= 0 or snapshot.sma_slow <= 0:
        return None, "Moving average data unavailable"

    bullish = (
        snapshot.ltp > snapshot.vwap
        and snapshot.sma_fast > snapshot.sma_slow
    )

    bearish = (
        snapshot.ltp < snapshot.vwap
        and snapshot.sma_fast < snapshot.sma_slow
    )

    if bullish == bearish:
        return None, "Trend filters are not aligned"

    score = 0.0
    reasons = []

    if bullish:
        score += 30
        reasons.append("Bullish price and moving average alignment")
    else:
        score += 30
        reasons.append("Bearish price and moving average alignment")

    if snapshot.volume_ratio >= 1.5:
        score += 20
        reasons.append("Volume expansion")

    if abs(snapshot.oi_change_pct) >= 2:
        score += 20
        reasons.append("Material open-interest change")

    if snapshot.volatility_pct > 0:
        score += 10
        reasons.append("Volatility data available")

    score += max(0.0, 20.0 - spread_pct * 10.0)

    if score < min_confidence:
        return None, f"Confidence below threshold: {score:.1f}%"

    side = Side.BUY if bullish else Side.SELL

    risk = max(
        snapshot.ltp * 0.005,
        snapshot.ask - snapshot.bid,
    )

    if risk <= 0:
        return None, "Invalid stop-loss distance"

    if side == Side.BUY:
        stop = snapshot.ltp - risk
        target = snapshot.ltp + risk * min_rr
    else:
        stop = snapshot.ltp + risk
        target = snapshot.ltp - risk * min_rr

    if stop <= 0 or target <= 0:
        return None, "Invalid calculated stop or target"

    actual_rr = abs(target - snapshot.ltp) / abs(
        snapshot.ltp - stop
    )

    if actual_rr < 2.0:
        return None, "Risk/reward below 2:1"

    signal = Signal(
        symbol=snapshot.symbol,
        side=side,
        confidence=min(score, 100.0),
        entry=snapshot.ltp,
        stop_loss=stop,
        target=target,
        rationale=tuple(reasons),
    )

    return signal, (
        "Signal generated. Validate option contract, "
        "market data and execution conditions."
    )
