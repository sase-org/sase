"""XPrompt location selector modal for choosing where to create new xprompts."""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.config import CHEZMOI_HOME, CONFIG_DIR, get_use_chezmoi
from sase.plugin_discovery import discover_plugin_resources, is_plugin_disabled
from sase.xprompt.loader import detect_project, get_sase_package_xprompts_dir

from .base import FilterInput, OptionListNavigationMixin


def _shorten_display_path(path: str, cwd: str, home: str) -> str:
    """Shorten a path for display in the location selector.

    Paths under CWD become ``./relative``.  Other home-relative paths use
    ``~/…/last/segments`` when they exceed the column budget.
    """
    if path.startswith(cwd + "/"):
        return "./" + path[len(cwd) + 1 :]
    if path.startswith(home + "/") or path == home:
        display = "~" + path[len(home) :]
        if len(display) <= 42:
            return display
        parts = display.split("/")
        if len(parts) > 3:
            return parts[0] + "/…/" + "/".join(parts[-2:])
        return display
    return path


@dataclass
class XPromptLocation:
    """A location where xprompts can be created or edited."""

    label: str
    path: str
    location_type: Literal["directory", "config"]


def _get_all_xprompt_locations(
    project: str | None = None,
) -> list[tuple[str, list[XPromptLocation]]]:
    """Discover all xprompt locations grouped by category.

    Returns a list of ``(group_label, locations)`` tuples in display order.
    """
    effective_project = project if project is not None else detect_project()
    cwd = Path.cwd()
    home = Path.home()
    chezmoi = get_use_chezmoi()

    directories: list[XPromptLocation] = []
    configs: list[XPromptLocation] = []
    plugin_dirs: list[XPromptLocation] = []
    builtin: list[XPromptLocation] = []

    # --- 1. xprompts directories ---
    # .xprompts/ (CWD) — only if exists
    cwd_dot_xprompts = cwd / ".xprompts"
    if cwd_dot_xprompts.is_dir():
        directories.append(
            XPromptLocation(
                label="CWD .xprompts/",
                path=str(cwd_dot_xprompts),
                location_type="directory",
            )
        )
    # xprompts/ (CWD) — only if exists
    cwd_visible = cwd / "xprompts"
    if cwd_visible.is_dir():
        directories.append(
            XPromptLocation(
                label="CWD xprompts/",
                path=str(cwd_visible),
                location_type="directory",
            )
        )
    # ~/.xprompts/ — only if exists (remapped when chezmoi enabled)
    home_dot_xprompts = CHEZMOI_HOME / "dot_xprompts" if chezmoi else home / ".xprompts"
    if home_dot_xprompts.is_dir():
        directories.append(
            XPromptLocation(
                label="Home ~/.xprompts/",
                path=str(home_dot_xprompts),
                location_type="directory",
            )
        )
    # ~/xprompts/ — only if exists (remapped when chezmoi enabled)
    home_visible = CHEZMOI_HOME / "xprompts" if chezmoi else home / "xprompts"
    if home_visible.is_dir():
        directories.append(
            XPromptLocation(
                label="Home ~/xprompts/",
                path=str(home_visible),
                location_type="directory",
            )
        )
    # ~/.config/sase/xprompts/{project}/ — only if project detected and exists
    if effective_project:
        project_dir = home / ".config" / "sase" / "xprompts" / effective_project
        if project_dir.is_dir():
            directories.append(
                XPromptLocation(
                    label=f"Project ({effective_project})",
                    path=str(project_dir),
                    location_type="directory",
                )
            )

    # --- 2. Config files ---
    # ~/.config/sase/sase.yml — always show (remapped when chezmoi enabled)
    chezmoi_config_dir = CHEZMOI_HOME / "dot_config" / "sase"
    user_sase_yml = (
        chezmoi_config_dir / "sase.yml" if chezmoi else CONFIG_DIR / "sase.yml"
    )
    configs.append(
        XPromptLocation(
            label="User sase.yml",
            path=str(user_sase_yml),
            location_type="config",
        )
    )
    # Each sase_*.yml overlay — only existing ones (remapped when chezmoi enabled)
    overlay_glob_dir = chezmoi_config_dir if chezmoi else CONFIG_DIR
    if overlay_glob_dir.is_dir():
        for overlay_path in sorted(overlay_glob_dir.glob("sase_*.yml")):
            configs.append(
                XPromptLocation(
                    label=f"User {overlay_path.name}",
                    path=str(overlay_path),
                    location_type="config",
                )
            )
    # ./sase.yml (CWD) — only if exists
    local_config = cwd / "sase.yml"
    if local_config.is_file():
        configs.append(
            XPromptLocation(
                label="Local sase.yml",
                path=str(local_config),
                location_type="config",
            )
        )

    # --- 3. Plugin xprompts directories ---
    if not is_plugin_disabled("XPROMPTS"):
        for module in discover_plugin_resources("sase_xprompts"):
            try:
                xprompts_ref = importlib.resources.files(module).joinpath("xprompts")
                plugin_path = str(xprompts_ref)
                short_name = getattr(module, "__name__", str(module)).replace("_", "-")
                plugin_dirs.append(
                    XPromptLocation(
                        label=f"Plugin ({short_name}) xprompts/",
                        path=plugin_path,
                        location_type="directory",
                    )
                )
            except (TypeError, AttributeError):
                continue

    # --- 4. Built-in locations ---
    # sase package xprompts dir
    pkg_xprompts = get_sase_package_xprompts_dir()
    builtin.append(
        XPromptLocation(
            label="Built-in xprompts/",
            path=str(pkg_xprompts),
            location_type="directory",
        )
    )
    # sase default_config.yml
    try:
        default_cfg = str(
            importlib.resources.files("sase").joinpath("default_config.yml")
        )
        builtin.append(
            XPromptLocation(
                label="Built-in default_config.yml",
                path=default_cfg,
                location_type="config",
            )
        )
    except Exception:
        pass
    # Plugin default_config.yml files
    if not is_plugin_disabled("CONFIG"):
        for module in discover_plugin_resources("sase_config"):
            try:
                ref = importlib.resources.files(module).joinpath("default_config.yml")
                plugin_cfg_path = str(ref)
                short_name = getattr(module, "__name__", str(module)).replace("_", "-")
                builtin.append(
                    XPromptLocation(
                        label=f"Plugin ({short_name}) default_config.yml",
                        path=plugin_cfg_path,
                        location_type="config",
                    )
                )
            except Exception:
                continue

    groups: list[tuple[str, list[XPromptLocation]]] = []
    if directories:
        groups.append(("Directories", directories))
    if configs:
        groups.append(("Config Files", configs))
    if plugin_dirs:
        groups.append(("Plugin Directories", plugin_dirs))
    if builtin:
        groups.append(("Built-in", builtin))
    return groups


