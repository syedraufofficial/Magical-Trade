"""Deterministic, fail-closed NIFTY options research engines.

This module never places broker orders. Inputs must be supplied by a separately
validated market-data adapter. Participant positioning is explicitly EOD data.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import erf, exp, log, pi, sqrt
from typing import Mapping, Sequence


@dataclass(frozen=True)
class DepthLevel:
    price: float
    quantity: int


@dataclass(frozen=True)
class MarketDepth:
    bids: tuple[DepthLevel, ...]
    asks: tuple[DepthLevel, ...]
    timestamp: datetime


@dataclass(frozen=True)
class DOMMetrics:
    imbalance_pct: float
    spread_pct: float
    bid_quantity: int
    ask_quantity: int
    valid: bool
    reason: str = ""


def _finite_positive(value: float, name: str) -> float:
    value = float(value)
    if not (value > 0 and value < float("inf")):
        raise ValueError(f"{name} must be finite and positive")
    return value


def assess_depth(depth: MarketDepth, now: datetime | None = None, max_age_seconds: int = 3) -> DOMMetrics:
    """Aggregate multi-level book imbalance; a snapshot alone is not a trade signal."""
    now = now or datetime.now(timezone.utc)
    if depth.timestamp.tzinfo is None:
        return DOMMetrics(0, 0, 0, 0, False, "Depth timestamp must be timezone-aware")
    age = (now - depth.timestamp).total_seconds()
    if age < -1 or age > max_age_seconds:
        return DOMMetrics(0, 0, 0, 0, False, "Depth data is stale or future-dated")
    if not depth.bids or not depth.asks:
        return DOMMetrics(0, 0, 0, 0, False, "Bid/ask depth is missing")
    if any(x.price <= 0 or x.quantity < 0 for x in (*depth.bids, *depth.asks)):
        return DOMMetrics(0, 0, 0, 0, False, "Invalid depth level")
    best_bid, best_ask = depth.bids[0].price, depth.asks[0].price
    if best_ask <= best_bid:
        return DOMMetrics(0, 0, 0, 0, False, "Crossed or locked book")
    bq, aq = sum(x.quantity for x in depth.bids), sum(x.quantity for x in depth.asks)
    total = bq + aq
    imbalance = 0.0 if total == 0 else 100.0 * (bq - aq) / total
    mid = (best_bid + best_ask) / 2
    spread = 100.0 * (best_ask - best_bid) / mid
    return DOMMetrics(imbalance, spread, bq, aq, True)


def order_flow_delta(aggressive_buy_qty: int, aggressive_sell_qty: int) -> float:
    """Signed executed-volume delta; unlike displayed depth, this uses trades."""
    if min(aggressive_buy_qty, aggressive_sell_qty) < 0:
        raise ValueError("Executed quantities cannot be negative")
    total = aggressive_buy_qty + aggressive_sell_qty
    return 0.0 if total == 0 else 100.0 * (aggressive_buy_qty - aggressive_sell_qty) / total


@dataclass(frozen=True)
class Greeks:
    delta: float
    gamma: float
    theta_per_day: float
    vega_per_1pct_iv: float
    implied_volatility: float


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def black_scholes_greeks(spot: float, strike: float, days_to_expiry: float,
                         volatility: float, risk_free_rate: float = 0.06,
                         option_type: str = "CE") -> Greeks:
    """European Black-Scholes Greeks. Volatility is decimal (e.g. 0.20).

    Theta is per calendar day; vega is per 1 volatility percentage point.
    This is a model estimate, not an exchange-provided Greek.
    """
    s, k = _finite_positive(spot, "spot"), _finite_positive(strike, "strike")
    vol = _finite_positive(volatility, "volatility")
    if days_to_expiry <= 0 or risk_free_rate < 0:
        raise ValueError("Expiry must be positive and rate non-negative")
    kind = option_type.upper()
    if kind not in {"CE", "PE"}:
        raise ValueError("option_type must be CE or PE")
    t = days_to_expiry / 365.0
    root_t = sqrt(t)
    d1 = (log(s / k) + (risk_free_rate + 0.5 * vol * vol) * t) / (vol * root_t)
    d2 = d1 - vol * root_t
    pdf = _norm_pdf(d1)
    delta = _norm_cdf(d1) if kind == "CE" else _norm_cdf(d1) - 1.0
    gamma = pdf / (s * vol * root_t)
    vega = s * pdf * root_t / 100.0
    theta_common = -(s * pdf * vol) / (2.0 * root_t)
    if kind == "CE":
        theta = theta_common - risk_free_rate * k * exp(-risk_free_rate * t) * _norm_cdf(d2)
    else:
        theta = theta_common + risk_free_rate * k * exp(-risk_free_rate * t) * _norm_cdf(-d2)
    return Greeks(delta, gamma, theta / 365.0, vega, vol)


@dataclass(frozen=True)
class ParticipantSnapshot:
    report_date: str
    published_at: str
    source: str
    participant: str
    instrument: str
    long_positions: int
    short_positions: int

    @property
    def net_positions(self) -> int:
        return self.long_positions - self.short_positions


def participant_bias(rows: Sequence[ParticipantSnapshot], expected_report_date: str) -> dict:
    """Summarise official EOD participant data; rejects stale/mixed report dates."""
    if not rows:
        return {"available": False, "reason": "No participant report supplied", "data_type": "EOD"}
    dates = {r.report_date for r in rows}
    if dates != {expected_report_date}:
        return {"available": False, "reason": "Participant report date mismatch/stale", "data_type": "EOD"}
    totals: dict[str, dict[str, int]] = {}
    for r in rows:
        p = r.participant.strip().upper()
        if p not in {"CLIENT", "PRO", "FII", "DII"}:
            continue
        item = totals.setdefault(p, {"long": 0, "short": 0, "net": 0})
        item["long"] += r.long_positions
        item["short"] += r.short_positions
        item["net"] += r.net_positions
    return {"available": bool(totals), "data_type": "EOD", "report_date": expected_report_date,
            "source": rows[0].source, "participants": totals,
            "warning": "Aggregate participant positioning, not live client orders or individual identities."}


WEIGHTS = {"price_action": .20, "vwap_volume": .15, "futures_oi": .15,
           "option_chain": .10, "dom_flow": .15, "greeks_iv": .15,
           "institutional_context": .10}


@dataclass(frozen=True)
class SignalInputs:
    spot: float
    vwap: float
    sma_fast: float
    sma_slow: float
    breakout_confirmed: bool
    volume_ratio: float
    futures_oi_change_pct: float
    futures_direction: str  # LONG_BUILDUP, SHORT_BUILDUP, LONG_UNWINDING, SHORT_COVERING, NEUTRAL
    pcr: float
    dom_imbalance_pct: float
    flow_delta_pct: float
    option_delta: float
    iv_change_pct: float
    spread_pct: float
    data_age_seconds: float
    participant_bias: str = "NEUTRAL"  # BULLISH, BEARISH, NEUTRAL, UNAVAILABLE
    option_type: str = "CE"


@dataclass(frozen=True)
class Decision:
    action: str
    score: float
    side: str | None
    reasons: tuple[str, ...]
    components: Mapping[str, float]


def score_setup(x: SignalInputs, min_score: float = 75.0) -> Decision:
    """Weighted setup score with hard gates. It is not a probability of profit."""
    side = x.option_type.upper()
    if side not in {"CE", "PE"}:
        return Decision("NO_TRADE", 0, None, ("Invalid option type",), {})
    vals = [x.spot, x.vwap, x.sma_fast, x.sma_slow, x.volume_ratio, x.pcr, x.spread_pct, x.data_age_seconds]
    if any(v != v or abs(v) == float("inf") for v in vals):
        return Decision("NO_TRADE", 0, None, ("Non-finite input",), {})
    if min(x.spot, x.vwap, x.sma_fast, x.sma_slow, x.volume_ratio, x.pcr) <= 0:
        return Decision("NO_TRADE", 0, None, ("Missing/invalid required data",), {})
    if x.data_age_seconds > 3 or x.data_age_seconds < 0:
        return Decision("NO_TRADE", 0, None, ("Market data stale or invalid",), {})
    if x.spread_pct > 1.5:
        return Decision("NO_TRADE", 0, None, ("Option spread exceeds 1.5%",), {})
    if not 0.45 <= abs(x.option_delta) <= 0.65:
        return Decision("NO_TRADE", 0, None, ("Option delta outside preferred 0.45–0.65 range",), {})
    bullish = x.spot > x.vwap and x.sma_fast > x.sma_slow
    bearish = x.spot < x.vwap and x.sma_fast < x.sma_slow
    if (side == "CE" and not bullish) or (side == "PE" and not bearish):
        return Decision("NO_TRADE", 0, None, ("Spot/VWAP/trend not aligned",), {})
    aligned_oi = x.futures_direction == ("LONG_BUILDUP" if side == "CE" else "SHORT_BUILDUP")
    aligned_dom = x.dom_imbalance_pct >= 15 and x.flow_delta_pct >= 10 if side == "CE" else x.dom_imbalance_pct <= -15 and x.flow_delta_pct <= -10
    aligned_pcr = x.pcr >= 1.0 if side == "CE" else x.pcr <= 1.0
    aligned_participant = x.participant_bias == ("BULLISH" if side == "CE" else "BEARISH")
    components = {
        "price_action": 100.0 if x.breakout_confirmed else 0.0,
        "vwap_volume": 100.0 if x.volume_ratio >= 1.5 else 35.0 if x.volume_ratio >= 1.2 else 0.0,
        "futures_oi": 100.0 if aligned_oi and abs(x.futures_oi_change_pct) >= 1.0 else 0.0,
        "option_chain": 100.0 if aligned_pcr else 40.0,
        "dom_flow": 100.0 if aligned_dom else 0.0,
        "greeks_iv": 100.0 if 0.45 <= abs(x.option_delta) <= 0.65 and x.iv_change_pct <= 5 else 50.0,
        "institutional_context": 100.0 if aligned_participant else 50.0 if x.participant_bias == "UNAVAILABLE" else 0.0,
    }
    score = round(sum(components[k] * WEIGHTS[k] for k in WEIGHTS), 1)
    reasons = ("Bullish CE conditions" if side == "CE" else "Bearish PE conditions",
               "Participant input is EOD aggregate, not live client flow" if x.participant_bias != "UNAVAILABLE" else "Participant report unavailable; neutral context")
    action = "CANDIDATE" if score >= min_score else "NO_TRADE"
    return Decision(action, score, side if action == "CANDIDATE" else None, reasons, components)


@dataclass
class PaperAccount:
    initial_capital: float = 5000.0
    cash: float = field(init=False)
    daily_realized_pnl: float = 0.0
    trades: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if self.initial_capital <= 0:
            raise ValueError("Initial capital must be positive")
        self.cash = float(self.initial_capital)

    def record_round_trip(self, entry: float, exit_price: float, quantity: int,
                          side: str, fees: float = 0.0, slippage_bps: float = 5.0) -> dict:
        if min(entry, exit_price, quantity) <= 0 or fees < 0 or slippage_bps < 0:
            raise ValueError("Invalid paper trade parameters")
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        slip = slippage_bps / 10000.0
        fill_in = entry * (1 + slip if side == "BUY" else 1 - slip)
        fill_out = exit_price * (1 - slip if side == "BUY" else 1 + slip)
        gross = (fill_out - fill_in) * quantity * (1 if side == "BUY" else -1)
        net = gross - fees
        self.cash += net
        self.daily_realized_pnl += net
        item = {"side": side, "quantity": quantity, "entry_fill": round(fill_in, 4),
                "exit_fill": round(fill_out, 4), "gross_pnl": round(gross, 2),
                "fees": round(fees, 2), "net_pnl": round(net, 2), "cash": round(self.cash, 2)}
        self.trades.append(item)
        return item


def risk_quantity(entry: float, stop: float, lot_size: int, max_risk: float = 50.0,
                  fees_and_slippage_per_unit: float = 0.0) -> int:
    """Largest whole-lot quantity within risk budget; returns zero if one lot is too risky."""
    if min(entry, stop, lot_size, max_risk) <= 0 or fees_and_slippage_per_unit < 0:
        raise ValueError("Invalid risk sizing input")
    unit_risk = abs(entry - stop) + fees_and_slippage_per_unit
    if unit_risk <= 0:
        raise ValueError("Stop must differ from entry")
    per_lot = unit_risk * lot_size
    lots = int(max_risk // per_lot)
    return lots * lot_size
