"""Pure save-location choice builders for the location-first picker.

This module is presentation-only data: no Textual widgets, no app state, no
event-loop interaction. The orchestrators (later phases) call these builders
off the Textual event loop and hand the result to
:cls:`SaveLocationPickerModal` via ``set_choices``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from sase.ace.tui.modals.mini_xprompt_target_catalog import (
    destination_defines_name,
    destination_target_for_name,
)
from sase.ace.tui.modals.unified_xprompt_save_support import UnifiedSaveLocation
from sase.ace.tui.modals.xprompt_location_modal import (
    XPROMPT_HOME_DIR_LABEL,
    XPROMPT_PROJECT_CONFIG_LABEL,
    XPROMPT_PROJECT_DIR_LABEL,
    XPROMPT_PROJECT_HOME_LABEL_PREFIX,
    XPROMPT_USER_CONFIG_LABEL,
    XPROMPT_USER_OVERLAY_LABEL_PREFIX,
    shorten_xprompt_location_path,
)
from sase.xprompt.snippet_targets import (
    SNIPPET_PROJECT_CONFIG_LABEL,
    SNIPPET_USER_CONFIG_LABEL,
    SNIPPET_USER_OVERLAY_LABEL_PREFIX,
    SnippetConfigLocation,
    SnippetSaveTarget,
)
from sase.xprompt.write_targets import resolve_xprompt_write_target

SaveLocationKind = Literal["directory", "config"]

#: Synthetic section for a configured snippet file outside discovery.
SNIPPET_CONFIGURED_SECTION = "Configured"

#: Synthetic label for a configured snippet file outside discovery.
SNIPPET_CONFIGURED_LABEL = "Configured snippet config"


@dataclass(frozen=True, slots=True)
class SaveLocationChoice:
    """One selectable (or shown-disabled) destination row."""

    choice_id: str
    """The location path. The orchestrator maps it back to the source row."""

    hotkey: str | None
    """Single-character pick key, or None when the row has no active key.

    Canonical rows that are not writable keep their canonical letter here so
    the modal can report *why* the usual key is unavailable. The modal renders
    those rows with ``·`` in the key column and excludes them from the hints
    line, so they have no *active* hotkey.
    """

    section: str
    kind: SaveLocationKind
    label: str
    display_path: str
    badges: tuple[str, ...] = field(default_factory=tuple)
    disabled_reason: str | None = None
    preview: str = ""
    is_default: bool = False
    collapsed_group: bool = False

    @property
    def is_selectable(self) -> bool:
        return self.disabled_reason is None


@dataclass(frozen=True, slots=True)
class SaveLocationPick:
    """A resolved picker choice plus keystrokes buffered while loading."""

    choice_id: str
    typeahead: str = ""


@dataclass(frozen=True, slots=True)
class ChangeSaveLocationRequest:
    """The name step asks the orchestrator to reopen the picker."""

    text: str


def _short_label(discovery_label: str) -> str:
    """Return the compact picker label for a discovery label."""
    if discovery_label == XPROMPT_PROJECT_DIR_LABEL:
        return "Project xprompts"
    if discovery_label in (
        XPROMPT_PROJECT_CONFIG_LABEL,
        SNIPPET_PROJECT_CONFIG_LABEL,
    ):
        return "Project config"
    if discovery_label.startswith(XPROMPT_PROJECT_HOME_LABEL_PREFIX):
        return "Project, personal"
    if discovery_label == XPROMPT_HOME_DIR_LABEL:
        return "Home xprompts"
    if discovery_label in (XPROMPT_USER_CONFIG_LABEL, SNIPPET_USER_CONFIG_LABEL):
        return "User config"
    if discovery_label.startswith(
        XPROMPT_USER_OVERLAY_LABEL_PREFIX
    ) or discovery_label.startswith(SNIPPET_USER_OVERLAY_LABEL_PREFIX):
        return discovery_label.removeprefix("User ")
    return discovery_label


def _write_path_for(path: str) -> str:
    """Return the resolved write path for *path*, falling back to *path*."""
    try:
        return str(resolve_xprompt_write_target(path).write_path)
    except Exception:
        return path


def _via_chezmoi(path: str) -> bool:
    """Return whether edits to *path* redirect through a chezmoi source."""
    try:
        return resolve_xprompt_write_target(path).via_chezmoi
    except Exception:
        return False


def _matches_path(row_path: str, wanted: str | None) -> bool:
    """Return whether *wanted* names *row_path* or its resolved write path."""
    if not wanted:
        return False
    return wanted == row_path or wanted == _write_path_for(row_path)


def _project_section(project: str | None) -> str:
    return f"Project · {project}" if project else "Project"


def _callable_reference(namespace: str | None, name: str) -> str:
    """Return the ``#`` reference previewed for *name* at a destination."""
    if not name:
        return f"#{namespace}/<name>" if namespace else "#<name>"
    if namespace and "/" not in name:
        return f"#{namespace}/{name}"
    return f"#{name}"


