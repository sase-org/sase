"""Config-file selector for saving a prompt draft as an ``ace.snippets`` entry.

Unlike :class:`~sase.ace.tui.modals.xprompt_location_modal.XPromptLocationModal`
-- which also offers xprompt *directories* and read-only built-in/plugin configs
-- this modal lists only writable user SASE YAML config files (the user
``sase.yml``, existing overlays, and an existing local ``./sase.yml``) where a
snippet can actually be stored. Discovery is a pure helper so it can run off the
Textual event loop.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import yaml  # type: ignore[import-untyped]
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.config import CHEZMOI_HOME, CONFIG_DIR, get_use_chezmoi

from .base import OptionListNavigationMixin


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
    """Return a reason the file at *path* cannot be written, or ``None``."""
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

    # File does not exist yet: ensure the nearest existing ancestor is writable
    # so the parent directory (and file) can be created.
    ancestor = path.parent
    while not ancestor.exists():
        parent = ancestor.parent
        if parent == ancestor:
            break
        ancestor = parent
    if not ancestor.exists() or not os.access(ancestor, os.W_OK):
        return "directory is not writable"
    return None


def load_snippet_config_locations(
    project: str | None = None,
) -> list[SnippetConfigLocation]:
    """Discover writable user SASE config files for snippet storage.

    Pure and side-effect free so it is safe to call from a worker thread. The
    user ``sase.yml`` is always offered (created on demand); overlays and the
    local ``./sase.yml`` appear only when they already exist. Paths are remapped
    to their chezmoi source when chezmoi management is enabled.
    """
    del project  # Snippets are not project-scoped; kept for signature parity.
    chezmoi = get_use_chezmoi()
    config_dir = CHEZMOI_HOME / "dot_config" / "sase" if chezmoi else CONFIG_DIR

    candidates: list[tuple[str, Path]] = []
    candidates.append(("User sase.yml", config_dir / "sase.yml"))
    if config_dir.is_dir():
        for overlay in sorted(config_dir.glob("sase_*.yml")):
            candidates.append((f"User {overlay.name}", overlay))
    local_config = Path.cwd() / "sase.yml"
    if local_config.is_file():
        candidates.append(("Local sase.yml", local_config))

    locations: list[SnippetConfigLocation] = []
    for label, path in candidates:
        locations.append(
            SnippetConfigLocation(
                label=label,
                path=str(path),
                display_path=_short_display_path(str(path)),
                disabled_reason=_writability_reason(path),
            )
        )
    return locations


class SnippetConfigLocationModal(
    OptionListNavigationMixin, ModalScreen["SnippetConfigLocation | None"]
):
    """Modal for choosing which config file stores the new snippet."""

    _option_list_id = "snippet-config-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "select_location", "Select"),
    ]

    def __init__(self, locations: list[SnippetConfigLocation]) -> None:
        super().__init__()
        self._locations = locations

    def compose(self) -> ComposeResult:
        with Container(id="snippet-config-container"):
            yield Label("Save snippet to config file", id="snippet-config-title")
            yield Label(
                "Choose where to store the new snippet:",
                id="snippet-config-hint",
            )
            with Vertical(id="snippet-config-list-panel"):
                yield OptionList(*self._create_options(), id="snippet-config-list")
            yield Static(
                "^n/^p navigate • enter select • Esc cancel",
                id="snippet-config-hints",
            )

    def on_mount(self) -> None:
        option_list = self.query_one("#snippet-config-list", OptionList)
        option_list.focus()
        self._skip_to_first_selectable(option_list)

    def _create_options(self) -> list[Option]:
        options: list[Option] = []
        for index, loc in enumerate(self._locations):
            text = Text()
            text.append("  📄 ", style="bold")
            text.append(loc.label, style="bold #87D7FF" if loc.is_selectable else "dim")
            text.append(f"\n     {loc.display_path}", style="dim")
            if loc.disabled_reason:
                text.append(f"  ({loc.disabled_reason})", style="italic #888888")
            options.append(
                Option(text, id=f"loc__{index}", disabled=not loc.is_selectable)
            )
        return options

    def _skip_to_first_selectable(self, option_list: OptionList) -> None:
        for index in range(option_list.option_count):
            try:
                option = option_list.get_option_at_index(index)
            except Exception:
                continue
            if option.id and not getattr(option, "disabled", False):
                option_list.highlighted = index
                return
        option_list.highlighted = None

    def _get_highlighted_location(self) -> SnippetConfigLocation | None:
        option_list = self.query_one("#snippet-config-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        if not option.id or getattr(option, "disabled", False):
            return None
        index = int(str(option.id).removeprefix("loc__"))
        if 0 <= index < len(self._locations):
            return self._locations[index]
        return None

    def action_select_location(self) -> None:
        loc = self._get_highlighted_location()
        if loc is not None and loc.is_selectable:
            self.dismiss(loc)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_select_location()


__all__ = [
    "SnippetConfigLocation",
    "SnippetConfigLocationModal",
    "load_snippet_config_locations",
]
