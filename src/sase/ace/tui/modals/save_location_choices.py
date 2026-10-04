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

from sase.ace.tui.modals._save_location_choice_format import (
    badges,
    macro_preview,
    matches_path,
    project_section as project_section_label,
    short_label,
    snippet_preview,
    via_chezmoi,
)
from sase.ace.tui.modals.mini_macro_target_catalog import (
    destination_defines_name,
    rebase_name_for_destination,
)
from sase.ace.tui.modals.unified_macro_save_support import UnifiedSaveLocation
from sase.ace.tui.modals.macro_location_modal import (
    MACRO_HOME_DIR_LABEL,
    MACRO_PROJECT_CONFIG_LABEL,
    MACRO_PROJECT_DIR_LABEL,
    MACRO_PROJECT_HOME_LABEL_PREFIX,
    MACRO_USER_CONFIG_LABEL,
    MACRO_USER_OVERLAY_LABEL_PREFIX,
)
from sase.macro.snippet_targets import (
    SNIPPET_PROJECT_CONFIG_LABEL,
    SNIPPET_USER_CONFIG_LABEL,
    SNIPPET_USER_OVERLAY_LABEL_PREFIX,
    SnippetConfigLocation,
    SnippetSaveTarget,
)

SaveLocationKind = Literal["directory", "config", "existing"]

#: Synthetic id for the Existing action row. Never a destination path.
EXISTING_CHOICE_ID = "__existing__"

#: Synthetic section for a configured snippet file outside discovery.
SNIPPET_CONFIGURED_SECTION = "Configured"

#: Synthetic label for a configured snippet file outside discovery.
SNIPPET_CONFIGURED_LABEL = "Configured snippet config"


@dataclass(frozen=True, slots=True)
class ExistingRowSpec:
    """Optional Existing action row rendered at the top of the picker."""

    count: int
    switching: bool = False


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


def _namespace_override_reason(
    row: UnifiedSaveLocation, override_name: str
) -> str | None:
    """Return a disable reason when *row* would rebase *override_name*."""
    rebased = rebase_name_for_destination(override_name, row)
    if rebased != override_name:
        return f"saves as #{rebased} — can't override #{override_name}"
    return None


def _existing_choice(
    spec: ExistingRowSpec,
    *,
    kind: Literal["macro", "snippet"],
    file_count: int,
) -> SaveLocationChoice:
    """Build the Existing action row. Never the default."""
    noun = "macros" if kind == "macro" else "snippets"
    singular = "macro" if kind == "macro" else "snippet"
    label = (
        f"Switch to existing {singular}…"
        if spec.switching
        else f"Edit existing {singular}…"
    )
    return SaveLocationChoice(
        choice_id=EXISTING_CHOICE_ID,
        hotkey="e",
        section="Existing",
        kind="existing",
        label=label,
        display_path="",
        badges=(f"{spec.count} {noun}",),
        disabled_reason=None if spec.count else f"no {noun} yet",
        preview=(
            f"→ fuzzy-find {spec.count} {noun} across {file_count} files "
            "· edit in place or override read-only ones"
        ),
        is_default=False,
        collapsed_group=False,
    )


def _finish_choices(
    choices: list[SaveLocationChoice],
    default_id: str | None,
    *,
    existing: ExistingRowSpec | None,
    override_name: str | None,
    kind: Literal["macro", "snippet"],
) -> tuple[tuple[SaveLocationChoice, ...], str | None]:
    """Prepend the Existing row unless override mode is on."""
    if existing is not None and override_name is None:
        choices = [
            _existing_choice(existing, kind=kind, file_count=len(choices)),
            *choices,
        ]
    return tuple(choices), default_id


_MACRO_CANONICAL_HOTKEYS = {
    MACRO_PROJECT_DIR_LABEL: "p",
    MACRO_PROJECT_CONFIG_LABEL: "P",
    MACRO_HOME_DIR_LABEL: "h",
    MACRO_USER_CONFIG_LABEL: "H",
}


def _is_plugin_row(row: UnifiedSaveLocation) -> bool:
    return row.builtin or row.group in ("Plugin directories", "Built-in (dev)")


