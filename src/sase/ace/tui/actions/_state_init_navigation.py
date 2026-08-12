"""Mode and navigation state initialized before the ACE TUI mounts."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from textual.worker import Worker

if TYPE_CHECKING:
    from ..models.agent import AgentType
    from ..tools.report import SlowToolCallReportSpec
    from ..widgets.prompt_panel._agent_display_state import (
        AgentHintRender,
        CommitViewSpec,
    )
    from .navigation._types import JumpAllResult
    from sase.core.query_corpus_facade import QueryCorpus


def init_navigation_state(self: Any) -> None:
    """Initialize interaction modes, jump maps, and patch navigation state."""
    # Hint mode state
    self._hint_mode_active = False
    self._hint_mode_hints_for = None  # None/"all" or "hooks_latest_only"
    self._hint_mappings = {}
    self._hint_tool_call_reports = {}
    self._hint_commit_views = {}
    self._hook_hint_to_idx = {}
    self._hint_to_entry_id = {}
    self._hint_patch_name = ""
    self._hint_changespec_name = ""  # legacy compatibility alias
    self._agent_hint_render_session = 0
    self._agent_hint_render_identity = None
    self._agent_hint_render_ready = None
    self._agent_hint_render_task = None

    # Accept mode state
    self._accept_mode_active = False
    self._accept_last_base = None

    # Rewind mode state
    self._rewind_mode_active = False

    # Fold mode state (for z key sub-command)
    self._fold_mode_active = False

    # Checkout mode state (for c key sub-commands)
    self._checkout_mode_active = False

    # Saved query mode state (for 0 key sub-commands)
    self._saved_query_mode_active = False

    # Copy mode state (for % key sub-commands)
    self._copy_mode_active = False

    # Last input timestamp used to defer non-urgent background work.
    self._last_input_mono = 0.0
    self._last_input_action = None
    # Stable widget refs cached during ``on_mount`` so hot paths (j/k
    # navigation, debounced detail refresh, mark toggle) skip repeated
    # ``query_one`` walks against the DOM. ``None`` until mount runs;
    # callers must fall back to ``query_one`` while these are unset
    # (e.g. tests that exercise mixin methods without mounting).
    self._w_patch_list = None
    self._w_patch_detail = None
    self._w_ancestors_children = None
    self._w_patch_info_panel = None
    self._w_footer = None
    self._w_search_query_panel = None
    self._w_agent_detail = None
    self._w_agent_info_panel = None
    self._w_tab_bar = None

    # Cached graph index over ``_all_patches``; rebuilt only when the
    # list identity changes (see ``_get_patch_graph_index``).
    self._patch_graph_index = None
    self._patch_graph_index_for_id = None

    # Leader mode state (for , key sub-commands)
    self._leader_mode_active = False
    self._last_leader_key = None

    # Bang mode state (for ! key sub-commands)
    self._bang_mode_active = False

    # Beads external issue mode state (for b key sub-commands)
    self._bead_issue_mode_active = False

    # Axe worker state (for background start/stop)
    self._axe_worker = None
    self._axe_worker_operation = None

    # Custom mode state (for user-defined prefix-key modes)
    self._custom_mode_active = None

    # Adaptive one- or two-character entry-jump mode state.
    self._entry_jump_mode_active = False
    self._entry_jump_hint_to_target = {}
    self._entry_jump_pending_prefix = ""
    self._entry_jump_hint_to_index = {}
    self._entry_jump_index_to_hint = {}
    # Agents-tab banner targets (kept in their own maps so the int-keyed
    # agent maps above can stay shared with Patches / AXE tabs).
    from .navigation.jump_hints import (
        AgentJumpAnchor,
        BannerJumpTarget,
        EntryJumpAnchor,
        PanelJumpTarget,
    )

    self._entry_jump_hint_to_banner = {}
    self._entry_jump_banner_to_hint = {}
    self._entry_jump_hint_to_panel = {}
    self._entry_jump_panel_to_hint = {}

    # Patches-tab banner jump-hint maps for grouped mode.  Banner identity
    # is the group key tuple — there's no panel scope on Patches so the
    # tuple alone is sufficient.  Empty in flat mode and on tabs that
    # don't render banner rows.
    self._entry_jump_hint_to_patch_banner = {}
    self._entry_jump_patch_banner_to_hint = {}

    # Entry jump-stack state. Non-Agents tabs keep per-tab row/banner
    # anchor stacks; the Agents tab uses richer anchors so panel and
    # banner focus can be restored.
    self._entry_jump_index_stack = {}
    self._entry_jump_forward_index_stack = {}
    self._entry_jump_last_panel = {}
    self._entry_jump_agents_anchor_stack = []
    self._entry_jump_agents_forward_anchor_stack = []

    # Non-PR Artifacts panes use stable row identities rather than app
    # indices. Hint display is transient; back targets persist per pane.
    from ..widgets.artifacts import ArtifactEntryTarget, ArtifactsPaneKey

    self._artifacts_jump_mode_subtab = None
    self._artifacts_jump_pending_prefix = ""
    self._artifacts_jump_hint_to_target = {}
    self._artifacts_jump_target_to_hint = {}
    self._artifacts_jump_history = {}
    self._artifacts_marked_targets = {
        "stitches": set(),
        "beads": set(),
        "ref:plan": set(),
        "files": set(),
    }

    # Cross-tab jump back state (`)
    self._jump_all_last_position = None

    # Ancestor/child/sibling navigation state
    self._ancestor_mode_active = False
    self._child_mode_active = False
    self._sibling_mode_active = False
    self._child_key_buffer = ""  # Buffer for multi-key child sequences
    self._ancestor_keys = {}  # name -> keymap
    self._children_keys = {}  # key -> name (for navigation)
    self._sibling_keys = {}  # key -> name (for sibling navigation)
    from ...patch import Patch

    self._all_patches = []  # Cache for ancestry lookup
    self._query_corpus = None
    self._query_corpus_source_list_id = None
    self._hidden_reverted_count = 0  # Count of filtered reverted Patches
