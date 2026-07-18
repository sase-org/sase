"""Late state initialization sections for the ACE startup mixin."""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

from ..models.fold_state import FoldStateManager

log = logging.getLogger(__name__)


def init_late_startup_state(
    self: Any,
    model_tier_override: Literal["large", "small"] | None,
) -> None:
    """Initialize AXE, query persistence, prompt catalog, and keymap state."""
    from ..util.debounce import DetailPanelDebouncer

    self._axe_status = None
    self._axe_metrics = None
    self._axe_output = ""
    self._axe_pinned_to_bottom = True
    self._axe_cmds_hidden = False

    self._axe_current_view = "axe"
    # Set when a chop child row is selected; the render layer uses
    # this to pick the chop-run-detail view rather than the
    # lumberjack overview.
    self._axe_chop_selection = None
    self._bgcmd_slots = []

    # Axe navigation caches: populated by the async collector so that
    # Ctrl+N / Ctrl+P render without touching disk. Empty until the
    # first async load completes (first-paint shows empty placeholders).
    self._axe_lumberjack_statuses = {}
    self._axe_lumberjack_metrics = {}
    self._axe_lumberjack_log_tails = {}
    self._axe_bgcmd_details = {}
    # Per-lumberjack ordered chop-name lists and per-chop snapshots
    # (config metadata + bounded run history) populated by the same
    # async collector so navigation paints chop rows from memory.
    self._axe_lumberjack_chop_names = {}
    self._axe_chop_snapshots = {}
    self._axe_lumberjack_snapshots = {}

    # Per-chop run-history view offset for Ctrl+N / Ctrl+P navigation.
    # 0 == newest. Absent entry means "follow newest" - a newer recorded
    # run keeps the view pinned to offset 0. Once the user moves off the
    # newest (offset > 0), the entry sticks; subsequent newer runs shift
    # what the offset points to but the offset itself is preserved until
    # the user steps back to 0, at which point the entry is removed and
    # the chop returns to auto-following the newest run.
    self._axe_chop_run_offsets = {}

    # Debouncer for axe j/k navigation detail updates.
    self._axe_detail_debouncer = DetailPanelDebouncer(self)
    self._axe_loading_placeholder_shown = False

    # Debouncer for changespecs j/k navigation detail updates.
    self._changespec_detail_debouncer = DetailPanelDebouncer(self)

    # Lumberjack cycling state (new axe architecture)
    self._axe_lumberjack_names = []
    self._axe_lumberjack_idx = None

    self._axe_items = []
    self._axe_last_idx = 0
    self._axe_last_item_key = None
    # Per-lumberjack fold keys ("lumberjack:<name>") are initialized
    # to EXPANDED lazily in ``_build_axe_items`` the first time each
    # lumberjack is seen.
    self._axe_fold_manager = FoldStateManager()

    # Query history stacks for prev/next navigation
    from ...query_history import load_query_history

    self._query_history = load_query_history()

    # Per-query ChangeSpec selection persistence
    from ...query_selection import load_query_selections

    self._query_selections = load_query_selections()

    # Saved-query slots cached in memory.  ``SearchQueryPanel`` reads
    # this on every render so we keep it disk-free; the cache is
    # refreshed by :meth:`_invalidate_saved_queries_cache` on explicit
    # save/delete.
    from ...saved_queries import load_saved_queries

    self._saved_queries = load_saved_queries()

    # Load ACE settings from merged config.
    from sase.config import load_merged_config

    merged = load_merged_config()
    ace_cfg = merged.get("ace", {}) if isinstance(merged, dict) else {}
    updates_cfg = ace_cfg.get("updates", {}) if isinstance(ace_cfg, dict) else {}
    from .update_toast import resolve_check_interval_seconds

    self._automatic_update_check_interval_seconds = resolve_check_interval_seconds(
        updates_cfg if isinstance(updates_cfg, dict) else {}
    )
    self._agents_repro_output_dir = (
        str(ace_cfg.get("repro_output_dir", "")) if isinstance(ace_cfg, dict) else ""
    )
    from ..tools.slow import slow_tool_call_threshold_ms_from_config

    self._slow_tool_call_threshold_ms = slow_tool_call_threshold_ms_from_config(
        ace_cfg if isinstance(ace_cfg, dict) else {}
    )
    from ..widgets.prompt_completion import parse_prompt_completion_settings

    self._prompt_completion_settings = parse_prompt_completion_settings(
        ace_cfg.get("prompt_completion", {}) if isinstance(ace_cfg, dict) else {}
    )
    self._history_prompt_words_cache = None
    self._history_prompt_words_source_token = None
    self._history_prompt_words_rebuild_in_flight = False
    self._history_prompt_words_rebuild_pending = False
    user_snippets: dict[str, str] = (
        ace_cfg.get("snippets", {}) if isinstance(ace_cfg, dict) else {}
    )
    # Defer the xprompt snippet scan (which walks disk-backed xprompt
    # definitions) until the prompt entry / help modal asks for it.
    # Cold startup's first paint never needs snippets, so skipping
    # this on the mount path keeps the stopwatch tight.
    self._user_snippets = dict(user_snippets)
    self._snippets_cache = None
    self._pending_snippet_saves = {}
    self._prompt_catalog = None
    self._prompt_catalog_generation = 0
    self._prompt_catalog_rebuild_in_flight = False
    self._prompt_catalog_rebuild_pending = False
    self._prompt_catalog_rebuild_pending_force = False
    self._prompt_catalog_rebuild_pending_config_dirty = False
    self._prompt_catalog_projects = {None}
    self._prompt_catalog_token_check_last_mono = 0.0
    self._prompt_catalog_assist_entries_cache = {}
    self._prompt_source_watcher = None
    self._prompt_source_watcher_active = False
    self._prompt_source_watched_projects = set()
    self._prompt_source_debounce_timer = None
    self._prompt_source_debounce_config_dirty = False

    # Build keymap registry from config
    from ..keymaps import (
        BUILTIN_MODE_NAMES,
        build_app_bindings,
        key_display_name,
        load_keymap_registry,
    )

    self._keymap_registry = load_keymap_registry(
        ace_cfg if isinstance(ace_cfg, dict) else {}
    )

    # Build prefix->mode_name lookup for custom (non-builtin) modes.
    self._custom_mode_prefixes = {
        mode.prefix: name
        for name, mode in self._keymap_registry.modes.items()
        if name not in BUILTIN_MODE_NAMES and mode.prefix
    }

    # Replace instance bindings with registry-driven bindings.
    from textual.binding import BindingsMap

    _app_bindings = build_app_bindings(self._keymap_registry.app)
    self._bindings = BindingsMap(_app_bindings)
    log.debug(
        "Keymap registry loaded: %d bindings, display=%s",
        len(_app_bindings),
        key_display_name(self._keymap_registry.app.next_changespec),
    )

    # Set global model tier override in environment if specified.
    if model_tier_override:
        os.environ["SASE_MODEL_TIER_OVERRIDE"] = model_tier_override
