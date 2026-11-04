
"""Read-only Angel One SmartAPI adapter.

Credentials are read from environment variables.
This module does not place, modify, or cancel orders.
"""

import os

from magical_trade.market_data import parse_smartapi_quote


class AngelOneAdapter:
    def __init__(self):
        self.connected = False
        self.client = None

    def connect(self):
        api_key = os.getenv("ANGEL_API_KEY")
        client_code = os.getenv("ANGEL_CLIENT_CODE")
        pin = os.getenv("ANGEL_PIN")
        totp_secret = os.getenv("ANGEL_TOTP_SECRET")

        if not all([api_key, client_code, pin, totp_secret]):
            raise RuntimeError(
                "Angel One credentials are missing from environment variables."
            )

        try:
            import pyotp
            from SmartApi import SmartConnect

            client = SmartConnect(api_key=api_key)
            totp = pyotp.TOTP(totp_secret).now()

            response = client.generateSession(
                client_code,
                pin,
                totp,
            )

            if not isinstance(response, dict) or response.get("status") is not True:
                raise RuntimeError("Angel One authentication failed.")

            self.client = client
            self.connected = True
            return True

        except RuntimeError:
            self.connected = False
            self.client = None
            raise
        except Exception:
            self.connected = False
            self.client = None
            raise RuntimeError(
                "Angel One connection failed. Check credentials and SDK setup."
            ) from None

    def get_ltp_quote(self, exchange: str, symbol: str, token: str):
        if not self.connected or self.client is None:
            raise RuntimeError("Connect to Angel One before requesting quotes.")

        if not all([exchange, symbol, token]):
            raise ValueError("Exchange, symbol and token are required.")

        try:
            response = self.client.ltpData(
                exchange,
                symbol,
                str(token),
            )

            if not isinstance(response, dict) or response.get("status") is not True:
                raise RuntimeError("Angel One quote request failed.")

            quote_data = response.get("data")

            if not isinstance(quote_data, dict):
                raise RuntimeError("Angel One returned an invalid quote.")

            normalized = {
                "data": {
                    "fetched": [quote_data]
                }
            }

            return parse_smartapi_quote(
                normalized,
                requested_symbol=symbol,
            )

        except (ValueError, RuntimeError):
            raise
        except Exception:
            raise RuntimeError(
                "Unable to fetch the Angel One market quote."
            ) from None

    def get_market_snapshot(self, symbol: str, exchange: str, token: str):
        """Compatibility method; returns a validated market quote."""
        return self.get_ltp_quote(exchange, symbol, token)
