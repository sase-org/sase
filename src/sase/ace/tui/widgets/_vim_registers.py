"""Vim register helpers for the prompt text area."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VimRegisterKind = Literal["charwise", "linewise"]


@dataclass(frozen=True)
class VimRegister:
    """Internal unnamed Vim register."""

    text: str = ""
    kind: VimRegisterKind = "charwise"


def first_non_blank_col(line: str) -> int:
    """Return the first non-blank column in *line*, or 0 for blank lines."""
    for index, char in enumerate(line):
        if not char.isspace():
            return index
    return 0
