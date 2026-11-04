
"""Magical Trade market data validation and parsing."""

from dataclasses import dataclass
from typing import Any


# ==========================================
# NUMERIC VALIDATION
# ==========================================

def safe_number(value: Any, field: str, allow_zero=True) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid market data field: {field}") from None

    if number != number or abs(number) == float("inf"):
        raise ValueError(f"Non-finite value: {field}")

    if number < 0 or (not allow_zero and number == 0):
        raise ValueError(f"Out-of-range value: {field}")

    return number


# ==========================================
# LIVE MARKET QUOTE
# ==========================================

@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    token: str
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    exchange_time: str | None = None


def parse_smartapi_quote(
    payload: dict,
    requested_symbol: str | None = None,
) -> MarketQuote:

    if not isinstance(payload, dict):
        raise ValueError("Quote payload must be an object")

    data = payload.get("data")

    records = (
        data.get("fetched")
        if isinstance(data, dict)
        else None
    )

    if records is not None:
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError("Expected exactly one quote record")
        record = records[0]
    else:
        record = data if isinstance(data, dict) else payload

    if not isinstance(record, dict):
        raise ValueError("Invalid quote record")

    symbol = str(
        record.get("tradingSymbol")
        or record.get("symbol")
        or requested_symbol
        or ""
    ).strip()

    token = str(
        record.get("symbolToken")
        or record.get("token")
        or ""
    ).strip()

    if not symbol:
        raise ValueError("Quote symbol is missing")

    if requested_symbol and symbol.upper() != requested_symbol.upper():
        raise ValueError("Requested and returned symbols differ")

    volume = safe_number(
        record.get("volume", 0), "volume"
    )

    if not volume.is_integer():
        raise ValueError("Volume must be a whole number")

    ltp = safe_number(record.get("ltp"), "ltp", False)
    open_price = safe_number(record.get("open", 0), "open")
    high = safe_number(record.get("high", 0), "high")
    low = safe_number(record.get("low", 0), "low")
    close = safe_number(record.get("close", 0), "close")

    if high and low and high < low:
        raise ValueError("Quote high is below quote low")

    exchange_time = (
        record.get("exchFeedTime")
        or record.get("exchangeTime")
    )

    return MarketQuote(
        symbol=symbol,
        token=token,
        ltp=ltp,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=int(volume),
        exchange_time=str(exchange_time) if exchange_time else None,
    )


# ==========================================
# HISTORICAL CANDLE MODEL
# ==========================================

@dataclass(frozen=True)
class MarketCandle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int


# ==========================================
# SMARTAPI HISTORICAL CANDLE PARSER
# ==========================================

def parse_smartapi_candles(payload: dict) -> list[MarketCandle]:

    if not isinstance(payload, dict):
        raise ValueError("Candle response must be an object")

    if payload.get("status") is False:
        raise RuntimeError(
            "Angel One rejected historical candle request: "
            + str(payload.get("message", "Unknown error"))
        )

    data = payload.get("data")

    if isinstance(data, dict):
        records = data.get("candles")
    else:
        records = data

    if not isinstance(records, list):
        raise ValueError("Historical candle data is missing")

    candles = []

    for index, row in enumerate(records):

        if not isinstance(row, (list, tuple)) or len(row) < 6:
            raise ValueError(
                f"Invalid candle record at index {index}"
            )

        timestamp = str(row[0])

        if not timestamp.strip():
            raise ValueError("Candle timestamp is missing")

        open_price = safe_number(row[1], "open", False)
        high = safe_number(row[2], "high", False)
        low = safe_number(row[3], "low", False)
        close = safe_number(row[4], "close", False)
        volume = safe_number(row[5], "volume")

        if not volume.is_integer():
            raise ValueError("Candle volume must be an integer")

        if high < low:
            raise ValueError("Candle high is below low")

        if not low <= open_price <= high:
            raise ValueError("Candle open is outside high/low")

        if not low <= close <= high:
            raise ValueError("Candle close is outside high/low")

        candles.append(
            MarketCandle(
                timestamp=timestamp,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=int(volume),
            )
        )

    return candles
