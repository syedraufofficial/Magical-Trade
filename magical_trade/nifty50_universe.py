"""NIFTY 50 constituent universe loader."""

import csv
import io
import requests


NIFTY50_CSV_URL = (
    "https://nsearchives.nseindia.com/"
    "content/indices/ind_nifty50list.csv"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/csv,*/*",
}


def load_nifty50_symbols():
    """Download and validate exactly 50 unique NIFTY constituents."""

    try:
        response = requests.get(
            NIFTY50_CSV_URL,
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()

    except requests.RequestException as exc:
        raise RuntimeError(
            f"NIFTY 50 download failed: {exc}"
        ) from None

    if not response.text.strip():
        raise RuntimeError("NSE returned an empty constituent file.")

    try:
        reader = csv.DictReader(io.StringIO(response.text))
        headers = {
            str(header).strip()
            for header in (reader.fieldnames or [])
        }

        if "Symbol" not in headers:
            raise RuntimeError(
                "NSE constituent file is missing the Symbol column."
            )

        symbols = {
            str(row.get("Symbol", "")).strip().upper()
            for row in reader
            if row.get("Symbol")
        }

    except (csv.Error, AttributeError, TypeError):
        raise RuntimeError(
            "Unable to parse NIFTY 50 constituent file."
        ) from None

    if len(symbols) != 50:
        raise RuntimeError(
            f"Expected 50 unique NIFTY constituents; received {len(symbols)}."
        )

    if any(not symbol.isalnum() for symbol in symbols):
        raise RuntimeError("Invalid symbol found in NIFTY 50 data.")

    return sorted(symbols)