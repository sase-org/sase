"""Location discovery and forwarding widgets for the unified save panel."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Literal

from textual.binding import Binding
from textual.widgets import Input, OptionList
import yaml  # type: ignore[import-untyped]

from sase.config import get_use_chezmoi
from sase.content_layout import (
    discover_project_root,
    resolve_chezmoi_layout,
    resolve_home_layout,
    resolve_project_layout,
)
from sase.config import CHEZMOI_HOME
from sase.xprompt.loader import detect_project
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import SaveTargetFormat
from sase.xprompt.save_index import IndexKind, names_for_location
from sase.xprompt.skill_locations import SkillDestination, skill_destinations
from sase.xprompt.snippet_targets import (
    SnippetSaveTarget,
    load_snippet_config_locations,
)

from .xprompt_location_modal import (
    XPromptLocation,
    get_all_xprompt_locations,
    shorten_xprompt_location_path,
)

SaveMode = Literal["xprompt", "snippet"]


@dataclass(frozen=True, slots=True)
class UnifiedSaveLocation:
    """Indexed destination row shared by xprompt and snippet save modes."""

    location: XPromptLocation
    group: str
    display_path: str
    names: frozenset[str]
    disabled_reason: str | None = None
    will_create: bool = False
    builtin: bool = False
    precedence: int = 0
    namespace: str | None = None
    is_skill_destination: bool = False
    """Whether this row is a canonical ``skills/`` directory.

    Skill rows leave :attr:`namespace` unset: the typed name is both the file
    name and the ``/`` skill name, and only the ``#`` reference is namespaced.
    :attr:`skill_project` carries that namespace instead.
    """
    skill_project: str | None = None

    @property
    def is_selectable(self) -> bool:
        return self.disabled_reason is None


@dataclass(frozen=True, slots=True)
class UnifiedXPromptSaveResult:
    """One fully armed save operation returned by the unified panel."""

    mode: SaveMode
    name: str
    path: str
    location_path: str
    target_format: SaveTargetFormat | None
    entry_name: str | None
    display_path: str
    exists: bool
    frontmatter: PromptFrontmatter


def load_unified_save_locations(
    project: str | None,
    *,
    skill: bool = False,
) -> list[UnifiedSaveLocation]:
    """Build a names-only xprompt destination index off the event loop.

    A draft declaring ``skill:`` is only offered canonical ``skills/``
    directories, because that is the only placement discovery accepts.
    """
    effective_project = project if project is not None else detect_project()
    if skill:
        return _skill_save_locations(effective_project)
    grouped = get_all_xprompt_locations(project)
    locations: list[tuple[str, XPromptLocation]] = [
        (group, location)
        for group, group_locations in grouped
        for location in group_locations
    ]
    locations = _with_missing_standard_directories(locations)
    cwd = str(Path.cwd())
    home = str(Path.home())
    rows: list[UnifiedSaveLocation] = []
    for ordinal, (source_group, location) in enumerate(locations):
        path = Path(location.path)
        group = _display_group(source_group, location.label)
        kind: IndexKind = (
            "directory" if location.location_type == "directory" else "xprompt_config"
        )
        rows.append(
            UnifiedSaveLocation(
                location=location,
                group=group,
                display_path=shorten_xprompt_location_path(location.path, cwd, home),
                names=names_for_location(kind, location.path),
                disabled_reason=_writability_reason(path, location.location_type),
                will_create=not path.exists(),
                builtin=group == "Built-in (dev)",
                precedence=_precedence(source_group, location.label, ordinal),
                namespace=(
                    effective_project
                    if effective_project and (location.label.startswith("Project"))
                    else None
                ),
            )
        )
    group_order = {
        "Project": 0,
        "CWD directories": 1,
        "Home directories": 2,
        "Config files": 3,
        "Plugin directories": 4,
        "Built-in (dev)": 5,
    }
    return sorted(rows, key=lambda row: (group_order[row.group], row.precedence))


def _skill_save_locations(project: str | None) -> list[UnifiedSaveLocation]:
    """Build destination rows for the canonical skill directories."""
    return [
        _skill_save_location(destination, precedence, project)
        for precedence, destination in enumerate(skill_destinations(project))
    ]


def _skill_save_location(
    destination: SkillDestination,
    precedence: int,
    project: str | None,
) -> UnifiedSaveLocation:
    """Turn one canonical skill directory into a destination row."""
    path = destination.path
    return UnifiedSaveLocation(
        location=XPromptLocation(destination.label, str(path), "directory"),
        group="Built-in (dev)" if destination.builtin else "Skill directories",
        display_path=shorten_xprompt_location_path(
            str(path), str(Path.cwd()), str(Path.home())
        ),
        names=names_for_location("directory", str(path)),
        disabled_reason=_writability_reason(path, "directory"),
        will_create=not path.exists(),
        builtin=destination.builtin,
        precedence=precedence,
        is_skill_destination=True,
        skill_project=project if destination.project_namespaced else None,
    )


def load_unified_snippet_locations(
    project: str | None,
) -> list[UnifiedSaveLocation]:
    """Build names-only snippet config rows off the event loop."""
    rows: list[UnifiedSaveLocation] = []
    for ordinal, location in enumerate(load_snippet_config_locations(project)):
        rows.append(
            UnifiedSaveLocation(
                location=XPromptLocation(location.label, location.path, "config"),
                group="Config files",
                display_path=location.display_path,
                names=names_for_location("snippet_config", location.path),
                disabled_reason=location.disabled_reason,
                will_create=not Path(location.path).exists(),
                precedence=ordinal,
            )
        )
    return rows


def ensure_unified_snippet_target_location(
    rows: list[UnifiedSaveLocation],
    target: SnippetSaveTarget,
) -> list[UnifiedSaveLocation]:
    """Return rows with the resolved snippet target selectable.

    ``ace.snippet_config_path`` may point at a valid YAML file that is not one
    of the standard discovered config files. The snippet pane can still write
    there directly, so the unified save panel's snippet mode must offer the
    same destination instead of falling back to the first discovered row.
    """
    path = str(target.write_path)
    if any(row.location.path == path for row in rows):
        return rows
    configured = UnifiedSaveLocation(
        location=XPromptLocation("Configured snippet config", path, "config"),
        group="Config files",
        display_path=target.display_path,
        names=names_for_location("snippet_config", path),
        disabled_reason=None,
        will_create=not Path(path).exists(),
        precedence=-1,
    )
    return [configured, *rows]


def _with_missing_standard_directories(
    locations: list[tuple[str, XPromptLocation]],
) -> list[tuple[str, XPromptLocation]]:
    existing = {location.path for _, location in locations}
    project_root = discover_project_root() or Path.cwd()
    project_dir = resolve_project_layout(project_root).xprompts.write_path
    home_dir = (
        resolve_chezmoi_layout(CHEZMOI_HOME).xprompts.write_path
        if get_use_chezmoi()
        else resolve_home_layout().xprompts.write_path
    )
    additions = [
        (
            "Directories",
            XPromptLocation("Project sase/xprompts/", str(project_dir), "directory"),
        ),
        (
            "Directories",
            XPromptLocation("Home ~/sase/xprompts/", str(home_dir), "directory"),
        ),
    ]
    return locations + [item for item in additions if item[1].path not in existing]


def _display_group(source_group: str, label: str) -> str:
    if source_group == "Built-in":
        return "Built-in (dev)"
    if source_group == "Plugin Directories":
        return "Plugin directories"
    if source_group == "Config Files":
        return "Config files"
    if label.startswith("Project"):
        return "Project"
    if label.startswith("CWD "):
        return "CWD directories"
    return "Home directories"


def _precedence(source_group: str, label: str, ordinal: int) -> int:
    """Map display locations onto loader first-wins discovery order."""
    if label == "Project sase/xprompts/":
        return 0
    if label == "Home ~/sase/xprompts/":
        return 1
    if label.startswith("Project home ("):
        return 2
    if label == "Project sase/sase.yml":
        return 10
    if label.startswith("User sase_"):
        return 20 - ordinal
    if label == "User sase.yml":
        return 21
    if "default_config.yml" in label:
        return 30
    if source_group == "Plugin Directories":
        return 40 + ordinal
    if "default_xprompts" in label:
        return 50
    if source_group == "Built-in":
        return 60 + ordinal
    return 100 + ordinal


def _writability_reason(
    path: Path,
    location_type: Literal["directory", "config"],
) -> str | None:
    if (
        location_type == "config"
        and path.name == "sase.yml"
        and path.parent.name == "sase"
    ):
        legacy = path.parent.parent / "sase.yml"
        if legacy.is_file():
            return "migrate legacy project config first"
    if path.exists():
        if location_type == "directory":
            if not path.is_dir():
                return "not a directory"
            return None if os.access(path, os.W_OK) else "read-only"
        if not path.is_file():
            return "not a file"
        if not os.access(path, os.W_OK):
            return "read-only"
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return "invalid YAML"
        return None if payload is None or isinstance(payload, dict) else "not a mapping"

    ancestor = path.parent
    while not ancestor.exists() and ancestor.parent != ancestor:
        ancestor = ancestor.parent
    return (
        None
        if ancestor.exists() and os.access(ancestor, os.W_OK)
        else "directory is not writable"
    )


class UnifiedSaveInput(Input):
    """Single-line field whose unused arrows navigate destinations."""

    BINDINGS = [
        Binding("up", "forward('prev_location')", show=False),
        Binding("down", "forward('next_location')", show=False),
        Binding("ctrl+n", "forward('next_location')", show=False),
        Binding("ctrl+p", "forward('prev_location')", show=False),
    ]

    def action_forward(self, action_name: str) -> None:
        action = getattr(self.screen, f"action_{action_name}", None)
        if callable(action):
            action()


class UnifiedDestinationList(OptionList):
    """Destination list with vim-style navigation while it has focus."""

    BINDINGS = [
        Binding("j", "forward('next_location')", show=False),
        Binding("k", "forward('prev_location')", show=False),
    ]

    def action_forward(self, action_name: str) -> None:
        action = getattr(self.screen, f"action_{action_name}", None)
        if callable(action):
            action()


__all__ = [
    "SaveMode",
    "UnifiedDestinationList",
    "UnifiedSaveInput",
    "UnifiedSaveLocation",
    "UnifiedXPromptSaveResult",
    "ensure_unified_snippet_target_location",
    "load_unified_save_locations",
    "load_unified_snippet_locations",
]