def macro_location_choices(
    rows: Sequence[UnifiedSaveLocation],
    *,
    last_used_path: str | None = None,
    current_path: str | None = None,
    home_mode: bool = False,
    project: str | None = None,
    name: str = "",
    existing: ExistingRowSpec | None = None,
    override_name: str | None = None,
    shadowed_by: Mapping[str, str] | None = None,
) -> tuple[tuple[SaveLocationChoice, ...], str | None]:
    """Build picker choices for mini-macro destinations.

    Returns the choices in display order plus the default choice id (``None``
    when nothing is selectable). Hotkeys are mnemonic and scope-first:
    ``p``/``P`` for the project rows, ``h``/``H`` for the home rows, digits
    for the remaining Project/Home rows in display order.
    """
    rows = tuple(rows)
    project_section = project_section_label(project)

    visible: list[tuple[UnifiedSaveLocation, str]] = []
    for row in rows:
        label = row.location.label
        if _is_plugin_row(row):
            if not row.is_selectable:
                continue
            visible.append((row, "Plugins & built-in"))
        elif label in _MACRO_CANONICAL_HOTKEYS:
            section = (
                project_section
                if label in (MACRO_PROJECT_DIR_LABEL, MACRO_PROJECT_CONFIG_LABEL)
                else "Home"
            )
            visible.append((row, section))
        elif label.startswith("Project") or label.startswith(
            MACRO_PROJECT_HOME_LABEL_PREFIX
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

    ordered = _order_macro_sections(visible)

    digit = 1
    hotkeys: dict[int, str | None] = {}
    for index, (row, _section) in enumerate(ordered):
        canonical = _MACRO_CANONICAL_HOTKEYS.get(row.location.label)
        if canonical is not None:
            hotkeys[index] = canonical
        elif _is_plugin_row(row):
            hotkeys[index] = None
        elif digit <= 9:
            hotkeys[index] = str(digit)
            digit += 1
        else:
            hotkeys[index] = None

    override_reasons: dict[str, str] = {}
    if override_name is not None:
        for row, _section in ordered:
            reason = _namespace_override_reason(row, override_name)
            if reason is not None:
                override_reasons[row.location.path] = reason

    selectable_indices = [
        index
        for index, (row, _section) in enumerate(ordered)
        if row.is_selectable and row.location.path not in override_reasons
    ]
    default_index = _macro_default_index(
        ordered,
        rows,
        last_used_path=last_used_path,
        current_path=current_path,
        home_mode=home_mode,
        selectable=selectable_indices,
        shadowed_ids=frozenset(shadowed_by or ())
        if override_name is not None
        else frozenset(),
        override=override_name is not None,
    )

    default_reason: str | None = None
    if default_index is not None:
        if override_name is not None:
            default_reason = "override"
        else:
            default_row = ordered[default_index][0]
            if matches_path(default_row.location.path, current_path):
                default_reason = "current"
            elif matches_path(default_row.location.path, last_used_path):
                default_reason = "last used"
            else:
                default_reason = "default"

    shadow_map = shadowed_by if override_name is not None else None
    choices: list[SaveLocationChoice] = []
    for index, (row, section) in enumerate(ordered):
        is_default = index == default_index
        is_current = matches_path(row.location.path, current_path)
        has_name = bool(name) and destination_defines_name(row, name)
        choices.append(
            SaveLocationChoice(
                choice_id=row.location.path,
                hotkey=hotkeys[index],
                section=section,
                kind=row.location.location_type,  # type: ignore[arg-type]
                label=short_label(row.location.label),
                display_path=row.display_path,
                badges=badges(
                    default_reason=default_reason if is_default else None,
                    is_current=is_current,
                    has_name=has_name,
                    has_label=f"has #{name}" if has_name else "",
                    is_new=row.will_create,
                    chezmoi=via_chezmoi(row.location.path),
                    shadowed_by=(shadow_map or {}).get(row.location.path),
                ),
                disabled_reason=row.disabled_reason
                or override_reasons.get(row.location.path),
                preview=macro_preview(row, rows, name=name),
                is_default=is_default,
                collapsed_group=_is_plugin_row(row),
            )
        )
    default_id = choices[default_index].choice_id if default_index is not None else None
    return _finish_choices(
        choices,
        default_id,
        existing=existing,
        override_name=override_name,
        kind="macro",
    )


def _order_macro_sections(
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
        if label == MACRO_PROJECT_DIR_LABEL:
            return (0, 0)
        if label == MACRO_PROJECT_CONFIG_LABEL:
            return (0, 1)
        if label == MACRO_HOME_DIR_LABEL:
            return (0, 0)
        if label == MACRO_USER_CONFIG_LABEL:
            return (0, 1)
        return (1, 0)

    project = sorted(project, key=_section_key)
    home = sorted(home, key=_section_key)
    return [*project, *home, *plugins]


def _macro_default_index(
    ordered: list[tuple[UnifiedSaveLocation, str]],
    rows: Sequence[UnifiedSaveLocation],
    *,
    last_used_path: str | None,
    current_path: str | None,
    home_mode: bool,
    selectable: list[int] | None = None,
    shadowed_ids: frozenset[str] = frozenset(),
    override: bool = False,
) -> int | None:
    """Return the display-order index of the default macro row."""
    del rows
    if selectable is None:
        selectable = [
            index for index, (row, _section) in enumerate(ordered) if row.is_selectable
        ]
    if not selectable:
        return None
    for index in selectable:
        if matches_path(ordered[index][0].location.path, current_path):
            return index
    for index in selectable:
        if matches_path(ordered[index][0].location.path, last_used_path):
            return index
    if override:
        for index in selectable:
            if ordered[index][0].location.path not in shadowed_ids:
                return index
        return selectable[0]
    if not home_mode:
        for index in selectable:
            if ordered[index][0].location.label == MACRO_PROJECT_DIR_LABEL:
                return index
    for index in selectable:
        if ordered[index][0].location.label == MACRO_HOME_DIR_LABEL:
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
    existing: ExistingRowSpec | None = None,
    override_name: str | None = None,
    shadowed_by: Mapping[str, str] | None = None,
) -> tuple[tuple[SaveLocationChoice, ...], str | None]:
    """Build picker choices for snippet config destinations.

    Returns the choices in display order plus the default choice id (``None``
    when nothing is selectable). The configured ``ace.snippet_config_path``
    gets its own top section with key ``c`` when it points outside the
    discovered files.
    """
    locations = tuple(locations)
    project_section = project_section_label(project)
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
            if matches_path(ordered[index].path, current_path):
                default_index = index
                break
        if default_index is None and resolved_target.source == "configured":
            for index in selectable:
                if ordered[index].path in (configured_path, configured_read):
                    default_index = index
                    break
        if default_index is None:
            for index in selectable:
                if matches_path(ordered[index].path, last_used_path):
                    default_index = index
                    break
        if override_name is not None:
            if default_index is None:
                shadowed_ids = set(shadowed_by or ())
                for index in selectable:
                    if ordered[index].path not in shadowed_ids:
                        default_index = index
                        break
            if default_index is None:
                default_index = selectable[0]
        elif default_index is None:
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
        if override_name is not None:
            snippet_default_reason = "override"
        else:
            default_entry = ordered[default_index]
            if matches_path(default_entry.path, current_path):
                snippet_default_reason = "current"
            elif (
                resolved_target.source == "configured"
                and default_entry.path == configured_path
            ):
                snippet_default_reason = "configured"
            elif matches_path(default_entry.path, last_used_path):
                snippet_default_reason = "last used"
            else:
                snippet_default_reason = "default"

    shadow_map = shadowed_by if override_name is not None else None
    choices: list[SaveLocationChoice] = []
    for index, entry in enumerate(ordered):
        is_default = index == default_index
        is_current = matches_path(entry.path, current_path)
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
                label=short_label(entry.label),
                display_path=entry.display_path,
                badges=badges(
                    default_reason=snippet_default_reason if is_default else None,
                    is_current=is_current,
                    has_name=has_trigger,
                    has_label=f"has ⇥ {trigger}" if has_trigger else "",
                    is_new=is_new,
                    chezmoi=via_chezmoi(entry.path),
                    shadowed_by=(shadow_map or {}).get(entry.path),
                ),
                disabled_reason=entry.disabled_reason,
                preview=snippet_preview(
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
    return _finish_choices(
        choices,
        final_default,
        existing=existing,
        override_name=override_name,
        kind="snippet",
    )


__all__ = [
    "ChangeSaveLocationRequest",
    "EXISTING_CHOICE_ID",
    "ExistingRowSpec",
    "SNIPPET_CONFIGURED_LABEL",
    "SNIPPET_CONFIGURED_SECTION",
    "SaveLocationChoice",
    "SaveLocationKind",
    "SaveLocationPick",
    "snippet_location_choices",
    "macro_location_choices",
]
