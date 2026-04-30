"""Command catalog construction for the ace TUI palette.

Builds a single source-of-truth list of :class:`CommandSpec` entries
from a :class:`KeymapRegistry`.  Coverage:

- Every field in :class:`AppKeymaps` (one ``app.<field>`` command).
- The 10 saved-query digit bindings ``0``..``9``.
- Every key in each built-in mode (fold / copy nested per-tab /
  leader / bang).
- Every valid user-defined custom mode command.

The catalog is the input the palette filters and the applicability
module scopes; it must stay in sync with :class:`AppKeymaps`. A
guard in :func:`iter_app_commands` raises :class:`RuntimeError` if
an ``AppKeymaps`` field is missing app-command metadata so this can
never silently drift.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import fields
from typing import TYPE_CHECKING

from sase.ace.tui.commands.types import (
    CATEGORY_ORDER,
    CommandCategory,
    CommandExecutor,
    CommandSpec,
    CommandTab,
)
from sase.ace.tui.keymaps.loader import key_display_name
from sase.ace.tui.keymaps.types import (
    BUILTIN_MODE_NAMES,
    AppKeymaps,
)

if TYPE_CHECKING:
    from sase.ace.tui.keymaps import KeymapRegistry


_ALL_TABS: tuple[CommandTab, ...] = ("changespecs", "agents", "axe")
_CL_ONLY: tuple[CommandTab, ...] = ("changespecs",)
_AGENTS_ONLY: tuple[CommandTab, ...] = ("agents",)
_AGENTS_AXE: tuple[CommandTab, ...] = ("agents", "axe")
_CL_AGENTS: tuple[CommandTab, ...] = ("changespecs", "agents")


# ---------------------------------------------------------------------------
# App command metadata
# ---------------------------------------------------------------------------
#
# (action, label, category, tabs, aliases).  Action name MUST match an
# AppKeymaps field. Labels are tuned for the palette; categories mirror
# the help modal sections; tabs encode where the binding can ever fire
# (entry-level applicability is layered on by ``availability.py``).

_APP_COMMAND_META: tuple[
    tuple[str, str, CommandCategory, tuple[CommandTab, ...], tuple[str, ...]],
    ...,
] = (
    # Navigation
    ("next_changespec", "Next entry", "Navigation", _ALL_TABS, ("down", "j")),
    ("prev_changespec", "Previous entry", "Navigation", _ALL_TABS, ("up", "k")),
    ("scroll_to_top", "Scroll to top", "Navigation", _ALL_TABS, ("g",)),
    ("scroll_to_bottom", "Scroll to bottom", "Navigation", _ALL_TABS, ("G",)),
    ("scroll_detail_down", "Scroll detail down", "Navigation", _ALL_TABS, ()),
    ("scroll_detail_up", "Scroll detail up", "Navigation", _ALL_TABS, ()),
    ("scroll_prompt_down", "Scroll prompt down", "Navigation", _AGENTS_ONLY, ()),
    ("scroll_prompt_up", "Scroll prompt up", "Navigation", _AGENTS_ONLY, ()),
    (
        "prev_changespec_history",
        "Previous CL in history",
        "Navigation",
        _CL_ONLY,
        ("history",),
    ),
    (
        "next_changespec_history",
        "Next CL in history",
        "Navigation",
        _CL_ONLY,
        ("history",),
    ),
    ("next_agent_file", "Next agent file", "Navigation", _AGENTS_ONLY, ()),
    ("prev_agent_file", "Previous agent file", "Navigation", _AGENTS_ONLY, ()),
    ("jump_to_entry", "Jump to entry", "Navigation", _ALL_TABS, ("hint",)),
    ("jump_to_all_entries", "Jump to any entry", "Navigation", _ALL_TABS, ("hint",)),
    # Tab switching
    ("next_tab", "Next tab", "Tabs", _ALL_TABS, ()),
    ("prev_tab", "Previous tab", "Tabs", _ALL_TABS, ()),
    # CL Actions
    ("quit", "Quit ace", "Misc", _ALL_TABS, ("exit",)),
    ("change_status", "Change CL status", "CL Actions", _CL_ONLY, ()),
    ("run_workflow", "Run workflow / resume / re-run", "CL Actions", _ALL_TABS, ()),
    ("mail", "Mail CL", "CL Actions", _CL_ONLY, ("send",)),
    ("show_diff", "Show diff", "CL Actions", _CL_ONLY, ()),
    ("reword", "Reword CL", "CL Actions", _CL_ONLY, ()),
    ("add_tag", "Add tag", "CL Actions", _CL_ONLY, ()),
    ("view_files", "View CL files", "CL Actions", _CL_ONLY, ()),
    ("edit_spec", "Edit spec / chat", "CL Actions", _ALL_TABS, ()),
    ("rename_cl", "Rename CL / agent", "CL Actions", _CL_AGENTS, ()),
    # ChangeSpec edits
    ("edit_hooks", "Edit hooks file", "ChangeSpec Edits", _CL_ONLY, ()),
    # Proposals & Sync
    ("accept_proposal", "Accept proposal", "Proposals & Sync", _CL_AGENTS, ()),
    ("rebase", "Rebase CL", "Proposals & Sync", _CL_ONLY, ()),
    ("start_rewind", "Rewind CL", "Proposals & Sync", _CL_ONLY, ()),
    ("sync", "Sync repo", "Proposals & Sync", _ALL_TABS, ()),
    ("refresh", "Refresh tab", "Proposals & Sync", _ALL_TABS, ("reload",)),
    # Folding
    ("hooks_or_collapse", "Toggle hooks / collapse", "Folding", _ALL_TABS, ()),
    (
        "hooks_or_collapse_all",
        "Toggle hooks / collapse all",
        "Folding",
        _ALL_TABS,
        (),
    ),
    ("expand_or_layout", "Expand entry / change layout", "Folding", _ALL_TABS, ()),
    ("expand_all_folds", "Expand all folds", "Folding", _ALL_TABS, ()),
    ("toggle_layout", "Toggle layout", "Folding", _ALL_TABS, ()),
    # Marking
    ("toggle_mark", "Mark / unmark entry", "Marking", _CL_AGENTS, ()),
    ("clear_marks", "Clear all marks", "Marking", _CL_AGENTS, ("unmark",)),
    ("bulk_change_status", "Bulk change status", "Marking", _CL_ONLY, ()),
    ("mark_inactive_pinned", "Mark inactive pinned", "Marking", _AGENTS_ONLY, ()),
    # Agents / Axe actions
    ("kill_agent", "Kill / dismiss / start-stop axe", "Agents", _ALL_TABS, ()),
    (
        "open_agent_cleanup_panel",
        "Open agent cleanup panel / clear AXE output",
        "Agents",
        _AGENTS_AXE,
        ("cleanup", "dismiss all", "clear output"),
    ),
    ("stop_axe_and_quit", "Stop AXE and quit", "Axe", _ALL_TABS, ()),
    ("start_custom_agent", "Run custom agent", "Agents", _ALL_TABS, ("@",)),
    (
        "start_agent_from_changespec",
        "Run agent from CL",
        "Agents",
        _CL_AGENTS,
        (),
    ),
    (
        "jump_to_agent_changespec",
        "Jump to agent's CL",
        "Agents",
        _AGENTS_ONLY,
        ("go to cl",),
    ),
    ("edit_panel", "Edit panel file", "Agents", _AGENTS_ONLY, ()),
    ("show_agent_run_log", "Show agent run log", "Agents", _AGENTS_ONLY, ("log",)),
    (
        "toggle_attempt_view",
        "Toggle attempt view",
        "Agents",
        _AGENTS_ONLY,
        ("retry", "history"),
    ),
    ("add_agent_tag", "Add / remove agent tag", "Agents", _AGENTS_ONLY, ()),
    (
        "focus_next_agent_panel",
        "Focus next agent panel",
        "Agents",
        _AGENTS_ONLY,
        (),
    ),
    (
        "focus_prev_agent_panel",
        "Focus previous agent panel",
        "Agents",
        _AGENTS_ONLY,
        (),
    ),
    # Grouping (agents tab)
    ("cycle_grouping_mode", "Cycle grouping mode", "Grouping", _AGENTS_ONLY, ()),
    (
        "cycle_grouping_mode_reverse",
        "Cycle grouping mode (reverse)",
        "Grouping",
        _AGENTS_ONLY,
        (),
    ),
    # Thinking panel
    ("toggle_thinking", "Toggle thinking panel", "Display", _AGENTS_ONLY, ()),
    (
        "toggle_thinking_reverse",
        "Toggle thinking panel (reverse)",
        "Display",
        _AGENTS_ONLY,
        (),
    ),
    # File trim
    ("reset_file_trim", "Reset file trim", "Display", _AGENTS_ONLY, ()),
    ("show_all_file_lines", "Show all file lines", "Display", _AGENTS_ONLY, ()),
    # Queries
    ("edit_query", "Edit query", "Queries", _ALL_TABS, ("/",)),
    ("prev_query", "Previous saved query", "Queries", _ALL_TABS, ()),
    ("next_query", "Next saved query", "Queries", _ALL_TABS, ()),
    # Display / misc
    ("toggle_hide_reverted", "Toggle hide reverted", "Display", _CL_ONLY, ()),
    ("toggle_hide_submitted", "Toggle hide submitted", "Display", _CL_ONLY, ()),
    ("show_notifications", "Show notifications", "Display", _ALL_TABS, ()),
    ("show_help", "Show help", "Display", _ALL_TABS, ("?",)),
    ("browse_xprompts", "Browse xprompts", "Display", _ALL_TABS, ("#",)),
    # Workspace prefixes
    ("checkout", "Checkout workspace (primary)", "Workspace", _ALL_TABS, ()),
    ("start_checkout_mode", "Checkout workspace mode", "Modes", _ALL_TABS, ()),
    ("open_tmux", "Open tmux (primary)", "Workspace", _ALL_TABS, ()),
    ("start_tmux_mode", "Open tmux mode", "Modes", _ALL_TABS, ()),
    # Tree navigation prefixes
    (
        "start_ancestor_mode",
        "Ancestor navigation",
        "Tree Navigation",
        _CL_ONLY,
        (),
    ),
    ("start_child_mode", "Child navigation", "Tree Navigation", _CL_ONLY, ()),
    ("start_sibling_mode", "Sibling navigation", "Tree Navigation", _CL_ONLY, ()),
    # Mode activation prefixes
    ("start_fold_mode", "Enter fold mode", "Modes", _ALL_TABS, ()),
    ("start_leader_mode", "Enter leader mode", "Modes", _ALL_TABS, ()),
    ("start_bang_mode", "Enter bang mode", "Modes", _ALL_TABS, ()),
    ("copy_tab_content", "Enter copy mode", "Modes", _ALL_TABS, ()),
    # Palette itself
    (
        "open_command_palette",
        "Open command palette",
        "Misc",
        _ALL_TABS,
        ("commands", ":"),
    ),
)


def _ensure_metadata_covers_app_keymaps() -> None:
    """Fail loudly if metadata drifts from :class:`AppKeymaps`."""
    meta_actions = {row[0] for row in _APP_COMMAND_META}
    field_names = {f.name for f in fields(AppKeymaps)}
    missing = field_names - meta_actions
    extra = meta_actions - field_names
    if missing or extra:
        parts: list[str] = []
        if missing:
            parts.append(f"AppKeymaps fields missing metadata: {sorted(missing)}")
        if extra:
            parts.append(f"metadata for nonexistent fields: {sorted(extra)}")
        raise RuntimeError(
            "_APP_COMMAND_META / AppKeymaps mismatch — " + "; ".join(parts)
        )


_ensure_metadata_covers_app_keymaps()


# ---------------------------------------------------------------------------
# Built-in mode metadata
# ---------------------------------------------------------------------------
#
# label per command_id within each built-in mode. Tabs default to all
# three; copy_mode subkeys are scoped per-tab by their nesting and have
# their tabs derived in ``iter_mode_commands``.

_FOLD_LABELS: dict[str, str] = {
    "cycle_commits": "Cycle commits fold",
    "cycle_hooks": "Cycle hooks fold",
    "cycle_mentors": "Cycle mentors fold",
    "cycle_timestamps": "Cycle timestamps fold",
    "cycle_deltas": "Cycle deltas fold",
    "toggle_commits": "Toggle commits fold",
    "toggle_hooks": "Toggle hooks fold",
    "toggle_mentors": "Toggle mentors fold",
    "toggle_timestamps": "Toggle timestamps fold",
    "toggle_deltas": "Toggle deltas fold",
    "cycle_all": "Cycle all folds",
    "toggle_all": "Toggle all folds",
}

_COPY_LABELS: dict[str, dict[str, str]] = {
    "changespecs": {
        "raw": "Copy raw line",
        "with_snapshot": "Copy line + snapshot",
        "bug": "Copy bug id",
        "cl_number": "Copy CL number",
        "name": "Copy CL name",
        "spec": "Copy spec text",
        "snapshot": "Copy snapshot",
    },
    "agents": {
        "chat": "Copy chat path",
        "file_path": "Copy file path",
        "name": "Copy agent name",
        "prompt": "Copy prompt",
        "snapshot": "Copy snapshot",
    },
    "axe": {
        "visible": "Copy visible output",
        "full": "Copy full output",
        "snapshot": "Copy snapshot",
    },
}

_LEADER_LABELS: dict[str, str] = {
    "run_cmd": "Run background command",
    "runners": "Show runners",
    "kill_mentors": "Kill mentor workflows",
    "review_mentors": "Review mentor results",
    "agent_home": "Agent (home mode)",
    "agent_from_cl": "Agent from CL (quick)",
    "kill_and_edit": "Kill agent and edit",
    "mark_inactive": "Mark inactive agents",
    "retry_edit": "Retry agent (edit)",
    "activity_info": "Activity dashboard",
    "clear_comments": "Clear CL comments",
    "task_queue": "Task queue",
    "prompt_history": "Prompt history",
    "prompt_history_cancelled": "Prompt history (cancelled)",
    "jump_to_notification": "Jump to notification",
    "temporary_llm_override": "Temporary model override",
}

_BANG_LABELS: dict[str, str] = {
    "run_cmd": "Run command (bang)",
    "toggle_axe": "Toggle AXE (bang)",
}

# Per-mode fallback tab scoping (refined per-command for copy_mode).
_LEADER_TABS: dict[str, tuple[CommandTab, ...]] = {
    "run_cmd": _CL_ONLY,
    "kill_mentors": _CL_ONLY,
    "review_mentors": _CL_ONLY,
    "kill_and_edit": _AGENTS_ONLY,
    "retry_edit": _AGENTS_ONLY,
    "clear_comments": _CL_ONLY,
    "jump_to_notification": _AGENTS_ONLY,
    "agent_from_cl": _CL_AGENTS,
}


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _format_key_sequence(keys: tuple[str, ...]) -> str:
    """Format a Textual key sequence for palette display.

    Single keys go through ``key_display_name`` directly. Multi-key
    sequences (mode prefix + subkey) are concatenated without a
    separator when both are single chars (``%n``, ``,t``, ``zc``) and
    space-joined otherwise to preserve readability (``Ctrl+D x``).
    """
    if not keys:
        return ""
    parts = [key_display_name(k) for k in keys]
    if all(len(p) == 1 for p in parts):
        return "".join(parts)
    return " ".join(parts)


def iter_app_commands(registry: KeymapRegistry) -> Iterator[CommandSpec]:
    """Yield one :class:`CommandSpec` per :class:`AppKeymaps` field."""
    for action, label, category, tabs, aliases in _APP_COMMAND_META:
        key = getattr(registry.app, action)
        yield CommandSpec(
            id=f"app.{action}",
            label=label,
            key_sequence=(key,),
            key_display=_format_key_sequence((key,)),
            category=category,
            tabs=tabs,
            executor=CommandExecutor(kind="app_action", action=action),
            aliases=(action, *aliases),
        )


def iter_digit_commands() -> Iterator[CommandSpec]:
    """Yield the 10 saved-query digit commands."""
    for d in (1, 2, 3, 4, 5, 6, 7, 8, 9, 0):
        key = str(d)
        yield CommandSpec(
            id=f"saved_query.{d}",
            label=f"Load saved query {d}",
            key_sequence=(key,),
            key_display=key,
            category="Saved Queries",
            tabs=_ALL_TABS,
            executor=CommandExecutor(kind="saved_query", digit=d),
            aliases=(f"q{d}", f"query {d}"),
        )


def _iter_fold_commands(registry: KeymapRegistry) -> Iterator[CommandSpec]:
    fold = registry.fold_mode
    prefix = fold.prefix
    for command_id, subkey in fold.keys.items():
        if not isinstance(subkey, str):
            continue  # nested dicts not allowed in fold mode
        label = _FOLD_LABELS.get(command_id, command_id.replace("_", " ").title())
        seq = (prefix, subkey)
        yield CommandSpec(
            id=f"fold.{command_id}",
            label=label,
            key_sequence=seq,
            key_display=_format_key_sequence(seq),
            category="Fold",
            tabs=_ALL_TABS,
            executor=CommandExecutor(kind="fold_mode_key", subkey=subkey),
            aliases=("fold", command_id),
        )


def _iter_copy_commands(registry: KeymapRegistry) -> Iterator[CommandSpec]:
    copy = registry.copy_mode
    prefix = copy.prefix
    tab_to_command_tab: dict[str, CommandTab] = {
        "changespecs": "changespecs",
        "agents": "agents",
        "axe": "axe",
    }
    for tab_name, sub in copy.keys.items():
        if not isinstance(sub, dict):
            continue
        ctab = tab_to_command_tab.get(tab_name)
        if ctab is None:
            continue
        labels = _COPY_LABELS.get(tab_name, {})
        for command_id, subkey in sub.items():
            if not isinstance(subkey, str):
                continue
            label = labels.get(command_id, command_id.replace("_", " ").title())
            seq = (prefix, subkey)
            yield CommandSpec(
                id=f"copy.{tab_name}.{command_id}",
                label=label,
                key_sequence=seq,
                key_display=_format_key_sequence(seq),
                category="Copy",
                tabs=(ctab,),
                executor=CommandExecutor(
                    kind="copy_mode_key", subkey=subkey, copy_tab=ctab
                ),
                aliases=("copy", command_id),
            )


def _iter_leader_commands(registry: KeymapRegistry) -> Iterator[CommandSpec]:
    leader = registry.leader_mode
    prefix = leader.prefix
    for command_id, subkey in leader.keys.items():
        if not isinstance(subkey, str):
            continue
        label = _LEADER_LABELS.get(command_id, command_id.replace("_", " ").title())
        tabs = _LEADER_TABS.get(command_id, _ALL_TABS)
        seq = (prefix, subkey)
        yield CommandSpec(
            id=f"leader.{command_id}",
            label=label,
            key_sequence=seq,
            key_display=_format_key_sequence(seq),
            category="Leader",
            tabs=tabs,
            executor=CommandExecutor(kind="leader_mode_key", subkey=subkey),
            aliases=("leader", command_id),
        )


def _iter_bang_commands(registry: KeymapRegistry) -> Iterator[CommandSpec]:
    bang = registry.bang_mode
    prefix = bang.prefix
    for command_id, subkey in bang.keys.items():
        if not isinstance(subkey, str):
            continue
        label = _BANG_LABELS.get(command_id, command_id.replace("_", " ").title())
        seq = (prefix, subkey)
        yield CommandSpec(
            id=f"bang.{command_id}",
            label=label,
            key_sequence=seq,
            key_display=_format_key_sequence(seq),
            category="Bang",
            tabs=_ALL_TABS,
            executor=CommandExecutor(kind="bang_mode_key", subkey=subkey),
            aliases=("bang", command_id),
        )


def _iter_custom_mode_commands(
    registry: KeymapRegistry,
) -> Iterator[CommandSpec]:
    for mode_name, mode in registry.modes.items():
        if mode_name in BUILTIN_MODE_NAMES:
            continue
        if not mode.prefix:
            continue
        for command_id, payload in mode.keys.items():
            if not isinstance(payload, dict):
                continue
            subkey = payload.get("key")
            if not subkey:
                continue
            label = payload.get("description", command_id.replace("_", " ").title())
            seq = (mode.prefix, subkey)
            yield CommandSpec(
                id=f"custom.{mode_name}.{command_id}",
                label=label,
                key_sequence=seq,
                key_display=_format_key_sequence(seq),
                category="Custom",
                tabs=_ALL_TABS,
                executor=CommandExecutor(
                    kind="custom_mode_key",
                    mode_name=mode_name,
                    command_id=command_id,
                    subkey=subkey,
                ),
                aliases=("custom", mode_name, command_id),
            )


def iter_mode_commands(registry: KeymapRegistry) -> Iterator[CommandSpec]:
    """Yield one CommandSpec for every mode subkey (built-in + custom)."""
    yield from _iter_fold_commands(registry)
    yield from _iter_copy_commands(registry)
    yield from _iter_leader_commands(registry)
    yield from _iter_bang_commands(registry)
    yield from _iter_custom_mode_commands(registry)


def build_command_catalog(registry: KeymapRegistry) -> list[CommandSpec]:
    """Construct the full catalog from a :class:`KeymapRegistry`.

    Order is deterministic: app commands (in ``_APP_COMMAND_META``
    order), then digit bindings, then mode commands (fold, copy,
    leader, bang, custom — each in registry insertion order).
    """
    catalog: list[CommandSpec] = []
    catalog.extend(iter_app_commands(registry))
    catalog.extend(iter_digit_commands())
    catalog.extend(iter_mode_commands(registry))
    return catalog


def sort_specs_by_category(specs: list[CommandSpec]) -> list[CommandSpec]:
    """Return *specs* reordered to mirror the help modal sections.

    Uses :data:`CATEGORY_ORDER` as the primary key and the original
    list position as a stable tie-breaker so commands in the same
    category keep their catalog order. Categories not listed in
    :data:`CATEGORY_ORDER` sort to the end in their existing order.
    """
    order = {cat: i for i, cat in enumerate(CATEGORY_ORDER)}
    fallback = len(order)
    indexed = list(enumerate(specs))
    indexed.sort(key=lambda t: (order.get(t[1].category, fallback), t[0]))
    return [s for _, s in indexed]


def get_command_by_id(
    catalog: list[CommandSpec], command_id: str
) -> CommandSpec | None:
    """Return the :class:`CommandSpec` with the given id or ``None``.

    Lookup helper used by footer/help to source labels and key
    displays from the same catalog the palette renders, keeping the
    three surfaces in sync without each one re-deriving keys from the
    raw registry.
    """
    for spec in catalog:
        if spec.id == command_id:
            return spec
    return None
