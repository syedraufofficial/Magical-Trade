"""Angel One integration boundary. Credentials and order placement are deliberately absent."""
class AngelOneAdapter:
    def __init__(self):
        self.connected = False

    def connect(self):
        raise NotImplementedError(
            "Broker authentication is not configured. Add a reviewed SmartAPI adapter; "
            "never store API keys, PINs, TOTP seeds or tokens in source control."
        )

    def get_market_snapshot(self, symbol: str):
        raise NotImplementedError("Live market-data adapter is not configured")
