"""Environment marker for provider turns owned by host finalizers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os

SASE_FINALIZER_OWNED_TURN_ENV = "SASE_FINALIZER_OWNED_TURN"


@contextmanager
def finalizer_owned_turn() -> Iterator[None]:
    """Mark the current provider invocation as owned by a host finalizer."""

    previous = os.environ.get(SASE_FINALIZER_OWNED_TURN_ENV)
    os.environ[SASE_FINALIZER_OWNED_TURN_ENV] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(SASE_FINALIZER_OWNED_TURN_ENV, None)
        else:
            os.environ[SASE_FINALIZER_OWNED_TURN_ENV] = previous


__all__ = [
    "SASE_FINALIZER_OWNED_TURN_ENV",
    "finalizer_owned_turn",
]
