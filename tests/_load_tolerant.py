"""Shared timeouts for waits that diagnose hangs under contention."""

from __future__ import annotations


# These waits are deadlock detectors, not speed assertions. Under the contention
# reproducer, a background thread or subprocess can legitimately take tens of
# seconds to reach a state that is effectively immediate on an idle machine.
LOAD_TOLERANT_TIMEOUT = 60.0


__all__ = ["LOAD_TOLERANT_TIMEOUT"]
