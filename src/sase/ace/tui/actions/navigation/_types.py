"""Type definitions and base class for navigation mixin."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from .jump_hints import (
    AgentJumpAnchor,
    BannerJumpTarget,
    EntryJumpAnchor,
    PanelJumpTarget,
)

if TYPE_CHECKING:
    from ....patch import Patch
    from ....query.types import QueryExpr
    from ....query_history import QueryHistoryStacks
    from ....query_record import QueryRecord
    from ...bgcmd import BackgroundCommandInfo
    from ...keymaps import KeymapRegistry
    from ...modals import JumpAllResult
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_panels import AgentPanelGroup
    from ...models.fold_state import FoldLevel
    from ...models.fold_state import SectionFoldStateManager
    from ...widgets.bgcmd_list import AxeItem
    from ...widgets.artifacts import ArtifactEntryTarget, ArtifactsPaneKey
    from sase.core.artifact_relation_layout import RelationKeymap
    from ...widgets.prompt_panel._member_roster import MemberJumpMap
    from ..axe_display._loaders import AxeItemKey

# Type alias for axe view: "axe" for daemon view, int for bgcmd slot (1-9)
AxeViewType = Literal["axe"] | int

# Type alias for tab names
TabName = Literal["artifacts", "agents", "axe"]


class NavigationMixinBase:
    """Base class with type hints for attributes accessed from AceApp."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
    current_idx: int
    current_attempt_number: int | None
    current_tab: TabName
    _last_input_action: str | None
    hooks_collapsed: FoldLevel
    stitches_collapsed: FoldLevel
    mentors_collapsed: FoldLevel
    timestamps_collapsed: FoldLevel
    deltas_collapsed: FoldLevel
    panel_fold_level: FoldLevel
    _agents: list[Agent]
    _group_fold_registry: AgentGroupFoldRegistry
    _current_group_key: tuple[str, ...] | None
    _fold_mode_active: bool
    _panel_fold_overrides: SectionFoldStateManager
    _member_jump_maps: dict[tuple[Any, ...], MemberJumpMap]
    _member_jump_pending_digit: str | None
    _member_jump_pending_container_identity: tuple[Any, ...] | None
    _patches_last_idx: int
    _patches_last_name: str | None
    _agents_last_idx: int
    _agents_last_identity: tuple[Any, ...] | None  # AgentType / str / str|None tuple
    _keymap_registry: KeymapRegistry
    _axe_pinned_to_bottom: bool
    _axe_last_idx: int
    _axe_last_item_key: AxeItemKey | None
    _ancestor_mode_active: bool
    _child_mode_active: bool
    _sibling_mode_active: bool
    _entry_jump_mode_active: bool
    _entry_jump_hint_to_target: dict[str, object]
    _entry_jump_pending_prefix: str
    _entry_jump_hint_to_index: dict[str, int]
    _entry_jump_index_to_hint: dict[int, str]
    _entry_jump_index_stack: dict[str, list[EntryJumpAnchor]]
    _entry_jump_forward_index_stack: dict[str, list[EntryJumpAnchor]]
    # Agents-tab jump-mode state for banner targets.  Agent targets are
    # tracked through ``_entry_jump_hint_to_index`` / ``_entry_jump_index_to_hint``
    # (their key is the global agent index); banners need a richer key
    # because two banners in different panels can share a ``group_key``.
    _entry_jump_hint_to_banner: dict[str, BannerJumpTarget]
    _entry_jump_banner_to_hint: dict[BannerJumpTarget, str]
    _entry_jump_hint_to_panel: dict[str, PanelJumpTarget]
    _entry_jump_panel_to_hint: dict[PanelJumpTarget, str]
    # Patches-tab banner jump-hint maps (grouped mode only).  Banner key is
    # the tuple group identity; Patches have no panel scope.
    _entry_jump_hint_to_patch_banner: dict[str, tuple[str, ...]]
    _entry_jump_patch_banner_to_hint: dict[tuple[str, ...], str]
    _current_patch_group_key: tuple[str, ...] | None
    # Back-jump anchors for the agents tab distinguish agent rows, in-panel
    # group banners, and stable-key collapsed whole-panel headers.
    _entry_jump_agents_anchor_stack: list[AgentJumpAnchor]
    _entry_jump_agents_forward_anchor_stack: list[AgentJumpAnchor]
    _artifacts_jump_mode_subtab: ArtifactsPaneKey | None
    _artifacts_jump_pending_prefix: str
    _artifacts_jump_hint_to_target: dict[str, ArtifactEntryTarget]
    _artifacts_jump_target_to_hint: dict[ArtifactEntryTarget, str]
    _artifacts_jump_history: dict[ArtifactsPaneKey, ArtifactEntryTarget]
    _jump_all_last_position: JumpAllResult | None
    _child_key_buffer: str
    _relation_keymap: RelationKeymap
    _all_patches: list[Patch]
    _query_history: dict[str, QueryHistoryStacks]
    _saved_queries: dict[str, dict[str, QueryRecord]]
    query_string: str
    parsed_query: QueryExpr
    _axe_current_view: AxeViewType
    _axe_items: list[AxeItem]
    _bgcmd_slots: list[tuple[int, BackgroundCommandInfo]]
    _panel_group: AgentPanelGroup