def _storage_name(namespace: str | None, name: str) -> str:
    """Return the physical entry name written for callable *name*."""
    if namespace:
        prefix = f"{namespace}/"
        if name.startswith(prefix):
            return name.removeprefix(prefix)
    return name


def _xprompt_preview(
    row: UnifiedSaveLocation,
    rows: Sequence[UnifiedSaveLocation],
    *,
    name: str,
) -> str:
    """Return the footer preview for one xprompt destination row."""
    count = len(row.names)
    if row.location.location_type == "directory":
        reference = _callable_reference(row.namespace, name)
        if name:
            try:
                target = destination_target_for_name(row, name, destinations=rows)
                concrete = shorten_xprompt_location_path(
                    target.path, str(Path.cwd()), str(Path.home())
                )
            except Exception:
                concrete = f"{row.display_path}/<name>.md"
            return f"→ {concrete} · called as {reference} · {count} xprompts here"
        return (
            f"→ {row.display_path}/<name>.md · called as {reference} "
            f"· {count} xprompts here"
        )
    entry = _storage_name(row.namespace, name) if name else "<name>"
    return f"→ {row.display_path} · xprompts.{entry}"


def _snippet_preview(display_path: str, *, trigger: str, count: int) -> str:
    """Return the footer preview for one snippet destination row."""
    return (
        f"→ {display_path} · ace.snippets.{trigger or '<trigger>'} "
        f"· {count} snippets here"
    )


def _badges(
    *,
    default_reason: str | None,
    is_current: bool,
    has_name: bool,
    has_label: str,
    is_new: bool,
    chezmoi: bool,
) -> tuple[str, ...]:
    """Assemble picker badges in display order."""
    badges: list[str] = []
    if default_reason is not None:
        badges.append(f"★ {default_reason}")
    elif is_current:
        badges.append("● current")
    if has_name:
        badges.append(has_label)
    if is_new:
        badges.append("new")
    if chezmoi:
        badges.append("chezmoi")
    return tuple(badges)


_XPROMPT_CANONICAL_HOTKEYS = {
    XPROMPT_PROJECT_DIR_LABEL: "p",
    XPROMPT_PROJECT_CONFIG_LABEL: "P",
    XPROMPT_HOME_DIR_LABEL: "h",
    XPROMPT_USER_CONFIG_LABEL: "H",
}


def _is_plugin_row(row: UnifiedSaveLocation) -> bool:
    return row.builtin or row.group in ("Plugin directories", "Built-in (dev)")


