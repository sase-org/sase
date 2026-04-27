"""Helpers for one-key jump-to-entry hint assignment."""

from __future__ import annotations

from collections.abc import Hashable
from typing import Literal

JUMP_HINT_CHARS = "1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Agents-tab jump targets: either a global agent index or a panel-scoped
# banner identity.  CLs and AXE tabs continue to pass plain ints — the
# generic ``build_jump_hint_maps`` accepts any hashable target.
AgentJumpTarget = tuple[Literal["agent"], int]
BannerJumpTarget = tuple[Literal["banner"], int, tuple[str, ...]]
JumpTarget = AgentJumpTarget | BannerJumpTarget


def normalize_jump_key(key: str, character: str | None = None) -> str:
    """Return the key token used for jump hint dispatch.

    Textual may expose shifted letters as ``event.key == "a"`` with
    ``event.character == "A"``.  Jump hints are case-sensitive, so printable
    hint characters must win over the normalized key name.  Named controls
    such as ``apostrophe`` and ``grave_accent`` keep their key names so
    back-jump behavior is unchanged.
    """
    if character is not None and len(character) == 1 and character in JUMP_HINT_CHARS:
        return character
    return key


def build_jump_hint_maps[T: Hashable](
    targets: list[T],
) -> tuple[dict[str, T], dict[T, str]]:
    """Build hint->target and target->hint mappings for visible entries."""
    hint_to_target: dict[str, T] = {}
    target_to_hint: dict[T, str] = {}
    for hint, target in zip(JUMP_HINT_CHARS, targets, strict=False):
        hint_to_target[hint] = target
        target_to_hint[target] = hint
    return hint_to_target, target_to_hint
