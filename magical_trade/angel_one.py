
"""Read-only Angel One SmartAPI adapter with safe diagnostics."""

import os

from magical_trade.market_data import parse_smartapi_quote


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
                client_code, pin, totp
            )

            if not isinstance(response, dict):
                raise RuntimeError(
                    "Unexpected Angel One login response."
                )

            if response.get("status") is not True:
                code = response.get("errorcode", "")
                detail = response.get("message", "Login rejected")

                raise RuntimeError(
                    f"Angel One rejected login. "
                    f"Code: {code}. Details: {detail}"
                )

            self.client = client
            self.connected = True
            return True

        except Exception as exc:
            self.client = None
            self.connected = False

            raise RuntimeError(
                "Angel One connection failed: "
                + self._safe_error(exc, totp)
            ) from None

    def get_ltp_quote(self, exchange, symbol, token):
        if not self.connected or self.client is None:
            raise RuntimeError("Connect to Angel One first.")

        if not all([exchange, symbol, token]):
            raise ValueError(
                "Exchange, symbol and token are required."
            )

        try:
            response = self.client.ltpData(
                exchange, symbol, str(token)
            )

            if (
                not isinstance(response, dict)
                or response.get("status") is not True
            ):
                detail = (
                    response.get("message", "Quote rejected")
                    if isinstance(response, dict)
                    else "Invalid response"
                )
                raise RuntimeError(detail)

            quote_data = response.get("data")

            if not isinstance(quote_data, dict):
                raise RuntimeError("Invalid quote response.")

            return parse_smartapi_quote(
                {"data": {"fetched": [quote_data]}},
                requested_symbol=symbol,
            )

        except (ValueError, RuntimeError):
            raise

        except Exception as exc:
            raise RuntimeError(
                "Quote error: " + self._safe_error(exc)
            ) from None

    def get_market_snapshot(self, symbol, exchange, token):
        return self.get_ltp_quote(exchange, symbol, token)
