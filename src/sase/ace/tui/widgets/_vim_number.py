"""Pure helpers for Vim-style number increment/decrement commands."""

from __future__ import annotations

import re
from dataclasses import dataclass


_NUMBER_RE = re.compile(r"-?\d+")


@dataclass(frozen=True, slots=True)
class _NumberChange:
    """A planned replacement for one numeric span in prompt text."""

    start: int
    end: int
    new_text: str
    new_cursor: int


def compute_number_change(text: str, cursor: int, delta: int) -> _NumberChange | None:
    """Return the Vim-style number change at/after *cursor*, wrapping to top."""
    matches = list(_NUMBER_RE.finditer(text))
    if not matches:
        return None

    match = next((candidate for candidate in matches if candidate.end() > cursor), None)
    if match is None:
        match = matches[0]

    original = match.group()
    value = int(original)
    new_value = value + delta

    original_digits = original[1:] if original.startswith("-") else original
    digits = str(abs(new_value))
    if len(original_digits) > 1 and original_digits.startswith("0"):
        digits = digits.zfill(len(original_digits))

    sign = "-" if new_value < 0 else ""
    new_text = f"{sign}{digits}"
    return _NumberChange(
        start=match.start(),
        end=match.end(),
        new_text=new_text,
        new_cursor=match.start() + len(new_text) - 1,
    )


__all__ = ["compute_number_change"]
