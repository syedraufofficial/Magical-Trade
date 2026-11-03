from .models import MarketSnapshot, Signal, Side


def evaluate(snapshot: MarketSnapshot, min_confidence=55.0, min_rr=2.0, max_spread_pct=1.5):
    """Transparent baseline signal. It is a research filter, not a prediction guarantee."""
    values = (snapshot.ltp, snapshot.bid, snapshot.ask)
    if not all(isinstance(x, (int, float)) and x > 0 for x in values):
        return None, "Invalid or missing market prices"
    if snapshot.ask < snapshot.bid:
        return None, "Crossed order book"
    mid = (snapshot.ask + snapshot.bid) / 2
    spread_pct = ((snapshot.ask - snapshot.bid) / mid) * 100
    if spread_pct > max_spread_pct:
        return None, f"Spread too wide: {spread_pct:.2f}%"

    score = 0.0
    reasons = []
    bullish = snapshot.ltp > snapshot.vwap > 0 and snapshot.sma_fast > snapshot.sma_slow > 0
    bearish = snapshot.ltp < snapshot.vwap and 0 < snapshot.sma_fast < snapshot.sma_slow
    if bullish:
        score += 30; reasons.append("Price above VWAP; fast SMA above slow SMA")
    elif bearish:
        score += 30; reasons.append("Price below VWAP; fast SMA below slow SMA")
    else:
        return None, "Trend filters are not aligned"
    if snapshot.volume_ratio >= 1.5:
        score += 20; reasons.append("Volume expansion")
    if abs(snapshot.oi_change_pct) >= 2:
        score += 20; reasons.append("Material open-interest change")
    if snapshot.volatility_pct > 0:
        score += 10; reasons.append("Volatility data available")
    score += max(0.0, 20.0 - spread_pct * 10.0)
    if score < min_confidence:
        return None, f"Confidence below threshold: {score:.1f}%"

    side = Side.BUY if bullish else Side.SELL
    risk = max(snapshot.ltp * 0.005, snapshot.ask - snapshot.bid)
    stop = snapshot.ltp - risk if side == Side.BUY else snapshot.ltp + risk
    target = snapshot.ltp + risk * min_rr if side == Side.BUY else snapshot.ltp - risk * min_rr
    return Signal(snapshot.symbol, side, min(score, 100), snapshot.ltp, stop, target, tuple(reasons)), "Signal generated; validate independently before use"
