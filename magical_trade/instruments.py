"""Angel One instrument master utilities."""

from datetime import datetime
import requests


INSTRUMENT_MASTER_URL = (
    "https://margincalculator.angelone.in/"
    "OpenAPI_File/files/OpenAPIScripMaster.json"
)

REQUIRED_FIELDS = {
    "token",
    "symbol",
    "name",
    "expiry",
    "strike",
    "lotsize",
    "instrumenttype",
    "exch_seg",
}


def _positive_number(value, field):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid instrument {field}") from None

    if number <= 0 or number == float("inf") or number != number:
        raise ValueError(f"Invalid instrument {field}")

    return number


def _expiry_date(value):
    """Parse Angel One expiry formats such as 27NOV2026."""
    value = str(value or "").strip().upper()

    if not value:
        raise ValueError("Instrument expiry is missing")

    for fmt in ("%d%b%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Unsupported expiry format: {value}")


def load_instrument_master():
    """Download and validate Angel One's instrument master."""

    try:
        response = requests.get(
            INSTRUMENT_MASTER_URL,
            timeout=30,
        )
        response.raise_for_status()
        records = response.json()

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Instrument master download failed: {exc}"
        ) from None

    except ValueError:
        raise RuntimeError(
            "Instrument master returned invalid JSON."
        ) from None

    if not isinstance(records, list) or not records:
        raise RuntimeError(
            "Instrument master is empty or invalid."
        )

    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError("Invalid instrument record.")

        if not REQUIRED_FIELDS.issubset(record):
            raise RuntimeError(
                "Instrument master schema is incomplete."
            )

    return records


def filter_nifty50_stock_options(records, nifty50_symbols):
    """Return validated NIFTY 50 constituent stock option contracts."""

    if not isinstance(records, (list, tuple)):
        raise ValueError("Instrument records must be a list")

    allowed = {
        str(symbol).strip().upper()
        for symbol in nifty50_symbols
        if str(symbol).strip()
    }

    results = []

    for item in records:
        if not isinstance(item, dict):
            continue

        if str(item.get("exch_seg", "")).upper() != "NFO":
            continue

        if str(item.get("instrumenttype", "")).upper() != "OPTSTK":
            continue

        name = str(item.get("name", "")).strip().upper()
        symbol = str(item.get("symbol", "")).strip().upper()

        if name not in allowed:
            continue

        if not symbol.endswith(("CE", "PE")):
            continue

        try:
            lot_size = _positive_number(item.get("lotsize"), "lot size")
            strike = _positive_number(item.get("strike"), "strike")
            expiry = _expiry_date(item.get("expiry"))

            if not lot_size.is_integer():
                continue

            if not strike > 0:
                continue

        except ValueError:
            continue

        results.append(item)

    return sorted(
        results,
        key=lambda item: (
            str(item.get("name", "")),
            _expiry_date(item["expiry"]),
            float(item["strike"]),
            str(item.get("symbol", "")),
        ),
    )


def find_instrument(records, exchange, trading_symbol):
    """Find one exact instrument; reject missing or ambiguous matches."""

    exchange = str(exchange).strip().upper()
    trading_symbol = str(trading_symbol).strip().upper()

    if not exchange or not trading_symbol:
        raise ValueError("Exchange and trading symbol are required")

    matches = [
        item
        for item in records
        if isinstance(item, dict)
        and str(item.get("exch_seg", "")).upper() == exchange
        and str(item.get("symbol", "")).upper() == trading_symbol
    ]

    if not matches:
        raise ValueError(
            f"Instrument not found: {exchange} {trading_symbol}"
        )

    if len(matches) > 1:
        raise ValueError(
            f"Instrument lookup is ambiguous: {exchange} {trading_symbol}"
        )

    return matches[0]