class _LocationFilterInput(FilterInput):
    """Filter input with forwarding for location modal actions."""

    BINDINGS = [
        *FilterInput.BINDINGS,
        ("ctrl+d", "scroll_preview_down", "Scroll Down"),
        ("ctrl+u", "scroll_preview_up_or_clear", "Scroll Up/Clear"),
        ("ctrl+n", "forward('next_option')", "Next"),
        ("ctrl+p", "forward('prev_option')", "Prev"),
        ("enter", "forward('select_location')", "Select"),
    ]

    def action_forward(self, action_name: str) -> None:
        modal = self.screen
        if isinstance(modal, XPromptLocationModal):
            getattr(modal, f"action_{action_name}")()

    def action_scroll_preview_down(self) -> None:
        modal = self.screen
        if isinstance(modal, XPromptLocationModal):
            modal.scroll_preview_down()

    def action_scroll_preview_up_or_clear(self) -> None:
        modal = self.screen
        if isinstance(modal, XPromptLocationModal):
            scroll = modal.query_one("#location-preview-scroll", VerticalScroll)
            if scroll.scroll_y > 0:
                modal.scroll_preview_up()
            elif self.cursor_position > 0:
                self.value = self.value[self.cursor_position :]
                self.cursor_position = 0


class XPromptLocationModal(
    OptionListNavigationMixin, ModalScreen[XPromptLocation | None]
):
    """Modal for selecting an xprompt location."""

    _option_list_id = "location-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "select_location", "Select"),
    ]

    def __init__(self, project: str | None = None) -> None:
        super().__init__()
        self._project = project
        self._groups = _get_all_xprompt_locations(project=project)
        self._flat: list[XPromptLocation] = []
        for _, locs in self._groups:
            self._flat.extend(locs)

    def compose(self) -> ComposeResult:
        with Container(id="location-container"):
            yield Label("Select Location", id="location-title")
            yield Label(
                "Choose where to create the new xprompt:",
                id="location-hint",
            )
            yield _LocationFilterInput(
                placeholder="Type to filter...",
                id="location-filter-input",
            )
            with Horizontal(id="location-panels"):
                with Vertical(id="location-list-panel"):
                    yield OptionList(
                        *self._create_options(),
                        id="location-list",
                    )
                with Vertical(id="location-preview-panel"):
                    with VerticalScroll(id="location-preview-scroll"):
                        yield Static("", id="location-preview")
            yield Static(
                "^n/^p: navigate  enter: select  ^d/^u: scroll  Esc: cancel",
                id="location-hints",
            )

    def _create_options(self, filter_text: str = "") -> list[Option]:
        filter_lower = filter_text.lower()
        home = str(Path.home())
        cwd = str(Path.cwd())
        options: list[Option] = []
        for group_label, locations in self._groups:
            filtered = (
                [
                    loc
                    for loc in locations
                    if not filter_lower
                    or filter_lower in loc.label.lower()
                    or filter_lower in loc.path.lower()
                ]
                if filter_lower
                else locations
            )
            if not filtered:
                continue
            header = Text(f"── {group_label} ──", style="bold dim")
            options.append(Option(header, id=f"__header__{group_label}", disabled=True))
            for loc in filtered:
                text = Text()
                display_path = _shorten_display_path(loc.path, cwd, home)
                exists = Path(loc.path).exists()
                if loc.location_type == "directory":
                    text.append("  📁 ", style="bold")
                else:
                    text.append("  📄 ", style="bold")
                text.append(loc.label, style="bold #87D7FF")
                text.append(f"\n     {display_path}", style="dim")
                if not exists:
                    text.append(" (new)", style="italic #FFD700")
                options.append(Option(text, id=f"loc__{id(loc)}"))
        return options

    def _get_filtered_flat(self, filter_text: str = "") -> list[XPromptLocation]:
        if not filter_text:
            return self._flat
        filter_lower = filter_text.lower()
        return [
            loc
            for loc in self._flat
            if filter_lower in loc.label.lower() or filter_lower in loc.path.lower()
        ]

    def on_mount(self) -> None:
        inp = self.query_one("#location-filter-input", _LocationFilterInput)
        inp.focus()
        option_list = self.query_one("#location-list", OptionList)
        self._skip_to_first_item(option_list)
        if self._flat:
            self._update_preview(self._flat[0])

    def _skip_to_first_item(self, option_list: OptionList) -> None:
        for i in range(option_list.option_count):
            try:
                opt = option_list.get_option_at_index(i)
                if opt.id and not str(opt.id).startswith("__header__"):
                    option_list.highlighted = i
                    return
            except Exception:
                continue

    def on_input_changed(self, event: Input.Changed) -> None:
        option_list = self.query_one("#location-list", OptionList)
        option_list.clear_options()
        for opt in self._create_options(event.value):
            option_list.add_option(opt)
        filtered = self._get_filtered_flat(event.value)
        if filtered:
            self._skip_to_first_item(option_list)
            self._update_preview(filtered[0])
        else:
            self._clear_preview()

    def action_next_option(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        current = option_list.highlighted
        if current is None:
            self._skip_to_first_item(option_list)
            return
        for i in range(current + 1, option_list.option_count):
            try:
                opt = option_list.get_option_at_index(i)
                if opt.id and not str(opt.id).startswith("__header__"):
                    option_list.highlighted = i
                    return
            except Exception:
                continue

    def action_prev_option(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        current = option_list.highlighted
        if current is None:
            return
        for i in range(current - 1, -1, -1):
            try:
                opt = option_list.get_option_at_index(i)
                if opt.id and not str(opt.id).startswith("__header__"):
                    option_list.highlighted = i
                    return
            except Exception:
                continue

    def _get_highlighted_location(self) -> XPromptLocation | None:
        option_list = self.query_one("#location-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            opt = option_list.get_option_at_index(highlighted)
            if not opt.id or str(opt.id).startswith("__header__"):
                return None
        except Exception:
            return None
        # Match by position: count non-header items up to highlighted
        filter_input = self.query_one("#location-filter-input", _LocationFilterInput)
        filtered = self._get_filtered_flat(filter_input.value)
        idx = 0
        for i in range(option_list.option_count):
            try:
                o = option_list.get_option_at_index(i)
                if o.id and not str(o.id).startswith("__header__"):
                    if i == highlighted:
                        return filtered[idx] if idx < len(filtered) else None
                    idx += 1
            except Exception:
                continue
        return None

    def action_select_location(self) -> None:
        loc = self._get_highlighted_location()
        if loc is not None:
            self.dismiss(loc)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        loc = self._get_highlighted_location()
        if loc is not None:
            self._update_preview(loc)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        loc = self._get_highlighted_location()
        if loc is not None:
            self.dismiss(loc)

    # -- Preview rendering ---------------------------------------------------

    def _update_preview(self, loc: XPromptLocation) -> None:
        """Update the preview panel for the given location."""
        try:
            preview = self.query_one("#location-preview", Static)
        except Exception:
            return

        p = Path(loc.path)
        if not p.exists():
            preview.update(Text("(path does not exist yet)", style="italic dim"))
            return

        if loc.location_type == "directory":
            preview.update(self._render_directory_tree(p))
        else:
            preview.update(self._render_file_preview(p))

    def _render_directory_tree(self, directory: Path) -> Syntax | Text:
        """Render a pretty tree of directory contents."""
        try:
            entries = sorted(
                directory.iterdir(), key=lambda e: (not e.is_dir(), e.name)
            )
        except PermissionError:
            return Text("(permission denied)", style="italic dim")

        if not entries:
            return Text("(empty directory)", style="italic dim")

        lines: list[str] = [f"{directory.name}/"]
        self._build_tree_lines(entries, "", lines)
        return Syntax("\n".join(lines), "text", theme="monokai", word_wrap=True)

    def _build_tree_lines(
        self,
        entries: list[Path],
        prefix: str,
        lines: list[str],
        *,
        max_depth: int = 2,
        _depth: int = 0,
    ) -> None:
        """Recursively build tree lines up to *max_depth*."""
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")

            if entry.is_dir() and _depth < max_depth:
                try:
                    children = sorted(
                        entry.iterdir(), key=lambda e: (not e.is_dir(), e.name)
                    )
                except PermissionError:
                    children = []
                extension = "    " if is_last else "│   "
                self._build_tree_lines(
                    children,
                    prefix + extension,
                    lines,
                    max_depth=max_depth,
                    _depth=_depth + 1,
                )

    def _render_file_preview(self, filepath: Path) -> Syntax | Text:
        """Render syntax-highlighted file contents."""
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return Text("(permission denied)", style="italic dim")
        except Exception:
            return Text("(unable to read file)", style="italic dim")

        lexer = "yaml" if filepath.suffix in (".yml", ".yaml") else "text"
        return Syntax(
            content, lexer, theme="monokai", word_wrap=True, line_numbers=True
        )

    def _clear_preview(self) -> None:
        """Clear the preview panel."""
        try:
            self.query_one("#location-preview", Static).update("")
        except Exception:
            pass

    # -- Preview scrolling ---------------------------------------------------

    def scroll_preview_down(self) -> None:
        scroll = self.query_one("#location-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def scroll_preview_up(self) -> None:
        scroll = self.query_one("#location-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)