def xprompt_location_choices(
    rows: Sequence[UnifiedSaveLocation],
    *,
    last_used_path: str | None = None,
    current_path: str | None = None,
    home_mode: bool = False,
    project: str | None = None,
    name: str = "",
) -> tuple[tuple[SaveLocationChoice, ...], str | None]:
    """Build picker choices for mini-xprompt destinations.

    Returns the choices in display order plus the default choice id (``None``
    when nothing is selectable). Hotkeys are mnemonic and scope-first:
    ``p``/``P`` for the project rows, ``h``/``H`` for the home rows, digits
    for the remaining Project/Home rows in display order.
    """
    rows = tuple(rows)
    project_section = _project_section(project)

    visible: list[tuple[UnifiedSaveLocation, str]] = []
    for row in rows:
        label = row.location.label
        if _is_plugin_row(row):
            if not row.is_selectable:
                continue
            visible.append((row, "Plugins & built-in"))
        elif label in _XPROMPT_CANONICAL_HOTKEYS:
            section = (
                project_section
                if label in (XPROMPT_PROJECT_DIR_LABEL, XPROMPT_PROJECT_CONFIG_LABEL)
                else "Home"
            )
            visible.append((row, section))
        elif label.startswith("Project") or label.startswith(
            XPROMPT_PROJECT_HOME_LABEL_PREFIX
        ):
            if not row.is_selectable:
                continue
            visible.append((row, project_section))
        elif label.startswith("Home") or label.startswith("User "):
            if not row.is_selectable:
                continue
            visible.append((row, "Home"))
        else:
            if not row.is_selectable:
                continue
            visible.append((row, "Home"))

    ordered = _order_xprompt_sections(visible)

    digit = 1
    hotkeys: dict[int, str | None] = {}
    for index, (row, _section) in enumerate(ordered):
        canonical = _XPROMPT_CANONICAL_HOTKEYS.get(row.location.label)
        if canonical is not None:
            hotkeys[index] = canonical
        elif _is_plugin_row(row):
            hotkeys[index] = None
        elif digit <= 9:
            hotkeys[index] = str(digit)
            digit += 1
        else:
            hotkeys[index] = None

    default_index = _xprompt_default_index(
        ordered,
        rows,
        last_used_path=last_used_path,
        current_path=current_path,
        home_mode=home_mode,
    )

    default_reason: str | None = None
    if default_index is not None:
        default_row = ordered[default_index][0]
        if _matches_path(default_row.location.path, current_path):
            default_reason = "current"
        elif _matches_path(default_row.location.path, last_used_path):
            default_reason = "last used"
        else:
            default_reason = "default"

    choices: list[SaveLocationChoice] = []
    for index, (row, section) in enumerate(ordered):
        is_default = index == default_index
        is_current = _matches_path(row.location.path, current_path)
        has_name = bool(name) and destination_defines_name(row, name)
        choices.append(
            SaveLocationChoice(
                choice_id=row.location.path,
                hotkey=hotkeys[index],
                section=section,
                kind=row.location.location_type,  # type: ignore[arg-type]
                label=_short_label(row.location.label),
                display_path=row.display_path,
                badges=_badges(
                    default_reason=default_reason if is_default else None,
                    is_current=is_current,
                    has_name=has_name,
                    has_label=f"has #{name}" if has_name else "",
                    is_new=row.will_create,
                    chezmoi=_via_chezmoi(row.location.path),
                ),
                disabled_reason=row.disabled_reason,
                preview=_xprompt_preview(row, rows, name=name),
                is_default=is_default,
                collapsed_group=_is_plugin_row(row),
            )
        )
    default_id = choices[default_index].choice_id if default_index is not None else None
    return tuple(choices), default_id


def _order_xprompt_sections(
    visible: list[tuple[UnifiedSaveLocation, str]],
) -> list[tuple[UnifiedSaveLocation, str]]:
    """Order rows as displayed: Project, Home, then Plugins & built-in."""
    project = [
        item for item in visible if item[1] not in ("Home", "Plugins & built-in")
    ]
    home = [item for item in visible if item[1] == "Home"]
    plugins = [item for item in visible if item[1] == "Plugins & built-in"]

    def _section_key(item: tuple[UnifiedSaveLocation, str]) -> tuple[int, int]:
        row = item[0]
        label = row.location.label
        if label == XPROMPT_PROJECT_DIR_LABEL:
            return (0, 0)
        if label == XPROMPT_PROJECT_CONFIG_LABEL:
            return (0, 1)
        if label == XPROMPT_HOME_DIR_LABEL:
            return (0, 0)
        if label == XPROMPT_USER_CONFIG_LABEL:
            return (0, 1)
        return (1, 0)

    project = sorted(project, key=_section_key)
    home = sorted(home, key=_section_key)
    return [*project, *home, *plugins]


