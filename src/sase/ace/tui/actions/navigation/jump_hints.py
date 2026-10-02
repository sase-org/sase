"""Helpers for adaptive jump-to-entry hint assignment and matching."""

from __future__ import annotations

from typing import Any, Literal, TYPE_CHECKING

from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.pager.jump_hints import (
    JUMP_HINT_CAPACITY,
    JUMP_HINT_CHARS,
    JumpHintMatch,
    JumpHintMatchOutcome,
    PAGER_RESERVED_JUMP_COMMAND_KEYS,
    build_jump_hint_maps,
    match_jump_hint,
    normalize_jump_key,
)

if TYPE_CHECKING:
    from ...models.agent_panels import PanelKey

__all__ = [
    "AgentJumpAnchor",
    "AgentJumpTarget",
    "ArtifactBannerJumpAnchor",
    "BannerJumpTarget",
    "EntryJumpAnchor",
    "JUMP_HINT_CAPACITY",
    "JUMP_HINT_CHARS",
    "JumpHintMatch",
    "JumpHintMatchOutcome",
    "JumpTarget",
    "PAGER_RESERVED_JUMP_COMMAND_KEYS",
    "PanelJumpTarget",
    "PatchBannerJumpAnchor",
    "TabJumpTarget",
    "build_jump_hint_maps",
    "match_jump_hint",
    "normalize_jump_key",
]

# Agents-tab jump targets distinguish a global agent index, a panel-scoped
# banner identity, a stable-key panel header, and an agent-tab strip chip.
# Patches and AXE tabs continue to pass plain ints — the generic map
# builder accepts hashables.
AgentJumpTarget = tuple[Literal["agent"], int]
BannerJumpTarget = tuple[Literal["banner"], int, tuple[str, ...]]
PanelJumpTarget = tuple[Literal["panel"], "PanelKey"]
TabJumpTarget = tuple[Literal["tab"], Any]
JumpTarget = AgentJumpTarget | BannerJumpTarget | PanelJumpTarget | TabJumpTarget
AgentJumpAnchor = (
    tuple[Literal["agent"], int, "PanelKey"]
    | tuple[Literal["agent"], int, "PanelKey", str]
    | tuple[Literal["banner"], "PanelKey", tuple[str, ...]]
    | tuple[Literal["banner"], "PanelKey", tuple[str, ...], str]
    | PanelJumpTarget
    | tuple[Literal["panel"], "PanelKey", str]
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
