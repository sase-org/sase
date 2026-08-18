"""Dataclasses for app-level and focused-pane keymaps."""

from dataclasses import dataclass


@dataclass
class AppKeymaps:
    """One field per configurable app-level action.

    No defaults -- all values must come from configuration files
    (``default_config.yml`` or user/plugin overrides). This ensures
    ``default_config.yml`` is the single source of truth for default
    keybindings and that adding a new field without a config entry is
    caught immediately at startup.
    """

    # Navigation
    next_patch: str
    prev_patch: str
    scroll_to_top: str
    scroll_to_bottom: str
    scroll_detail_down: str
    scroll_detail_up: str
    scroll_prompt_down: str
    scroll_prompt_up: str
    next_agent_metadata_section: str
    prev_agent_metadata_section: str
    next_agent_file: str
    prev_agent_file: str
    # Tab switching
    next_tab: str
    prev_tab: str
    cycle_artifacts_subtab: str
    cycle_artifacts_subtab_reverse: str
    # Artifacts split
    cycle_artifacts_split: str
    cycle_artifacts_split_reverse: str
    files_next_version: str
    files_prev_version: str
    pick_artifacts_project: str
    # Stitches sub-tab
    stitches_next: str
    stitches_prev: str
    stitches_view_selected: str
    stitches_filters: str
    stitches_toggle_sdd: str
    stitches_cycle_merges: str
    stitches_toggle_all_projects: str
    stitches_fetch: str
    # Plans sub-tab
    plans_next: str
    plans_prev: str
    plans_view_selected: str
    plans_filters: str
    plans_approve: str
    plans_reject: str
    plans_open_bead: str
    # Beads sub-tab
    beads_next: str
    beads_prev: str
    beads_view_selected: str
    beads_filters: str
    beads_expand: str
    beads_collapse: str
    beads_cycle_status: str
    beads_edit: str
    beads_add_note: str
    beads_create: str
    beads_close: str
    beads_snooze: str
    beads_launch_work: str
    beads_open_bug: str
    start_bead_issue_mode: str
    beads_open_plan: str
    # Files sub-tab
    files_next: str
    files_prev: str
    files_view_selected: str
    files_open_viewer: str
    files_open_external: str
    files_open_agent: str
    files_filters: str
    files_cycle_kind: str
    files_copy_path: str
    # Patch actions
    patches_filters: str
    quit: str
    change_status: str
    run_workflow: str
    mail: str
    show_diff: str
    reword: str
    add_tag: str
    view_files: str
    jump_to_entry: str
    jump_to_entry_fast: str
    jump_to_entry_forward: str
    jump_to_all_entries: str
    edit_spec: str
    add_axe_item: str
    toggle_axe_description: str
    rename_cl: str
    # Patch edits
    edit_hooks: str
    mark_pr_origin: str
    # Proposals & sync
    accept_proposal: str
    rebase: str
    start_rewind: str
    sync: str
    refresh: str
    artifacts_copy_reference: str
    # Fold / collapse
    hooks_or_collapse: str
    hooks_or_collapse_all: str
    expand_or_layout: str
    expand_all_folds: str
    toggle_layout: str
    # Marking
    toggle_mark: str
    clear_marks: str
    bulk_change_status: str
    save_marked_agents: str
    # Agent / axe
    kill_agent: str
    open_agent_cleanup_panel: str
    stop_axe_and_quit: str
    start_custom_agent: str
    start_agent_home: str
    start_agent_from_patch: str
    start_last_vcs_xprompt_in_editor: str
    restore_prompt_stash: str
    jump_to_agent_patch: str
    edit_panel: str
    show_agent_run_log: str
    open_artifact_files: str
    toggle_attempt_view: str
    toggle_agent_unread: str
    edit_agent_tribe: str
    focus_next_agent_panel: str
    focus_prev_agent_panel: str
    # Grouping mode cycle (agents tab)
    cycle_grouping_mode: str
    cycle_grouping_mode_reverse: str
    # Tools panel
    toggle_thinking: str
    toggle_thinking_reverse: str
    # Queries
    search_forward: str
    edit_query: str
    search_reverse: str
    open_saved_query_picker: str
    start_saved_query_mode: str
    prev_query: str
    next_query: str
    # Display / misc
    show_help: str
    toggle_hide_reverted: str
    patches_toggle_reverted: str
    toggle_hide_submitted: str
    show_notifications: str
    open_config_center: str
    open_command_palette: str
    dismiss_toasts: str
    # Workspace mode prefixes
    checkout: str
    start_checkout_mode: str
    open_tmux: str
    start_tmux_mode: str
    # Tree navigation prefixes
    start_ancestor_mode: str
    start_child_mode: str
    start_sibling_mode: str
    toggle_relation_panel: str
    # Mode activation prefixes
    start_fold_mode: str
    zoom_panel: str
    isolate_panels: str
    collapse_panel_folds: str
    start_leader_mode: str
    start_bang_mode: str
    copy_tab_content: str

    @property
    def next_changespec(self) -> str:  # legacy compatibility alias
        """Legacy alias for :attr:`next_patch`."""
        return self.next_patch

    @next_changespec.setter  # legacy compatibility alias
    def next_changespec(self, value: str) -> None:  # legacy compatibility alias
        self.next_patch = value

    @property
    def prev_changespec(self) -> str:  # legacy compatibility alias
        """Legacy alias for :attr:`prev_patch`."""
        return self.prev_patch

    @prev_changespec.setter  # legacy compatibility alias
    def prev_changespec(self, value: str) -> None:  # legacy compatibility alias
        self.prev_patch = value

    @property
    def start_agent_from_changespec(self) -> str:  # legacy compatibility alias
        """Legacy alias for :attr:`start_agent_from_patch`."""
        return self.start_agent_from_patch

    @start_agent_from_changespec.setter  # legacy compatibility alias
    def start_agent_from_changespec(
        self, value: str
    ) -> None:  # legacy compatibility alias
        self.start_agent_from_patch = value

    @property
    def jump_to_agent_changespec(self) -> str:  # legacy compatibility alias
        """Legacy alias for :attr:`jump_to_agent_patch`."""
        return self.jump_to_agent_patch

    @jump_to_agent_changespec.setter  # legacy compatibility alias
    def jump_to_agent_changespec(
        self, value: str
    ) -> None:  # legacy compatibility alias
        self.jump_to_agent_patch = value


