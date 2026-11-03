class LiveTradingDisabled(RuntimeError):
    pass

class LiveExecutionGuard:
    """Fail-closed placeholder. No broker order API is implemented in this release."""
    enabled = False

    def submit(self, *args, **kwargs):
        raise LiveTradingDisabled(
            "Live execution is disabled. This build supports research and paper trading only."
        )
