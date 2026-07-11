"""One-screen xprompt save-as: name, location, collision, and preview."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option
import yaml  # type: ignore[import-untyped]

from sase.xprompt.save import SaveTargetFormat, load_config_xprompt_markdown

from .xprompt_location_modal import XPromptLocation, get_all_xprompt_locations
from .xprompt_save_target_modal import XPromptSaveTarget


@dataclass(frozen=True)
class _UnifiedSaveLocation:
    location: XPromptLocation
    definitions: dict[str, str]


def load_unified_save_locations(project: str | None) -> list[_UnifiedSaveLocation]:
    """Load location/collision previews off the Textual event loop."""
    result: list[_UnifiedSaveLocation] = []
    for _, locations in get_all_xprompt_locations(project):
        for location in locations:
            definitions: dict[str, str] = {}
            path = Path(location.path)
            if location.location_type == "directory" and path.is_dir():
                for source in path.glob("*.md"):
                    try:
                        definitions[source.stem] = source.read_text(encoding="utf-8")
                    except OSError:
                        pass
            elif location.location_type == "config" and path.is_file():
                try:
                    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                    names = (
                        payload.get("xprompts", {}) if isinstance(payload, dict) else {}
                    )
                    if isinstance(names, dict):
                        for name in names:
                            try:
                                definitions[str(name)] = load_config_xprompt_markdown(
                                    path, str(name)
                                )
                            except Exception:
                                definitions[str(name)] = "(preview unavailable)"
                except Exception:
                    pass
            result.append(_UnifiedSaveLocation(location, definitions))
    return result


class UnifiedXPromptSaveModal(ModalScreen[XPromptSaveTarget | None]):
    """Save to a selected storage surface with live collision visibility."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+n", "next_location", "Next"),
        ("ctrl+p", "prev_location", "Previous"),
        ("ctrl+t", "save_snippet", "Snippet"),
    ]

    def __init__(
        self,
        locations: list[_UnifiedSaveLocation],
        *,
        initial_name: str = "",
        allow_create_snippet: bool = False,
    ) -> None:
        super().__init__()
        self._locations = locations
        self._initial_name = initial_name
        self._allow_create_snippet = allow_create_snippet

    def compose(self) -> ComposeResult:
        with Container(id="unified-save-container"):
            yield Label("Save draft as xprompt", id="unified-save-title")
            yield Input(
                value=self._initial_name,
                placeholder="xprompt name",
                id="unified-save-name",
            )
            with Horizontal(id="unified-save-panels"):
                with Vertical(id="unified-save-locations-panel"):
                    yield OptionList(
                        *[
                            Option(
                                f"{row.location.label}\n  {row.location.path}",
                                id=f"location-{index}",
                            )
                            for index, row in enumerate(self._locations)
                        ],
                        id="unified-save-locations",
                    )
                with Vertical(id="unified-save-preview-panel"):
                    yield Static("", id="unified-save-status")
                    yield Static("", id="unified-save-preview")
            snippet_hint = " · ctrl+t snippet" if self._allow_create_snippet else ""
            yield Static(
                f"ctrl+n/ctrl+p location · enter save{snippet_hint} · esc cancel",
                id="unified-save-hints",
            )

    def on_mount(self) -> None:
        locations = self.query_one("#unified-save-locations", OptionList)
        if self._locations:
            locations.highlighted = 0
        name = self.query_one("#unified-save-name", Input)
        name.focus()
        name.cursor_position = len(name.value)
        self._refresh_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "unified-save-name":
            self._refresh_preview()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "unified-save-name":
            self.action_save()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        self._refresh_preview()

    def _selected_index(self) -> int | None:
        highlighted = self.query_one("#unified-save-locations", OptionList).highlighted
        return (
            highlighted
            if highlighted is not None and highlighted < len(self._locations)
            else None
        )

    def _current_name(self) -> str:
        return self.query_one("#unified-save-name", Input).value.strip()

    def _refresh_preview(self) -> None:
        index = self._selected_index()
        status = self.query_one("#unified-save-status", Static)
        preview = self.query_one("#unified-save-preview", Static)
        if index is None:
            status.update(Text("No writable locations found", style="red"))
            preview.update("")
            return
        name = self._current_name()
        row = self._locations[index]
        existing = row.definitions.get(name)
        if existing is None:
            status.update(
                Text(f"Create #{name}" if name else "Enter a name", style="#00D7AF")
            )
            preview.update(Text(row.location.path, style="dim"))
        else:
            status.update(Text(f"Overwrite #{name}", style="bold #FFD700"))
            preview.update(existing[:4000])

    def action_next_location(self) -> None:
        options = self.query_one("#unified-save-locations", OptionList)
        current = options.highlighted or 0
        options.highlighted = min(current + 1, max(0, len(self._locations) - 1))

    def action_prev_location(self) -> None:
        options = self.query_one("#unified-save-locations", OptionList)
        current = options.highlighted or 0
        options.highlighted = max(0, current - 1)

    def action_save(self) -> None:
        index = self._selected_index()
        name = self._current_name()
        if index is None or not name:
            return
        row = self._locations[index]
        location = row.location
        exists = name in row.definitions
        if location.location_type == "directory":
            path = str(Path(location.path) / (name.replace("/", "_") + ".md"))
            target_format = SaveTargetFormat.MARKDOWN
            entry_name = None
        else:
            path = location.path
            target_format = SaveTargetFormat.CONFIG
            entry_name = name
        self.dismiss(
            XPromptSaveTarget(
                kind="write",
                name=name,
                path=path,
                target_format=target_format,
                entry_name=entry_name,
                display_path=path,
                exists=exists,
            )
        )

    def action_save_snippet(self) -> None:
        if self._allow_create_snippet:
            self.dismiss(XPromptSaveTarget(kind="create_snippet"))

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = [
    "UnifiedXPromptSaveModal",
    "load_unified_save_locations",
]
