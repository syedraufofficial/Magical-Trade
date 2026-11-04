
"""Angel One instrument master utilities."""

import requests


INSTRUMENT_MASTER_URL = (
    "https://margincalculator.angelone.in/"
    "OpenAPI_File/files/OpenAPIScripMaster.json"
)


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

    required_fields = {
        "token", "symbol", "name",
        "expiry", "strike", "lotsize",
        "instrumenttype", "exch_seg",
    }

    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError(
                "Invalid instrument record."
            )

        if not required_fields.issubset(record):
            raise RuntimeError(
                "Instrument master schema is incomplete."
            )

    return records


def filter_nifty50_stock_options(records, nifty50_symbols):
    """Return only NIFTY 50 constituent stock options."""

    allowed = {
        str(symbol).strip().upper()
        for symbol in nifty50_symbols
    }

    results = []

    for item in records:
        if (
            str(item.get("exch_seg", "")).lower() == "nfo"
            and str(item.get("instrumenttype", "")).upper()
            == "OPTSTK"
            and str(item.get("name", "")).upper() in allowed
            and str(item.get("symbol", "")).upper().endswith(
                ("CE", "PE")
            )
        ):
            results.append(item)

    return sorted(
        results,
        key=lambda item: (
            item.get("name", ""),
            item.get("expiry", ""),
            float(item.get("strike", 0)),
            item.get("symbol", ""),
        ),
    )
