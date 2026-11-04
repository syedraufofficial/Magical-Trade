"""NIFTY 50 constituent universe."""

import csv
import io
import requests


NIFTY50_CSV_URL = (
    "https://nsearchives.nseindia.com/"
    "content/indices/ind_nifty50list.csv"
)


def load_nifty50_symbols():
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv,*/*",
    }

    response = requests.get(
        NIFTY50_CSV_URL,
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()

    reader = csv.DictReader(
        io.StringIO(response.text)
    )

    symbols = {
        row["Symbol"].strip().upper()
        for row in reader
        if row.get("Symbol")
    }

    if len(symbols) != 50:
        raise RuntimeError(
            f"Expected 50 NIFTY constituents; received {len(symbols)}."
        )

    return sorted(symbols)