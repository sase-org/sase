"""Shared typed failures for incomplete indexed lookups."""

from __future__ import annotations


class IndexLookupUnavailable(RuntimeError):
    """A bounded index lookup could not prove a complete answer."""

    def __init__(
        self,
        message: str,
        *,
        availability: str,
        source: str,
        diagnostic: str | None,
        truncated: bool = False,
    ) -> None:
        self.availability = availability
        self.source = source
        self.diagnostic = diagnostic
        self.truncated = truncated
        super().__init__(message)

    @property
    def transient(self) -> bool:
        """Whether waiting for a busy index may make the lookup succeed."""
        return self.availability == "busy"