def _xprompt_default_index(
    ordered: list[tuple[UnifiedSaveLocation, str]],
    rows: Sequence[UnifiedSaveLocation],
    *,
    last_used_path: str | None,
    current_path: str | None,
    home_mode: bool,
) -> int | None:
    """Return the display-order index of the default xprompt row."""
    del rows
    selectable = [
        index for index, (row, _section) in enumerate(ordered) if row.is_selectable
    ]
    if not selectable:
        return None
    for index in selectable:
        if _matches_path(ordered[index][0].location.path, current_path):
            return index
    for index in selectable:
        if _matches_path(ordered[index][0].location.path, last_used_path):
            return index
    if not home_mode:
        for index in selectable:
            if ordered[index][0].location.label == XPROMPT_PROJECT_DIR_LABEL:
                return index
    for index in selectable:
        if ordered[index][0].location.label == XPROMPT_HOME_DIR_LABEL:
            return index
    return selectable[0]


def snippet_location_choices(
    locations: Sequence[SnippetConfigLocation],
    *,
    resolved_target: SnippetSaveTarget,
    names_by_path: Mapping[str, frozenset[str]],
    last_used_path: str | None = None,
    current_path: str | None = None,
    project: str | None = None,
    trigger: str = "",
) -> tuple[tuple[SaveLocationChoice, ...], str | None]:
    """Build picker choices for snippet config destinations.

    Returns the choices in display order plus the default choice id (``None``
    when nothing is selectable). The configured ``ace.snippet_config_path``
    gets its own top section with key ``c`` when it points outside the
    discovered files.
    """
    locations = tuple(locations)
    project_section = _project_section(project)
    known_paths = {location.path for location in locations}
    configured_path = str(resolved_target.write_path)
    configured_read = str(resolved_target.read_path)
    configured_outside = (
        resolved_target.source == "configured"
        and configured_path not in known_paths
        and configured_read not in known_paths
    )

    @dataclass(frozen=True, slots=True)
    class _Entry:
        path: str
        section: str
        label: str
        display_path: str
        disabled_reason: str | None
        names: frozenset[str]

    raw: list[_Entry] = []
    if configured_outside:
        raw.append(
            _Entry(
                path=configured_path,
                section=SNIPPET_CONFIGURED_SECTION,
                label=SNIPPET_CONFIGURED_LABEL,
                display_path=resolved_target.display_path,
                disabled_reason=None,
                names=names_by_path.get(configured_path, frozenset()),
            )
        )
    for location in locations:
        raw.append(
            _Entry(
                path=location.path,
                section="",
                label=location.label,
                display_path=location.display_path,
                disabled_reason=location.disabled_reason,
                names=names_by_path.get(location.path, frozenset()),
            )
        )

    entries: list[_Entry] = []
    for entry in raw:
        if entry.section == SNIPPET_CONFIGURED_SECTION:
            entries.append(entry)
            continue
        label = entry.label
        if label == SNIPPET_PROJECT_CONFIG_LABEL:
            entries.append(entry)
        elif label == SNIPPET_USER_CONFIG_LABEL:
            entries.append(entry)
        elif label.startswith(SNIPPET_USER_OVERLAY_LABEL_PREFIX):
            if entry.disabled_reason is not None:
                continue
            entries.append(entry)
        else:
            if entry.disabled_reason is not None:
                continue
            entries.append(entry)

    def _entry_section(entry: _Entry) -> str:
        if entry.section:
            return entry.section
        if entry.label == SNIPPET_PROJECT_CONFIG_LABEL:
            return project_section
        return "Home"

    ordered = sorted(
        entries,
        key=lambda entry: (
            0 if entry.section == SNIPPET_CONFIGURED_SECTION else 1,
            0 if _entry_section(entry) != "Home" else 1,
            0
            if entry.label in (SNIPPET_PROJECT_CONFIG_LABEL, SNIPPET_USER_CONFIG_LABEL)
            else 1,
        ),
    )

    digit = 1
    hotkeys: list[str | None] = []
    for entry in ordered:
        if entry.section == SNIPPET_CONFIGURED_SECTION:
            hotkeys.append("c")
        elif entry.label == SNIPPET_PROJECT_CONFIG_LABEL:
            hotkeys.append("p")
        elif entry.label == SNIPPET_USER_CONFIG_LABEL:
            hotkeys.append("h")
        elif entry.label.startswith(SNIPPET_USER_OVERLAY_LABEL_PREFIX) and digit <= 9:
            hotkeys.append(str(digit))
            digit += 1
        else:
            hotkeys.append(None)

    selectable = [
        index for index, entry in enumerate(ordered) if entry.disabled_reason is None
    ]
    default_index: int | None = None
    if selectable:
        for index in selectable:
            if _matches_path(ordered[index].path, current_path):
                default_index = index
                break
        if default_index is None and resolved_target.source == "configured":
            for index in selectable:
                if ordered[index].path in (configured_path, configured_read):
                    default_index = index
                    break
        if default_index is None:
            for index in selectable:
                if _matches_path(ordered[index].path, last_used_path):
                    default_index = index
                    break
        if default_index is None:
            for index in selectable:
                if ordered[index].path in (configured_path, configured_read):
                    default_index = index
                    break
            if default_index is None:
                for index in selectable:
                    if ordered[index].label == SNIPPET_USER_CONFIG_LABEL:
                        default_index = index
                        break
        if default_index is None:
            default_index = selectable[0]

    snippet_default_reason: str | None = None
    if default_index is not None:
        default_entry = ordered[default_index]
        if _matches_path(default_entry.path, current_path):
            snippet_default_reason = "current"
        elif (
            resolved_target.source == "configured"
            and default_entry.path == configured_path
        ):
            snippet_default_reason = "configured"
        elif _matches_path(default_entry.path, last_used_path):
            snippet_default_reason = "last used"
        else:
            snippet_default_reason = "default"

    choices: list[SaveLocationChoice] = []
    for index, entry in enumerate(ordered):
        is_default = index == default_index
        is_current = _matches_path(entry.path, current_path)
        has_trigger = bool(trigger) and trigger in entry.names
        try:
            is_new = not Path(entry.path).exists()
        except Exception:
            is_new = False
        choices.append(
            SaveLocationChoice(
                choice_id=entry.path,
                hotkey=hotkeys[index],
                section=_entry_section(entry),
                kind="config",
                label=_short_label(entry.label),
                display_path=entry.display_path,
                badges=_badges(
                    default_reason=snippet_default_reason if is_default else None,
                    is_current=is_current,
                    has_name=has_trigger,
                    has_label=f"has ⇥ {trigger}" if has_trigger else "",
                    is_new=is_new,
                    chezmoi=_via_chezmoi(entry.path),
                ),
                disabled_reason=entry.disabled_reason,
                preview=_snippet_preview(
                    entry.display_path,
                    trigger=trigger,
                    count=len(entry.names),
                ),
                is_default=is_default,
                collapsed_group=False,
            )
        )
    final_default = (
        choices[default_index].choice_id if default_index is not None else None
    )
    return tuple(choices), final_default


__all__ = [
    "ChangeSaveLocationRequest",
    "SNIPPET_CONFIGURED_LABEL",
    "SNIPPET_CONFIGURED_SECTION",
    "SaveLocationChoice",
    "SaveLocationKind",
    "SaveLocationPick",
    "snippet_location_choices",
    "xprompt_location_choices",
]
