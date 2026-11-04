from magical_trade.instruments import (
    filter_nifty50_stock_options,
)


def test_only_nifty50_stock_options_are_returned():
    records = [
        {
            "token": "100",
            "symbol": "RELIANCE27NOV3000CE",
            "name": "RELIANCE",
            "expiry": "27NOV2026",
            "strike": "300000",
            "lotsize": "250",
            "instrumenttype": "OPTSTK",
            "exch_seg": "NFO",
        },
        {
            "token": "200",
            "symbol": "ABC27NOV100CE",
            "name": "ABC",
            "expiry": "27NOV2026",
            "strike": "100000",
            "lotsize": "1",
            "instrumenttype": "OPTSTK",
            "exch_seg": "NFO",
        },
    ]

    result = filter_nifty50_stock_options(
        records,
        ["RELIANCE", "HDFCBANK"],
    )

    assert len(result) == 1
    assert result[0]["name"] == "RELIANCE"
    assert result[0]["symbol"].endswith("CE")