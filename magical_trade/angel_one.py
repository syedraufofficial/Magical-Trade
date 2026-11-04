
"""Read-only Angel One SmartAPI adapter."""

import os

from magical_trade.market_data import parse_smartapi_quote


class AngelOneAdapter:
    def __init__(self, credentials=None):
        self.credentials = credentials or {}
        self.connected = False
        self.client = None

    def _credential(self, name):
        return self.credentials.get(name) or os.getenv(name)

    def connect(self):
        api_key = self._credential("ANGEL_API_KEY")
        client_code = self._credential("ANGEL_CLIENT_CODE")
        pin = self._credential("ANGEL_PIN")
        totp_secret = self._credential("ANGEL_TOTP_SECRET")

        if not all([api_key, client_code, pin, totp_secret]):
            raise RuntimeError("Angel One credentials are missing from Streamlit Secrets.")

        try:
            import pyotp
            from SmartApi import SmartConnect

            client = SmartConnect(api_key=api_key)
            totp = pyotp.TOTP(totp_secret).now()

            response = client.generateSession(client_code, pin, totp)

            if not isinstance(response, dict) or response.get("status") is not True:
                raise RuntimeError("Angel One authentication failed.")

            self.client = client
            self.connected = True
            return True

        except RuntimeError:
            self.client = None
            self.connected = False
            raise
        except Exception:
            self.client = None
            self.connected = False
            raise RuntimeError(
                "Angel One connection failed. Check credentials and SDK setup."
            ) from None

    def get_ltp_quote(self, exchange, symbol, token):
        if not self.connected or self.client is None:
            raise RuntimeError("Connect to Angel One first.")

        if not all([exchange, symbol, token]):
            raise ValueError("Exchange, symbol and token are required.")

        try:
            response = self.client.ltpData(exchange, symbol, str(token))

            if not isinstance(response, dict) or response.get("status") is not True:
                raise RuntimeError("Angel One quote request failed.")

            quote_data = response.get("data")
            if not isinstance(quote_data, dict):
                raise RuntimeError("Invalid quote response.")

            return parse_smartapi_quote(
                {"data": {"fetched": [quote_data]}},
                requested_symbol=symbol,
            )

        except (ValueError, RuntimeError):
            raise
        except Exception:
            raise RuntimeError("Unable to fetch Angel One quote.") from None

    def get_market_snapshot(self, symbol, exchange, token):
        return self.get_ltp_quote(exchange, symbol, token)