@dataclass
class StatisticsPaneKeymaps:
    """Focused-pane actions for the Admin Center Statistics tab."""

    prev_view: str = "left_square_bracket"
    next_view: str = "right_square_bracket"
    select_view: str = "0"
    jump_to_entry: str = "apostrophe"
    cycle_range: str = "t"
    cycle_range_reverse: str = "T"
    custom_range: str = "c"
    cycle_group: str = "g"
    cycle_project_filter: str = "p"
    cycle_project_filter_reverse: str = "P"
    focus_xprompt: str = "x"
    clear_xprompt_focus: str = "X"
    scroll_down: str = "ctrl+d"
    scroll_up: str = "ctrl+u"
    refresh: str = "r"
    help: str = "question_mark"


@dataclass
class GateModalKeymaps:
    """Focused actions shared by plan and custom gate modals."""

    next_control: str = "j"
    previous_control: str = "k"
    toggle_option: str = "space"
    submit_primary: str = "enter"
    submit_branch: str = "ctrl+s"
    open_inputs: str = "i"
    next_input: str = "tab"
    previous_input: str = "shift+tab"


@dataclass
class GlossaryPanelKeymaps:
    """Focused-pane actions for the Glossary panel."""

    next_term: str = "j"
    prev_term: str = "k"
    first_term: str = "g"
    last_term: str = "G"
    scroll_definition_down: str = "ctrl+d"
    scroll_definition_up: str = "ctrl+u"
    filter_terms: str = "slash"
    toggle_definition_filter: str = "full_stop"
    next_relation: str = "tab"
    prev_relation: str = "shift+tab"
    follow_relation: str = "enter,l"
    travel_back: str = "backspace,h"
    next_project: str = "p"
    prev_project: str = "P"
    add_term: str = "a"
    delete_term: str = "d"
    open_source: str = "o"
    open_viewer: str = "Z"
    copy_definition: str = "y"
    copy_source_path: str = "Y"
    refresh: str = "r"
    help: str = "question_mark"
