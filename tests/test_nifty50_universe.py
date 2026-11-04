from unittest.mock import Mock, patch

from magical_trade.nifty50_universe import load_nifty50_symbols


def test_load_nifty50_symbols_returns_50_symbols():
    rows = ["Symbol,Company Name"]
    rows.extend(
        f"STOCK{i},Company {i}"
        for i in range(50)
    )
    csv_data = "\n".join(rows)

    mock_response = Mock()
    mock_response.text = csv_data
    mock_response.raise_for_status.return_value = None

    with patch(
        "magical_trade.nifty50_universe.requests.get",
        return_value=mock_response,
    ):
        symbols = load_nifty50_symbols()

    assert len(symbols) == 50
    assert "STOCK0" in symbols
    assert symbols == sorted(symbols)