"""Snippet destination discovery, resolution, and collision detection.

This module is intentionally UI-free: it decides which config file a saved
``ace.snippets`` entry lands in and where that trigger already collides, but
it performs no Textual rendering. ACE's prompt bar and modals import it for
the ``gt`` snippet pane and the unified save panel's snippet mode alike.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]

from sase.config import CHEZMOI_HOME, CONFIG_DIR, get_use_chezmoi
from sase.content_layout import discover_project_root, resolve_project_layout

from .naming import ResolutionSource, resolution_after_save
from .save_index import names_for_location
from .write_targets import resolve_xprompt_write_target


@dataclass(frozen=True)
class SnippetConfigLocation:
    """A YAML config file where a snippet can be saved."""

    label: str
    path: str
    display_path: str
    disabled_reason: str | None = None

    @property
    def is_selectable(self) -> bool:
        return self.disabled_reason is None


def _short_display_path(path: str) -> str:
    home = str(Path.home())
    cwd = str(Path.cwd())
    if path.startswith(cwd + "/"):
        return "./" + path[len(cwd) + 1 :]
    if path.startswith(home + "/"):
        return "~" + path[len(home) :]
    return path


def _writability_reason(path: Path) -> str | None:
    if path.name == "sase.yml" and path.parent.name == "sase":
        legacy = path.parent.parent / "sase.yml"
        if legacy.is_file():
            return "migrate legacy project config first"
    if path.exists():
        if not path.is_file():
            return "not a file"
        if not os.access(path, os.W_OK):
            return "read-only"
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return "invalid YAML"
        if data is not None and not isinstance(data, dict):
            return "not a YAML mapping"
        return None

    ancestor = path.parent
    while not ancestor.exists() and ancestor.parent != ancestor:
        ancestor = ancestor.parent
    if not ancestor.exists() or not os.access(ancestor, os.W_OK):
        return "directory is not writable"
    return None


def load_snippet_config_locations(
    project: str | None = None,
) -> list[SnippetConfigLocation]:
    """Discover user config files offered by the unified snippet panel."""
    del project
    chezmoi = get_use_chezmoi()
    config_dir = CHEZMOI_HOME / "dot_config" / "sase" if chezmoi else CONFIG_DIR
    candidates: list[tuple[str, Path]] = [("User sase.yml", config_dir / "sase.yml")]
    if config_dir.is_dir():
        candidates.extend(
            (f"User {overlay.name}", overlay)
            for overlay in sorted(config_dir.glob("sase_*.yml"))
        )
    project_root = discover_project_root() or Path.cwd()
    local_config = resolve_project_layout(project_root).config.write_path
    candidates.append(("Project sase/sase.yml", local_config))
    return [
        SnippetConfigLocation(
            label=label,
            path=str(path),
            display_path=_short_display_path(str(path)),
            disabled_reason=_writability_reason(path),
        )
        for label, path in candidates
    ]


@dataclass(frozen=True)
class SnippetSaveTarget:
    """Where a saved ``ace.snippets`` entry is read from and written to."""

    read_path: Path
    write_path: Path
    apply_target: Path | None
    via_chezmoi: bool
    display_path: str
    source: Literal["configured", "default"]
    fallback_reason: str | None


def resolve_snippet_save_target(configured: str | None) -> SnippetSaveTarget:
    """Resolve the config file that receives a new ``ace.snippets`` entry.

    An empty/whitespace *configured* value, or one rejected by the checks
    below, falls back to the default location with ``fallback_reason`` set
    so callers can tell the user why their preference was not honored.
    """
    fallback_reason: str | None = None
    resolved: Path | None = None
    source: Literal["configured", "default"] = "default"

    stripped = (configured or "").strip()
    if stripped:
        expanded = os.path.expanduser(os.path.expandvars(stripped))
        candidate = Path(expanded)
        if not candidate.is_absolute():
            candidate = CONFIG_DIR / candidate
        if candidate.suffix not in {".yml", ".yaml"}:
            fallback_reason = "must be a .yml or .yaml file"
        else:
            reason = _writability_reason(candidate)
            if reason is not None:
                fallback_reason = reason
            else:
                resolved = candidate
                source = "configured"

    if resolved is None:
        resolved = (
            CHEZMOI_HOME / "dot_config" / "sase" / "sase.yml"
            if get_use_chezmoi()
            else CONFIG_DIR / "sase.yml"
        )
        source = "default"

    write_target = resolve_xprompt_write_target(resolved)
    return SnippetSaveTarget(
        read_path=write_target.read_path,
        write_path=write_target.write_path,
        apply_target=write_target.apply_target,
        via_chezmoi=write_target.via_chezmoi,
        display_path=_short_display_path(str(write_target.read_path)),
        source=source,
        fallback_reason=fallback_reason,
    )


@dataclass(frozen=True)
class SnippetTriggerMatch:
    """One config file that already defines a trigger."""

    trigger: str
    location_path: str
    display_path: str
    is_destination: bool


@dataclass(frozen=True)
class SnippetCollision:
    """Where a trigger collides today and who wins after a save."""

    matches: tuple[SnippetTriggerMatch, ...]
    derived_from: str | None
    winner_path: str | None
    shadowed_by: str | None
    shadows: str | None


def snippet_collision(
    trigger: str,
    destination: SnippetSaveTarget,
    *,
    locations: Sequence[SnippetConfigLocation],
    derived: Mapping[str, str],
) -> SnippetCollision:
    """Report where *trigger* is already defined and what saving would do.

    *locations* must be in first-wins discovery order, matching
    ``load_snippet_config_locations()``. When the resolved *destination*
    path is not among them (an out-of-discovery configured file), it is
    treated as the highest-precedence source, since it is where the user
    explicitly asked the entry to be written.
    """
    destination_path = str(destination.write_path)
    defines = {
        location.path: trigger in names_for_location("snippet_config", location.path)
        for location in locations
    }
    matches = tuple(
        SnippetTriggerMatch(
            trigger=trigger,
            location_path=location.path,
            display_path=location.display_path,
            is_destination=location.path == destination_path,
        )
        for location in locations
        if defines[location.path]
    )
    sources = [
        ResolutionSource(location.path, defines[location.path])
        for location in locations
    ]
    if destination_path not in defines:
        destination_defines = trigger in names_for_location(
            "snippet_config", destination_path
        )
        sources.insert(0, ResolutionSource(destination_path, destination_defines))
    resolution = resolution_after_save(destination_path, sources)
    winner_path = resolution.shadowed_by or destination_path
    return SnippetCollision(
        matches=matches,
        derived_from=derived.get(trigger),
        winner_path=winner_path,
        shadowed_by=resolution.shadowed_by,
        shadows=resolution.shadows,
    )


def load_snippet_template(path: str | Path, trigger: str) -> str:
    """Return the stored template for one ``ace.snippets`` trigger."""
    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    ace = payload.get("ace", {}) if isinstance(payload, dict) else {}
    snippets = ace.get("snippets", {}) if isinstance(ace, dict) else {}
    if not isinstance(snippets, dict) or trigger not in snippets:
        raise KeyError(trigger)
    return str(snippets[trigger])


__all__ = [
    "SnippetCollision",
    "SnippetConfigLocation",
    "SnippetSaveTarget",
    "SnippetTriggerMatch",
    "load_snippet_template",
    "load_snippet_config_locations",
    "resolve_snippet_save_target",
    "snippet_collision",
]
