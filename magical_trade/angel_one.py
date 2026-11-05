
"""Read-only Angel One SmartAPI adapter."""

import logging
import os
from datetime import datetime

from magical_trade.market_data import (
    parse_smartapi_quote,
    parse_smartapi_candles,
    validate_quote_freshness,
)

logger = logging.getLogger(__name__)


class AngelOneAdapter:
    """Read-only market-data adapter. Never submits broker orders."""

    def __init__(self, credentials=None):
        self.credentials = credentials or {}
        self.connected = False
        self.client = None
        self.last_quote_freshness = (False, "No quote received")

    def _credential(self, name):
        return self.credentials.get(name) or os.getenv(name)

    def _safe_error(self, exc, totp=None):
        message = str(exc) or "No additional details."
        secrets = [
            self._credential("ANGEL_API_KEY"),
            self._credential("ANGEL_CLIENT_CODE"),
            self._credential("ANGEL_PIN"),
            self._credential("ANGEL_TOTP_SECRET"),
            totp,
        ]

        for secret in secrets:
            if secret:
                message = message.replace(str(secret), "[REDACTED]")

        return f"{type(exc).__name__}: {message[:400]}"

    def connect(self):
        self.connected = False
        self.client = None

        api_key = self._credential("ANGEL_API_KEY")
        client_code = self._credential("ANGEL_CLIENT_CODE")
        pin = self._credential("ANGEL_PIN")
        totp_secret = self._credential("ANGEL_TOTP_SECRET")

        if not all([api_key, client_code, pin, totp_secret]):
            raise RuntimeError("Missing Angel One credentials.")

        totp = None

        try:
            import pyotp
            from SmartApi import SmartConnect

            client = SmartConnect(api_key=api_key)
            totp = pyotp.TOTP(totp_secret).now()

            response = client.generateSession(
                client_code, pin, totp
            )

            if not isinstance(response, dict):
                raise RuntimeError("Unexpected Angel One login response.")

            if response.get("status") is not True:
                raise RuntimeError(
                    "Angel One login rejected. "
                    f"Code: {response.get('errorcode', 'N/A')}. "
                    f"Message: {response.get('message', 'Unknown')}"
                )

            self.client = client
            self.connected = True
            logger.info("Angel One authentication successful.")
            return True

        except Exception as exc:
            self.client = None
            self.connected = False
            raise RuntimeError(
                "Angel One authentication failed: "
                + self._safe_error(exc, totp)
            ) from None

    def get_ltp_quote(self, exchange, symbol, token):
        if not self.connected or self.client is None:
            raise RuntimeError("Connect to Angel One first.")

        if not all([exchange, symbol, token]):
            raise ValueError("Exchange, symbol and token are required.")

        try:
            response = self.client.ltpData(
                str(exchange).upper(),
                str(symbol),
                str(token),
            )

            if not isinstance(response, dict):
                raise RuntimeError("Invalid Angel One quote response.")

            if response.get("status") is not True:
                raise RuntimeError(
                    "Angel One quote rejected: "
                    + str(response.get("message", "Unknown error"))
                )

            quote_data = response.get("data")
            if not isinstance(quote_data, dict):
                raise RuntimeError("Angel One returned invalid quote data.")

            normalized = dict(quote_data)
            normalized.setdefault("tradingSymbol", str(symbol))
            normalized.setdefault("symbolToken", str(token))

            quote = parse_smartapi_quote(
                {"data": {"fetched": [normalized]}},
                requested_symbol=str(symbol),
            )

            if quote.token != str(token):
                raise RuntimeError("Returned instrument token mismatch.")

            self.last_quote_freshness = validate_quote_freshness(quote)

            logger.info(
                "Quote received for %s; freshness=%s",
                symbol,
                self.last_quote_freshness[0],
            )
            return quote

        except (ValueError, RuntimeError):
            raise
        except Exception as exc:
            raise RuntimeError(
                "Angel One quote error: " + self._safe_error(exc)
            ) from None

    def is_quote_safe_for_paper(self):
        """True only when the latest quote has a fresh exchange timestamp."""
        return self.last_quote_freshness[0]

    def get_quote_freshness(self):
        """Return (is_fresh, explanation) for the latest quote."""
        return self.last_quote_freshness

    def get_historical_candles(
        self,
        exchange,
        token,
        fromdate,
        todate,
        interval="FIVE_MINUTE",
    ):
        if not self.connected or self.client is None:
            raise RuntimeError("Connect to Angel One first.")

        exchange = str(exchange).upper()
        interval = str(interval).upper()

        if exchange not in {"NSE", "NFO", "BSE", "BFO", "MCX"}:
            raise ValueError("Unsupported exchange.")

        allowed_intervals = {
            "ONE_MINUTE", "THREE_MINUTE", "FIVE_MINUTE",
            "TEN_MINUTE", "FIFTEEN_MINUTE", "THIRTY_MINUTE",
            "ONE_HOUR", "ONE_DAY",
        }
        if interval not in allowed_intervals:
            raise ValueError("Unsupported candle interval.")

        if not token:
            raise ValueError("Instrument token is required.")

        try:
            start = datetime.strptime(fromdate, "%Y-%m-%d %H:%M")
            end = datetime.strptime(todate, "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            raise ValueError(
                "Dates must use YYYY-MM-DD HH:MM format."
            ) from None

        if start >= end:
            raise ValueError("Start date must be earlier than end date.")

        params = {
            "exchange": exchange,
            "symboltoken": str(token),
            "interval": interval,
            "fromdate": start.strftime("%Y-%m-%d %H:%M"),
            "todate": end.strftime("%Y-%m-%d %H:%M"),
        }

        try:
            response = self.client.getCandleData(params)

            if not isinstance(response, dict):
                raise RuntimeError("Invalid historical API response.")

            if response.get("status") is not True:
                raise RuntimeError(
                    "Historical API rejected request: "
                    + str(response.get("message", "Unknown error"))
                )

            candles = parse_smartapi_candles(response)
            logger.info("Historical candles received: %s", len(candles))
            return candles

        except (ValueError, RuntimeError):
            raise
        except Exception as exc:
            raise RuntimeError(
                "Historical data error: " + self._safe_error(exc)
            ) from None

    def get_market_snapshot(self, symbol, exchange, token):
        return self.get_ltp_quote(exchange, symbol, token)
