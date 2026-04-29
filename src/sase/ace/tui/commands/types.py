"""Type definitions for the ace TUI command catalog and palette.

Defines the small data classes that the rest of the command subsystem
revolves around:

- ``CommandTab`` / ``CommandCategory`` — display + scoping enums.
- ``CommandExecutor`` — frozen descriptor that says *how* to run a
  command (by app action name, by saved-query digit, by mode handler
  + subkey, or by custom mode command id). The executor is interpreted
  by Phase 3's ``execute`` module; the catalog only constructs them.
- ``CommandSpec`` — one command in the catalog. Stable id, label, key
  sequence (Textual + display), category, applicable tabs, executor,
  and search aliases.
- ``CommandContext`` — the small bag of state extracted from
  ``AceApp`` that availability predicates read. Defaults are conservative
  so unit tests can construct contexts piecemeal.
- ``CommandAvailability`` — the predicate signature.
- ``CommandPaletteResult`` — what the modal returns when the user
  picks a row (or cancels).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sase.ace.changespec import ChangeSpec
    from sase.ace.tui.models import Agent
    from sase.ace.tui.widgets.bgcmd_list import AxeItem


CommandTab = Literal["changespecs", "agents", "axe"]
"""The three top-level tabs that scope command applicability."""


CommandCategory = Literal[
    "Navigation",
    "Tabs",
    "CL Actions",
    "ChangeSpec Edits",
    "Proposals & Sync",
    "Folding",
    "Marking",
    "Agents",
    "Axe",
    "Grouping",
    "Display",
    "Queries",
    "Workspace",
    "Tree Navigation",
    "Modes",
    "Copy",
    "Leader",
    "Bang",
    "Fold",
    "Saved Queries",
    "Custom",
    "Misc",
]
"""Stable category labels grouped by the help modal's existing structure."""


CATEGORY_ORDER: tuple[CommandCategory, ...] = (
    "Navigation",
    "Tabs",
    "CL Actions",
    "ChangeSpec Edits",
    "Proposals & Sync",
    "Folding",
    "Marking",
    "Agents",
    "Axe",
    "Grouping",
    "Display",
    "Tree Navigation",
    "Workspace",
    "Modes",
    "Queries",
    "Saved Queries",
    "Fold",
    "Copy",
    "Leader",
    "Bang",
    "Custom",
    "Misc",
)
"""Display order that mirrors the help modal sections.

Used by the palette modal to group rows by category in a stable,
help-aligned order rather than alphabetic. Categories not listed here
sort to the end in their existing order (Python stable sort).
"""


# ---------------------------------------------------------------------------
# Executor descriptor
# ---------------------------------------------------------------------------


ExecutorKind = Literal[
    "app_action",
    "saved_query",
    "fold_mode_key",
    "copy_mode_key",
    "leader_mode_key",
    "bang_mode_key",
    "custom_mode_key",
]


@dataclass(frozen=True)
class CommandExecutor:
    """Frozen descriptor that says how to run a command.

    The catalog constructs these; Phase 3's ``execute`` module
    interprets them. Keeping this as data (not a callable) keeps the
    catalog importable from tests without dragging in ``AceApp``.

    Attributes:
        kind: Which dispatch path to use.
        action: For ``app_action`` — the action method name without the
            ``action_`` prefix (e.g. ``"refresh"``).
        digit: For ``saved_query`` — the digit 0..9.
        subkey: For mode-key kinds — the Textual subkey (e.g. ``"c"`` for
            ``z c`` cycle commits).
        mode_name: For ``custom_mode_key`` — the user-defined mode name.
        command_id: For ``custom_mode_key`` — the named entry inside that
            mode's keys dict.
        copy_tab: For ``copy_mode_key`` — which per-tab subdict the
            subkey lives under (``"changespecs"``, ``"agents"``, or
            ``"axe"``).
    """

    kind: ExecutorKind
    action: str | None = None
    digit: int | None = None
    subkey: str | None = None
    mode_name: str | None = None
    command_id: str | None = None
    copy_tab: CommandTab | None = None


# ---------------------------------------------------------------------------
# Command spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandSpec:
    """One command in the catalog.

    Attributes:
        id: Stable identifier such as ``app.refresh``,
            ``copy.agents.name``, ``leader.task_queue``,
            ``saved_query.3``, or ``custom.<mode>.<command_id>``.
        label: Short human-readable label suitable for the palette row.
        key_sequence: Tuple of one or more Textual key names. Single-key
            bindings are length-1; mode subcommands are length-2 (prefix +
            subkey).
        key_display: Pre-formatted display string (e.g. ``"%n"``,
            ``"Ctrl+D"``, ``",t"``, ``":"``).
        category: One of ``CommandCategory``.
        tabs: Which tabs this command can ever appear under. Tab-agnostic
            commands list all three.
        executor: Frozen ``CommandExecutor`` describing dispatch.
        aliases: Optional extra search tokens (action name, alt phrasings,
            mode prefix).
    """

    id: str
    label: str
    key_sequence: tuple[str, ...]
    key_display: str
    category: CommandCategory
    tabs: tuple[CommandTab, ...]
    executor: CommandExecutor
    aliases: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Context + availability
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandContext:
    """Snapshot of app state used by applicability predicates.

    Defaults are conservative so unit tests can construct contexts
    piecemeal (e.g. ``CommandContext(tab="agents")``).
    """

    tab: CommandTab = "changespecs"
    changespec: ChangeSpec | None = None
    agent: Agent | None = None
    axe_item: AxeItem | None = None
    # CLs tab state
    mark_count: int = 0
    # Agents tab state
    completed_agent_count: int = 0
    runner_count: int = 0
    can_jump_to_changespec: bool = False
    attempt_pinned: bool = False
    group_focused: bool = False
    file_panel_visible: bool = False
    # Axe tab state
    axe_running: bool = False
    selected_axe_slot_done: bool = False
    selected_axe_slot_running: bool = False


CommandAvailability = Callable[["CommandSpec", CommandContext], bool]
"""Pure predicate signature over a spec + the current context."""


# ---------------------------------------------------------------------------
# Palette result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandPaletteResult:
    """What the palette modal returns when dismissed.

    ``selected_id`` is ``None`` when the user cancels with Esc.
    """

    selected_id: str | None
