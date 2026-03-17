"""Issue ID generation using prefix + base36 counter."""

from __future__ import annotations

import threading

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
_lock = threading.Lock()


# pyvision: tests/test_bead/test_ids.py
def to_base36(n: int) -> str:
    """Convert a non-negative integer to a base36 string."""
    if n < 0:
        raise ValueError("Cannot convert negative number to base36")
    if n == 0:
        return "0"
    digits: list[str] = []
    while n:
        digits.append(_ALPHABET[n % 36])
        n //= 36
    return "".join(reversed(digits))


# pyvision: tests/test_bead/test_ids.py
def from_base36(s: str) -> int:
    """Convert a base36 string to an integer."""
    return int(s, 36)


class IdGenerator:
    """Thread-safe ID generator using prefix + base36 counter."""

    def __init__(self, prefix: str, counter: int = 1) -> None:
        self.prefix = prefix
        self._counter = counter

    @property
    def counter(self) -> int:
        return self._counter

    def next_id(self) -> str:
        """Generate the next issue ID, e.g. 'sase-03v'."""
        with _lock:
            issue_id = f"{self.prefix}-{to_base36(self._counter)}"
            self._counter += 1
            return issue_id
