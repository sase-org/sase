"""Shared option-action type for the capacity inspector modal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class OptionAction:
    """Selectable-row action for the capacity inspector option list."""

    kind: Literal["jump", "toggle_group"]
    detail_kind: str
    row: Any | None = None
    group: Any | None = None
    group_code: str | None = None


__all__ = ["OptionAction"]
