"""Helpers for adaptive jump-to-entry hint assignment and matching."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from ...models.agent_panels import PanelKey

JUMP_HINT_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
JUMP_HINT_CAPACITY = len(JUMP_HINT_CHARS) ** 2


class JumpHintMatchOutcome(StrEnum):
    """Possible results from one generated-hint keypress."""

    PENDING = "pending"
    COMPLETE = "complete"
    INVALID = "invalid"


@dataclass(frozen=True)
class _JumpHintMatch[T]:
    """Result of matching one key against an optional pending prefix."""

    outcome: JumpHintMatchOutcome
    prefix: str = ""
    target: T | None = None


# Agents-tab jump targets distinguish a global agent index, a panel-scoped
# banner identity, and a stable-key panel header. Patches and AXE
# tabs continue to pass plain ints — the generic map builder accepts hashables.
AgentJumpTarget = tuple[Literal["agent"], int]
BannerJumpTarget = tuple[Literal["banner"], int, tuple[str, ...]]
PanelJumpTarget = tuple[Literal["panel"], PanelKey]
JumpTarget = AgentJumpTarget | BannerJumpTarget | PanelJumpTarget
AgentJumpAnchor = (
    tuple[Literal["agent"], int, PanelKey]
    | tuple[Literal["banner"], PanelKey, tuple[str, ...]]
    | PanelJumpTarget
)
PatchBannerJumpAnchor = tuple[
    Literal["patch_banner", "changespec_banner"], tuple[str, ...]
]
EntryJumpAnchor = int | PatchBannerJumpAnchor


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
    """Build fixed-width hint maps for visible entries.

    Sessions with at most 62 targets use compact one-character base-62 hints.
    Larger sessions use two-character hints and truncate after ``ZZ``.
    """
    hint_to_target: dict[str, T] = {}
    target_to_hint: dict[T, str] = {}
    width = 1 if len(targets) <= len(JUMP_HINT_CHARS) else 2
    for index, target in enumerate(targets[:JUMP_HINT_CAPACITY]):
        hint = _jump_hint_for_index(index, width=width)
        hint_to_target[hint] = target
        target_to_hint[target] = hint
    return hint_to_target, target_to_hint


def match_jump_hint[T](
    hint_to_target: Mapping[str, T],
    pending_prefix: str,
    key: str,
) -> _JumpHintMatch[T]:
    """Match ``key`` against a generated hint map without mutating state."""
    candidate = f"{pending_prefix}{key}"
    if candidate in hint_to_target:
        return _JumpHintMatch(
            JumpHintMatchOutcome.COMPLETE,
            target=hint_to_target[candidate],
        )
    if any(hint.startswith(candidate) for hint in hint_to_target):
        return _JumpHintMatch(JumpHintMatchOutcome.PENDING, prefix=candidate)
    return _JumpHintMatch(JumpHintMatchOutcome.INVALID)


def _jump_hint_for_index(index: int, *, width: int) -> str:
    """Encode ``index`` in the canonical base-62 alphabet at fixed width."""
    if width == 1:
        return JUMP_HINT_CHARS[index]
    quotient, remainder = divmod(index, len(JUMP_HINT_CHARS))
    return f"{JUMP_HINT_CHARS[quotient]}{JUMP_HINT_CHARS[remainder]}"
