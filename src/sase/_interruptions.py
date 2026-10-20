"""Exception types used to unwind bounded synchronous operations."""

from __future__ import annotations


class PublicationDrainTimedOut(TimeoutError):
    """Raised when a synchronous agent publication drain reaches its deadline."""
