from datetime import datetime, timezone, timedelta
import pytest
from magical_trade.intelligence import (
    DepthLevel, MarketDepth, assess_depth, order_flow_delta,
    black_scholes_greeks, ParticipantSnapshot, participant_bias,
    SignalInputs, score_setup, PaperAccount, risk_quantity,
)


def test_depth_imbalance_and_staleness():
    now = datetime.now(timezone.utc)
    d = MarketDepth((DepthLevel(100, 300),), (DepthLevel(101, 100),), now)
    m = assess_depth(d, now)
    assert m.valid and m.imbalance_pct == 50
    stale = MarketDepth(d.bids, d.asks, now - timedelta(seconds=10))
    assert not assess_depth(stale, now).valid


def test_flow_delta():
    assert order_flow_delta(150, 50) == 50
    with pytest.raises(ValueError): order_flow_delta(-1, 2)


def test_greeks_sensible_and_put_delta_negative():
    call = black_scholes_greeks(100, 100, 7, .2, option_type="CE")
    put = black_scholes_greeks(100, 100, 7, .2, option_type="PE")
    assert 0 < call.delta < 1 and -1 < put.delta < 0
    assert call.gamma > 0 and call.vega_per_1pct_iv > 0


def test_participant_data_is_explicitly_eod_and_date_checked():
    rows = [ParticipantSnapshot("2026-11-04", "2026-11-05", "NSE", "FII", "INDEX_FUT", 100, 80)]
    result = participant_bias(rows, "2026-11-04")
    assert result["available"] and result["data_type"] == "EOD"
    assert "not live" in result["warning"]
    assert not participant_bias(rows, "2026-11-05")["available"]


def test_ce_candidate_requires_aligned_inputs():
    x = SignalInputs(spot=22000, vwap=21900, sma_fast=22010, sma_slow=21980,
        breakout_confirmed=True, volume_ratio=1.8, futures_oi_change_pct=2,
        futures_direction="LONG_BUILDUP", pcr=1.2, dom_imbalance_pct=25,
        flow_delta_pct=20, option_delta=.52, iv_change_pct=1,
        spread_pct=.5, data_age_seconds=1, participant_bias="BULLISH", option_type="CE")
    result = score_setup(x)
    assert result.action == "CANDIDATE" and result.side == "CE"
    stale = SignalInputs(**{**x.__dict__, "data_age_seconds": 9})
    assert score_setup(stale).action == "NO_TRADE"


def test_paper_account_round_trip_charges_and_slippage():
    a = PaperAccount(5000)
    r = a.record_round_trip(100, 110, 2, "BUY", fees=5)
    assert r["net_pnl"] < 15 and a.cash == 5000 + r["net_pnl"]


def test_risk_sizing_never_rounds_up_to_unsafe_lot():
    assert risk_quantity(100, 99, lot_size=50, max_risk=50) == 50
    assert risk_quantity(100, 98, lot_size=50, max_risk=50) == 0
