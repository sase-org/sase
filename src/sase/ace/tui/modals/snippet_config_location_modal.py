"""Discovery of config files that can store ``ace.snippets`` entries."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from sase.config import CHEZMOI_HOME, CONFIG_DIR, get_use_chezmoi
from sase.content_layout import discover_project_root, resolve_project_layout


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


__all__ = ["SnippetConfigLocation", "load_snippet_config_locations"]
