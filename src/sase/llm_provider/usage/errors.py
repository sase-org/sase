"""Exceptions raised by the provider usage store."""


class ProviderUsageStateError(RuntimeError):
    """Raised when provider-usage store state cannot be safely consumed."""


__all__ = ["ProviderUsageStateError"]
