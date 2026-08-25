"""Types and constructors for ACE copy-mode targets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CopyTargetCategory = Literal["Identity", "Location", "Content", "Data", "Actions"]


@dataclass(frozen=True, slots=True)
class CopyTarget:
    """Presentation metadata for one configured copy-mode target."""

    group: str
    target: str
    footer_label: str
    palette_label: str
    category: CopyTargetCategory
    plural_label: str
    accepts_marks: bool = False


def build_copy_target(
    group: str,
    target: str,
    footer_label: str,
    palette_label: str,
    category: CopyTargetCategory,
    plural_label: str,
    *,
    accepts_marks: bool = False,
) -> CopyTarget:
    return CopyTarget(
        group=group,
        target=target,
        footer_label=footer_label,
        palette_label=palette_label,
        category=category,
        plural_label=plural_label,
        accepts_marks=accepts_marks,
    )


__all__ = [
    "CopyTargetCategory",
]
