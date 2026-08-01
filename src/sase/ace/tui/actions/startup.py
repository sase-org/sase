"""Startup/mount mixin for the ace TUI app.

``StartupMixin`` is the public mixin imported by ``actions.__init__`` and
``AceApp``. Its implementation is split across focused private mixins so this
module stays as a small composition point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from textual.timer import Timer

from ...query.types import QueryExpr
from ..util.fs_watcher import ArtifactWatcher
from ..util.nav_gate import NavigationGate
from ._startup_common_placeholders import StartupCommonPlaceholdersMixin
from ._startup_history_words import StartupHistoryWordsMixin
from ._startup_loads import StartupLoadsMixin
from ._startup_misspellings import StartupMisspellingsMixin
from ._startup_mount import StartupMountMixin
from ._startup_prompt_catalog import StartupPromptCatalogMixin
from ._startup_watchers import StartupWatchersMixin
from ._state_init import StateInitMixin

if TYPE_CHECKING:
    from .navigation._types import JumpAllResult
    from ..prompt_catalog import PromptCatalogSnapshot
    from ..widgets.prompt_completion import (
        PromptCompletionSettings,
        PromptSpellcheckSettings,
    )
    from ..widgets.xprompt_arg_assist import XPromptAssistEntry
    from sase.history.prompt_placeholders import CommonPlaceholderSourceToken
    from sase.history.prompt_misspellings import MisspellingsSourceToken
    from sase.history.prompt_words import HistoryWordsSourceToken

TabName = Literal["changespecs", "agents", "axe"]


class StartupMixin(
    StateInitMixin,
    StartupHistoryWordsMixin,
    StartupCommonPlaceholdersMixin,
    StartupMisspellingsMixin,
    StartupPromptCatalogMixin,
    StartupLoadsMixin,
    StartupWatchersMixin,
    StartupMountMixin,
):
    """Mixin providing app state initialization and mount-time setup."""

    # Attributes set by ``_init_app_state`` and referenced from other mixins.
    query_string: str
    parsed_query: QueryExpr
    refresh_interval: int
    theme: str
    _current_idx: int
    _current_attempt_number: int | None
    _auto_start_axe: bool
    _restart_axe: bool
    _mounting: bool
    _changespecs_first_load_done: bool
    _agents_first_load_done: bool
    _axe_first_load_done: bool
    _mount_state_loads_done: bool
    _agents_onboarding_launch_targets_available: bool
    _agents_onboarding_launch_targets_refresh_scheduled: bool
    _agents_onboarding_launch_targets_refresh_running: bool
    _agents_onboarding_launch_targets_refresh_pending: bool
    _agents_onboarding_plugins_installed: bool
    _agents_onboarding_plugins_refresh_scheduled: bool
    _agents_onboarding_plugins_refresh_running: bool
    _agents_onboarding_plugins_refresh_pending: bool
    _automatic_update_check_in_flight: bool
    _automatic_update_check_interval_seconds: float
    _automatic_update_check_timer: Timer | None
    _agents_sync_check_interval_seconds: float
    _agents_sync_recompute_interval_seconds: float
    _agents_sync_indicator_enabled: bool
    _agents_sync_check_in_flight: bool
    _agents_sync_revalidation_pending: bool
    _agents_sync_check_timer: Timer | None
    _agents_sync_last_recompute_mono: float
    _refresh_timer: Timer | None
    _countdown_timer: Timer | None
    _countdown_remaining: int
    _last_input_mono: float
    _last_input_action: str | None
    _post_mount_background_loads_started: bool
    _jump_all_last_position: JumpAllResult | None
    _nav_gate: NavigationGate
    _fs_watcher: ArtifactWatcher | None
    _stall_watchdog: Any
    _stall_watchdog_suspend_signals_wired: bool
    _w_changespec_list: Any
    _w_changespec_detail: Any
    _w_ancestors_children: Any
    _w_changespec_info_panel: Any
    _w_footer: Any
    _w_search_query_panel: Any
    _w_agent_detail: Any
    _w_agent_info_panel: Any
    _w_tab_bar: Any
    _saved_queries: dict[str, str]
    _dirty_changespecs: bool
    _dirty_agents: bool
    _dirty_axe: bool
    _dirty_notifications: bool
    _last_full_sanity_refresh: float
    _user_snippets: dict[str, str]
    _snippets_cache: dict[str, str] | None
    _pending_snippet_saves: dict[str, str]
    _prompt_catalog: PromptCatalogSnapshot | None
    _prompt_catalog_generation: int
    _prompt_catalog_rebuild_in_flight: bool
    _prompt_catalog_rebuild_pending: bool
    _prompt_catalog_rebuild_pending_force: bool
    _prompt_catalog_rebuild_pending_config_dirty: bool
    _prompt_catalog_projects: set[str | None]
    _prompt_catalog_token_check_last_mono: float
    _prompt_catalog_assist_entries_cache: dict[
        str | None,
        list[XPromptAssistEntry],
    ]
    _prompt_source_watcher: ArtifactWatcher | None
    _prompt_source_watcher_active: bool
    _prompt_source_watched_projects: set[str | None]
    _prompt_source_debounce_timer: Timer | None
    _prompt_source_debounce_config_dirty: bool
    _prompt_completion_settings: PromptCompletionSettings
    _prompt_spellcheck_settings: PromptSpellcheckSettings
    _history_prompt_words_cache: list[str] | None
    _history_prompt_words_source_token: HistoryWordsSourceToken | None
    _history_prompt_words_rebuild_in_flight: bool
    _history_prompt_words_rebuild_pending: bool
    _common_placeholders_cache: list[str] | None
    _common_placeholders_source_token: CommonPlaceholderSourceToken | None
    _common_placeholders_generation: int
    _common_placeholders_rebuild_in_flight: bool
    _common_placeholders_rebuild_pending: bool
    _misspelled_words_cache: frozenset[str] | None
    _allowed_misspellings_cache: frozenset[str] | None
    _misspellings_source_token: MisspellingsSourceToken | None
    _misspellings_generation: int
    _misspellings_rebuild_in_flight: bool
    _misspellings_rebuild_pending: bool
    _slow_tool_call_threshold_ms: int
