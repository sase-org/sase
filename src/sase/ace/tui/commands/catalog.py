"""Command catalog construction for the ace TUI palette.

Builds a single source-of-truth list of :class:`CommandSpec` entries
from a :class:`KeymapRegistry`. Coverage:

- Every field in :class:`AppKeymaps` (one ``app.<field>`` command).
- The 10 saved-query picker sequences (configured prefix + ``0``..``9``).
- Every key in each built-in mode (fold / copy nested per-tab /
  leader / bang).
- Every valid user-defined custom mode command.

The catalog is the input the palette filters and the applicability
module scopes; it must stay in sync with :class:`AppKeymaps`. A guard
raises :class:`RuntimeError` if an ``AppKeymaps`` field is missing
app-command metadata so this can never silently drift.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from sase.ace.tui.artifact_tabs import ARTIFACTS_SUBTAB_ORDER
from sase.ace.tui.commands._app_metadata import (
    APP_COMMAND_META as _APP_COMMAND_META,
    ensure_metadata_covers_app_keymaps,
)
from sase.ace.tui.commands._formatting import (
    format_key_sequence as _format_key_sequence,
)
from sase.ace.tui.commands._mode_commands import iter_mode_commands
from sase.ace.tui.commands._tabs import ALL_TABS
from sase.ace.tui.commands._tabs import CL_ONLY
from sase.ace.tui.commands.types import (
    CATEGORY_ORDER,
    CommandExecutor,
    CommandSpec,
)

if TYPE_CHECKING:
    from sase.ace.tui.keymaps import KeymapRegistry


def _ensure_metadata_covers_app_keymaps() -> None:
    """Fail loudly if metadata drifts from :class:`AppKeymaps`.

    Kept in this module for compatibility with tests and downstream
    guard callers that patch ``catalog._APP_COMMAND_META`` directly.
    """
    ensure_metadata_covers_app_keymaps(_APP_COMMAND_META)


_ensure_metadata_covers_app_keymaps()


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


def iter_saved_query_commands(registry: KeymapRegistry) -> Iterator[CommandSpec]:
    """Yield the 10 saved-query commands behind the configured picker key."""
    prefix = registry.app.open_saved_query_picker
    for d in (1, 2, 3, 4, 5, 6, 7, 8, 9, 0):
        key = str(d)
        sequence = (prefix, key)
        yield CommandSpec(
            id=f"saved_query.{d}",
            label=f"Load saved query {d}",
            key_sequence=sequence,
            key_display=_format_key_sequence(sequence),
            category="Saved Queries",
            tabs=CL_ONLY,
            executor=CommandExecutor(kind="saved_query", digit=d),
            aliases=(f"q{d}", f"query {d}"),
        )


def iter_digit_commands(
    registry: KeymapRegistry | None = None,
) -> Iterator[CommandSpec]:
    """Compatibility alias for saved-query command catalog callers."""
    if registry is None:
        from sase.ace.tui.keymaps import load_keymap_registry

        registry = load_keymap_registry({})
    yield from iter_saved_query_commands(registry)


def _iter_projects_command() -> Iterator[CommandSpec]:
    """Yield the keyless Projects-tab command.

    The standalone ``,p`` project-management panel was retired and re-homed
    as the Admin Center's Projects tab. This command preserves a fast,
    searchable path to that panel — it has no key binding (the ``,p`` leader
    key is gone) and opens the Admin Center pre-focused on Projects via the
    ``open_projects_panel`` app action.
    """
    yield CommandSpec(
        id="projects",
        label="Open project management panel",
        key_sequence=(),
        key_display="",
        category="Display",
        tabs=ALL_TABS,
        executor=CommandExecutor(kind="app_action", action="open_projects_panel"),
        aliases=("projects", "project management", "admin center"),
    )


def _iter_artifacts_subtab_commands() -> Iterator[CommandSpec]:
    """Yield numbered direct jumps for every Artifacts sub-tab."""
    for index, subtab in enumerate(ARTIFACTS_SUBTAB_ORDER, start=1):
        label = "PRs" if subtab == "prs" else subtab.title()
        key = str(index)
        yield CommandSpec(
            id=f"artifacts.{subtab}",
            label=f"Show Artifacts: {label}",
            key_sequence=(key,),
            key_display=key,
            category="Tabs",
            tabs=CL_ONLY,
            executor=CommandExecutor(
                kind="app_action",
                action=f"show_artifacts_{subtab}",
            ),
            aliases=("artifacts", subtab, f"artifact {subtab}"),
        )


def _iter_logs_command() -> Iterator[CommandSpec]:
    """Yield the keyless Logs-tab command.

    The standalone ``,L`` log panel was retired and re-homed as the Admin
    Center's Logs tab. This command preserves a fast, searchable path to that
    panel without keeping the old leader key alive.
    """
    yield CommandSpec(
        id="logs",
        label="Open logs panel",
        key_sequence=(),
        key_display="",
        category="Display",
        tabs=ALL_TABS,
        executor=CommandExecutor(kind="app_action", action="open_log_panel"),
        aliases=(
            "logs",
            "log panel",
            "launch failures",
            "diagnostics",
            "admin center",
        ),
    )


def _iter_tasks_command() -> Iterator[CommandSpec]:
    """Yield the keyless Tasks-tab command.

    The standalone ``,t`` task-queue modal was retired and re-homed as the
    Admin Center's Tasks tab. This command preserves a fast, searchable path
    to that live task monitor without keeping the old leader key alive.
    """
    yield CommandSpec(
        id="tasks",
        label="Open tasks panel",
        key_sequence=(),
        key_display="",
        category="Display",
        tabs=ALL_TABS,
        executor=CommandExecutor(kind="app_action", action="open_tasks_panel"),
        aliases=("tasks", "task queue", "background tasks", "jobs", "queue"),
    )


def _iter_statistics_command() -> Iterator[CommandSpec]:
    """Yield the keyless Admin Center Statistics-tab command."""

    yield CommandSpec(
        id="statistics",
        label="Open statistics",
        key_sequence=(),
        key_display="",
        category="Display",
        tabs=ALL_TABS,
        executor=CommandExecutor(kind="app_action", action="open_statistics_panel"),
        aliases=(
            "statistics",
            "stats",
            "metrics",
            "telemetry",
            "admin center",
        ),
    )


def build_command_catalog(registry: KeymapRegistry) -> list[CommandSpec]:
    """Construct the full catalog from a :class:`KeymapRegistry`.

    Order is deterministic: app commands (in ``_APP_COMMAND_META``
    order), then saved-query sequences, numbered Artifacts jumps, the keyless
    Tasks, Statistics, Logs, and Projects commands, then
    mode commands (fold, copy, leader, bang, custom; each in registry
    insertion order).
    """
    catalog: list[CommandSpec] = []
    catalog.extend(iter_app_commands(registry))
    catalog.extend(iter_saved_query_commands(registry))
    catalog.extend(_iter_artifacts_subtab_commands())
    catalog.extend(_iter_tasks_command())
    catalog.extend(_iter_statistics_command())
    catalog.extend(_iter_logs_command())
    catalog.extend(_iter_projects_command())
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
