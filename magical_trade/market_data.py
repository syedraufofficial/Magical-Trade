"""Safe Angel One SmartAPI market quote parser.

This module validates quote data only.
It does not authenticate or place broker orders.
"""

from dataclasses import dataclass
from typing import Any


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


def safe_number(value: Any, field: str, allow_zero=True) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid quote field: {field}") from None

    if not (number == number and abs(number) != float("inf")):
        raise ValueError(f"Non-finite quote field: {field}")

    if number < 0 or (not allow_zero and number == 0):
        raise ValueError(f"Out-of-range quote field: {field}")

    return number


def parse_smartapi_quote(
    payload: dict,
    requested_symbol: str | None = None,
) -> MarketQuote:

    if not isinstance(payload, dict):
        raise ValueError("Quote payload must be an object")

    data = payload.get("data")
    records = data.get("fetched") if isinstance(data, dict) else None

    if records is not None:
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError("Expected exactly one fetched quote record")
        record = records[0]
    else:
        record = payload

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
        raise ValueError("Returned symbol does not match requested symbol")

    volume = safe_number(record.get("volume", 0), "volume")

    if not volume.is_integer():
        raise ValueError("Volume must be a whole number")

    exchange_time = (
        record.get("exchFeedTime")
        or record.get("exchangeTime")
    )

    return MarketQuote(
        symbol=symbol,
        token=token,
        ltp=safe_number(record.get("ltp"), "ltp", False),
        open=safe_number(record.get("open", 0), "open"),
        high=safe_number(record.get("high", 0), "high"),
        low=safe_number(record.get("low", 0), "low"),
        close=safe_number(record.get("close", 0), "close"),
        volume=int(volume),
        exchange_time=str(exchange_time) if exchange_time else None,
    )