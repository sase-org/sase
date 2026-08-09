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
from dataclasses import InitVar, dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sase.ace.patch import Patch
    from sase.ace.tui.models import Agent
    from sase.ace.tui.widgets.bgcmd_list import AxeItem


CommandTab = Literal["artifacts", "agents", "axe"]
"""The three top-level tabs that scope command applicability."""

LegacyCommandTab = Literal["changespecs", "patches"]


CommandCategory = Literal[
    "Navigation",
    "Tabs",
    "Bugs",
    "Patch Actions",
    "Patch Edits",
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
    "Bugs",
    "Patch Actions",
    "Patch Edits",
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
            subkey lives under (``"artifacts"``, ``"agents"``, or
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
            ``copy.agents.name``, ``leader.agent_run_log``,
            ``saved_query.3``, or ``custom.<mode>.<command_id>``.
        label: Short human-readable label suitable for the palette row.
        key_sequence: Tuple of one or more Textual key names. Single-key
            bindings are length-1; mode subcommands are length-2 (prefix +
            subkey).
        key_display: Pre-formatted display string (e.g. ``"%n"``,
            ``"Ctrl+D"``, ``",A"``, ``":"``).
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

    tab: CommandTab | LegacyCommandTab = "artifacts"
    artifacts_subtab: Literal[
        "prs", "commits", "bugs", "beads", "plans", "chats", "other"
    ] = "prs"
    patch: Patch | None = None
    changespec: InitVar[Patch | None] = None
    agent: Agent | None = None
    axe_item: AxeItem | None = None
    # Warm-only Artifacts copy-palette selection state. ``None`` means the
    # caller did not capture this specialized context and preserves the
    # command catalog's conservative legacy behavior.
    artifact_selection_present: bool | None = None
    artifact_available_targets: frozenset[str] | None = None
    # Patches tab state
    mark_count: int = 0
    # Agents tab state
    completed_agent_count: int = 0
    stopped_agent_count: int = 0
    unread_completed_agent_count: int = 0
    runner_count: int = 0
    can_jump_to_patch: bool = False
    can_jump_to_changespec: InitVar[bool | None] = None
    attempt_pinned: bool = False
    panel_focused: bool = False
    panel_collapsed: bool = False
    focused_panel_key: str | None = None
    # Compatibility for callers that still construct collapsed-only context.
    collapsed_panel_focused: bool = False
    group_focused: bool = False
    file_panel_visible: bool = False
    has_artifact_files: bool = False
    agents_metadata_search_active: bool = False
    # Axe tab state
    axe_running: bool = False
    selected_axe_slot_done: bool = False
    selected_axe_slot_running: bool = False
    selected_axe_chop_run_total: int = 0
    selected_axe_chop_enabled: bool = True
    selected_axe_chop_running: bool = False

    def __post_init__(
        self,
        changespec: Patch | None,
        can_jump_to_changespec: bool | None,
    ) -> None:
        if self.tab in {"changespecs", "patches"}:
            object.__setattr__(self, "tab", "artifacts")
        if self.patch is None and changespec is not None:
            object.__setattr__(self, "patch", changespec)
        if can_jump_to_changespec is not None and not self.can_jump_to_patch:
            object.__setattr__(
                self,
                "can_jump_to_patch",
                can_jump_to_changespec,
            )

    @property
    def selected_changespec(self) -> Patch | None:
        return self.patch


def _command_context_changespec(self: CommandContext) -> Patch | None:
    return self.patch


def _command_context_can_jump_to_changespec(self: CommandContext) -> bool:
    return self.can_jump_to_patch


CommandContext.changespec = property(_command_context_changespec)  # type: ignore[attr-defined]
CommandContext.can_jump_to_changespec = property(  # type: ignore[attr-defined]
    _command_context_can_jump_to_changespec
)


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
