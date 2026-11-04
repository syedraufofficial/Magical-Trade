
"""Read-only Angel One SmartAPI adapter with diagnostics."""



import os
import logging
from datetime import datetime, timedelta

from magical_trade.market_data import (
    parse_smartapi_quote,
    parse_smartapi_candles,
)

logger = logging.getLogger(__name__)


class AngelOneAdapter:

    def __init__(self, credentials=None):
        self.credentials = credentials or {}
        self.connected = False
        self.client = None

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
                message = message.replace(
                    str(secret), "[REDACTED]"
                )

        return f"{type(exc).__name__}: {message[:400]}"

    # ======================================
    # ANGEL ONE AUTHENTICATION
    # ======================================

    def connect(self):

        self.connected = False
        self.client = None

        api_key = self._credential("ANGEL_API_KEY")
        client_code = self._credential("ANGEL_CLIENT_CODE")
        pin = self._credential("ANGEL_PIN")
        totp_secret = self._credential("ANGEL_TOTP_SECRET")

        if not all([api_key, client_code, pin, totp_secret]):
            raise RuntimeError(
                "Missing Angel One credentials in Streamlit Secrets."
            )

        totp = None

        try:
            import pyotp
            from SmartApi import SmartConnect

            client = SmartConnect(api_key=api_key)

            totp = pyotp.TOTP(totp_secret).now()

            response = client.generateSession(
                client_code,
                pin,
                totp
            )

            if not isinstance(response, dict):
                raise RuntimeError(
                    "Unexpected Angel One login response."
                )

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

    # ======================================
    # LIVE LTP QUOTE
    # ======================================

    def get_ltp_quote(self, exchange, symbol, token):

        if not self.connected or self.client is None:
            raise RuntimeError(
                "Connect to Angel One first."
            )

        if not all([exchange, symbol, token]):
            raise ValueError(
                "Exchange, symbol and token are required."
            )

        try:

            response = self.client.ltpData(
                exchange,
                symbol,
                str(token)
            )

            if not isinstance(response, dict):
                raise RuntimeError(
                    "Invalid Angel One response."
                )

            if response.get("status") is not True:
                raise RuntimeError(
                    "Angel One quote rejected: "
                    + str(response.get("message", "Unknown error"))
                )

            quote_data = response.get("data")

            if not isinstance(quote_data, dict):
                raise RuntimeError(
                    "Angel One returned invalid quote data."
                )

            # Preserve the original response for diagnostics.
            logger.info(
                "Angel One quote fields received: %s",
                sorted(quote_data.keys())
            )

            # Fill identity fields if the SDK omits them.
            normalized_data = dict(quote_data)

            normalized_data.setdefault(
                "tradingSymbol", symbol
            )

            normalized_data.setdefault(
                "symbolToken", str(token)
            )

            logger.info(
                "Quote diagnostics: LTP=%s, Open=%s, "
                "High=%s, Low=%s, Close=%s, Volume=%s",
                normalized_data.get("ltp"),
                normalized_data.get("open"),
                normalized_data.get("high"),
                normalized_data.get("low"),
                normalized_data.get("close"),
                normalized_data.get("volume")
            )

            quote = parse_smartapi_quote(
                {
                    "data": {
                        "fetched": [normalized_data]
                    }
                },
                requested_symbol=symbol
            )

            if quote.token != str(token):
                raise RuntimeError(
                    "Returned instrument token does not match request."
                )

            if quote.ltp <= 0:
                raise RuntimeError(
                    "Angel One returned an invalid LTP."
                )

            return quote

        except (ValueError, RuntimeError):
            raise

        except Exception as exc:

            raise RuntimeError(
                "Angel One quote error: "
                + self._safe_error(exc)
            ) from None



    # ======================================
    # HISTORICAL CANDLE DATA
    # ======================================

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

        intervals = {
            "ONE_MINUTE": 30,
            "THREE_MINUTE": 60,
            "FIVE_MINUTE": 100,
            "TEN_MINUTE": 100,
            "FIFTEEN_MINUTE": 200,
            "THIRTY_MINUTE": 200,
            "ONE_HOUR": 400,
            "ONE_DAY": 2000,
        }

        exchange = str(exchange).upper()
        interval = str(interval).upper()

        if exchange not in {"NSE", "NFO", "BSE", "BFO", "MCX"}:
            raise ValueError("Unsupported exchange.")

        if interval not in intervals:
            raise ValueError("Unsupported candle interval.")

        if not token:
            raise ValueError("Instrument token is required.")

        try:
            start = datetime.strptime(
                fromdate, "%Y-%m-%d %H:%M"
            )
            end = datetime.strptime(
                todate, "%Y-%m-%d %H:%M"
            )

        except (TypeError, ValueError):
            raise ValueError(
                "Dates must use YYYY-MM-DD HH:MM format."
            ) from None

        if start >= end:
            raise ValueError(
                "Start date must be earlier than end date."
            )

        if end - start > timedelta(days=intervals[interval]):
            raise ValueError(
                "Requested date range exceeds the Angel One "
                "limit for this interval."
            )

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
                raise RuntimeError(
                    "Invalid historical API response."
                )

            if response.get("status") is not True:
                raise RuntimeError(
                    "Historical API rejected request: "
                    + str(response.get("message", "Unknown error"))
                )

            candles = parse_smartapi_candles(response)

            logger.info(
                "Historical candles received: %s | %s",
                interval,
                len(candles),
            )

            if not candles:
                logger.warning("No historical candles returned.")

            return candles

        except (ValueError, RuntimeError):
            raise

        except Exception as exc:
            raise RuntimeError(
                "Historical data error: "
                + self._safe_error(exc)
            ) from None

    # ======================================
    # MARKET SNAPSHOT
    # ======================================

    def get_market_snapshot(self, symbol, exchange, token):

        return self.get_ltp_quote(
            exchange,
            symbol,
            token
        )
