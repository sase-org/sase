"""Helpers for adaptive jump-to-entry hint assignment and matching."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from ...models.agent_panels import PanelKey
from ...widgets.artifacts.entry_navigation import ArtifactEntryTarget

JUMP_HINT_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
JUMP_HINT_CAPACITY = len(JUMP_HINT_CHARS) ** 2

#: Reserved command keys the pager binds to a verb (``q`` close, ``j``/``k``
#: scroll, ``g``/``G`` top/bottom, ``y`` copy, ``E`` edit, ``r`` refresh,
#: ``n``/``N`` search next/prev). Named once so the viewer's bindings and the
#: prefix-free allocator below can never drift apart.
PAGER_RESERVED_JUMP_COMMAND_KEYS: frozenset[str] = frozenset("qjkgGyErnN")


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
    Literal[
        "patch_banner",
        "changespec_banner",  # legacy compatibility alias
    ],
    tuple[str, ...],
]
#: Shared Artifacts banner anchor: any pane's collapsed grouping banner,
#: identified by pane id plus its stable group key.  Files/Plans/Stitches
#: banners already flow through ``ArtifactEntryTarget`` (their marker is
#: baked into ``parts``) via the newer per-pane jump-history in
#: ``artifacts_navigation.py``, so this variant exists for parity with
#: ``PatchBannerJumpAnchor`` in the shared vocabulary rather than because an
#: existing consumer constructs it today.
ArtifactBannerJumpAnchor = tuple[Literal["artifact_banner"], str, tuple[str, ...]]
#: ``int`` anchors are AXE's flat-list row index; Patches rows use the
#: stable ``ArtifactEntryTarget`` identity instead so marks/anchors survive
#: reorder and reload; collapsed Patch banners keep their own typed anchor.
EntryJumpAnchor = (
    int | ArtifactEntryTarget | PatchBannerJumpAnchor | ArtifactBannerJumpAnchor
)


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
    *,
    excluded: frozenset[str] = frozenset(),
    prefix_free: bool = False,
) -> tuple[dict[str, T], dict[T, str]]:
    """Build hint maps for visible entries.

    Fixed-width mode (the default, unchanged for every existing caller):
    sessions with at most 62 targets use compact one-character base-62
    hints; larger sessions use two-character hints and truncate after
    ``ZZ``.

    ``prefix_free=True`` switches to variable-width allocation over
    ``JUMP_HINT_CHARS`` minus ``excluded``: single-character labels are
    assigned first, and only the minimum number of trailing alphabet
    characters needed to cover every target are reserved as two-character
    prefixes. A reserved prefix character is never itself a complete label,
    so matching stays prefix-free and untimed — no reserved prefix can ever
    collide with a single-key label the way fixed-width labels collide once
    a session crosses 62 targets.
    """
    alphabet = "".join(char for char in JUMP_HINT_CHARS if char not in excluded)
    if prefix_free:
        hints = _prefix_free_hint_sequence(len(targets), alphabet=alphabet)
    else:
        width = 1 if len(targets) <= len(alphabet) else 2
        capacity = len(alphabet) if width == 1 else len(alphabet) ** 2
        hints = [
            _jump_hint_for_index(index, alphabet=alphabet, width=width)
            for index in range(min(len(targets), capacity))
        ]
    hint_to_target: dict[str, T] = {}
    target_to_hint: dict[T, str] = {}
    for hint, target in zip(hints, targets, strict=False):
        hint_to_target[hint] = target
        target_to_hint[target] = hint
    return hint_to_target, target_to_hint


def _minimum_prefix_reservation(target_count: int, alphabet_size: int) -> int:
    """Return the fewest trailing alphabet characters reserved as prefixes.

    ``k`` reserved characters combined with the full alphabet as a second
    character yield ``alphabet_size + k * (alphabet_size - 1)`` total labels
    -- ``alphabet_size - k`` single-character labels plus ``k * alphabet_size``
    two-character ones. Returns the smallest ``k`` whose capacity covers
    ``target_count``.
    """
    if target_count <= alphabet_size or alphabet_size < 2:
        return 0
    reserved = 1
    while alphabet_size + reserved * (alphabet_size - 1) < target_count:
        reserved += 1
    return reserved


def _prefix_free_hint_sequence(count: int, *, alphabet: str) -> list[str]:
    """Return *count* prefix-free labels, single-key first, in order."""
    size = len(alphabet)
    reserved = _minimum_prefix_reservation(count, size)
    single_char_labels = alphabet[: size - reserved]
    hints = list(single_char_labels[:count])
    if len(hints) >= count:
        return hints
    for prefix_char in alphabet[size - reserved :]:
        for char in alphabet:
            hints.append(f"{prefix_char}{char}")
            if len(hints) == count:
                return hints
    return hints


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


def _jump_hint_for_index(
    index: int, *, alphabet: str = JUMP_HINT_CHARS, width: int
) -> str:
    """Encode ``index`` in the given base-N alphabet at fixed width."""
    if width == 1:
        return alphabet[index]
    quotient, remainder = divmod(index, len(alphabet))
    return f"{alphabet[quotient]}{alphabet[remainder]}"
