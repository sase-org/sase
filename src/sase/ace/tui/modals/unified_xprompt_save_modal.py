"""Keyboard-first, truthful save panel for xprompts and snippets."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.xprompt.naming import (
    ResolutionSource,
    SaveResolution,
    markdown_save_plan,
    resolution_after_save,
    validate_snippet_trigger,
    validate_xprompt_name,
)
from sase.content_layout import skill_reference_name
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import SaveTargetFormat
from sase.xprompt.save_index import (
    DefinitionKind,
    load_definition,
)

from .unified_xprompt_save_destinations import (
    UnifiedXPromptSaveDestinationsMixin,
)
from .unified_xprompt_save_preview import (
    PreviewTab,
    UnifiedXPromptSavePreviewMixin,
)
from .unified_xprompt_save_support import (
    SaveMode,
    UnifiedDestinationList,
    UnifiedSaveInput,
    UnifiedSaveLocation,
    UnifiedXPromptSaveResult,
    load_unified_save_locations,
    load_unified_snippet_locations,
)
from .xprompt_location_modal import shorten_xprompt_location_path


# Compatibility name retained for tests and third-party imports from the
# short-lived first version of this modal.
_UnifiedSaveLocation = UnifiedSaveLocation


class UnifiedXPromptSaveModal(
    UnifiedXPromptSaveDestinationsMixin,
    UnifiedXPromptSavePreviewMixin,
    ModalScreen[UnifiedXPromptSaveResult | None],
):
    """Save a draft with live validation, collision evidence, and one verdict."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+n", "next_location", "Next destination", show=False),
        Binding("ctrl+p", "prev_location", "Previous destination", show=False),
        Binding(
            "ctrl+x",
            "toggle_mode",
            "Xprompt / snippet",
            show=False,
            priority=True,
        ),
        Binding("ctrl+o", "cycle_preview", "Cycle preview", show=False),
        Binding("ctrl+d", "scroll_preview_down", "Scroll down", show=False),
        Binding("ctrl+u", "scroll_preview_up", "Scroll up", show=False),
        Binding("enter", "save", "Save", show=False),
    ]

    def __init__(
        self,
        locations: list[UnifiedSaveLocation],
        *,
        snippet_locations: list[UnifiedSaveLocation] | None = None,
        frontmatter: PromptFrontmatter | None = None,
        body: str = "",
        snippet_body: str = "",
        pane_count: int = 1,
        initial_name: str = "",
        last_used: dict[SaveMode, str] | None = None,
    ) -> None:
        super().__init__()
        self._locations_by_mode = {
            "xprompt": locations,
            "snippet": snippet_locations or [],
        }
        self._frontmatter = frontmatter or PromptFrontmatter()
        self._body = body
        self._snippet_body = snippet_body
        self._pane_count = pane_count
        self._last_used = last_used or {}
        self._mode: SaveMode = "xprompt"
        self._mode_names: dict[SaveMode, str] = {
            "xprompt": initial_name,
            "snippet": "",
        }
        self._preview_tab: PreviewTab = "draft"
        self._armed_identity: tuple[SaveMode, str, str] | None = None
        self._armed_at = 0.0
        self._updating_options = False
        self._updating_fields = False
        self._preview_debouncer: DetailPanelDebouncer | None = None
        self._preview_tasks: set[asyncio.Task[None]] = set()
        self._existing_cache: dict[tuple[SaveMode, str, str], str] = {}

    @property
    def _locations(self) -> list[UnifiedSaveLocation]:
        return self._locations_by_mode[self._mode]

    def compose(self) -> ComposeResult:
        with Container(id="unified-save-container"):
            yield Label("", id="unified-save-title")
            with Horizontal(classes="unified-save-field", id="unified-save-name-row"):
                yield Label("Name", classes="unified-save-field-label")
                yield UnifiedSaveInput(
                    value=self._mode_names["xprompt"],
                    placeholder="code_review_swarm",
                    id="unified-save-name",
                )
            with Horizontal(
                classes="unified-save-field", id="unified-save-description-row"
            ):
                yield Label("Description", classes="unified-save-field-label")
                yield UnifiedSaveInput(
                    value=self._frontmatter.description or "",
                    placeholder="Optional metadata",
                    id="unified-save-description",
                )
            with Horizontal(id="unified-save-panels"):
                with Vertical(id="unified-save-locations-panel"):
                    yield Static("Destination", classes="unified-save-panel-title")
                    yield UnifiedDestinationList(id="unified-save-locations")
                with Vertical(id="unified-save-preview-panel"):
                    yield Static("", id="unified-save-preview-header", markup=False)
                    with VerticalScroll(id="unified-save-preview-scroll"):
                        yield Static("", id="unified-save-preview", markup=False)
            yield Static("", id="unified-save-verdict", markup=False)
            yield Static(
                "↑↓ destination · tab next field · ^o preview · ^x snippet · ^d/^u scroll · esc cancel",
                id="unified-save-hints",
                markup=False,
            )

    def on_mount(self) -> None:
        self._preview_debouncer = DetailPanelDebouncer(self.app)
        self._sync_mode(first_mount=True)
        name = self.query_one("#unified-save-name", UnifiedSaveInput)
        name.focus()
        name.cursor_position = len(name.value)

    def on_unmount(self) -> None:
        if self._preview_debouncer is not None:
            self._preview_debouncer.cancel()
        for task in self._preview_tasks:
            task.cancel()

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._updating_fields:
            return
        if event.input.id == "unified-save-name":
            self._mode_names[self._mode] = event.value
            selected = self._selected_location_path()
            self._disarm()
            self._rebuild_options(selected)
        elif event.input.id == "unified-save-description":
            self._disarm()
        self._refresh()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id in {"unified-save-name", "unified-save-description"}:
            self.action_save()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if self._updating_options:
            return
        self._disarm()
        self._preview_tab = "diff" if self._current_collision() else "draft"
        self._refresh()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_save()

    def action_toggle_mode(self) -> None:
        name = self.query_one("#unified-save-name", UnifiedSaveInput)
        self._mode_names[self._mode] = name.value
        self._mode = "snippet" if self._mode == "xprompt" else "xprompt"
        self._disarm()
        self._preview_tab = "draft"
        self._sync_mode(first_mount=False)

    def _sync_mode(self, *, first_mount: bool) -> None:
        self._updating_fields = True
        try:
            name = self.query_one("#unified-save-name", UnifiedSaveInput)
            name.value = self._mode_names[self._mode]
            name.placeholder = (
                "snippet_trigger" if self._mode == "snippet" else "code_review_swarm"
            )
        finally:
            self._updating_fields = False
        self.query_one("#unified-save-description-row", Horizontal).display = (
            self._mode == "xprompt"
        )
        self._update_title()
        preferred = self._default_location_path()
        self._rebuild_options(preferred)
        self._refresh()

    def _update_title(self) -> None:
        pane_word = "pane" if self._pane_count == 1 else "panes"
        if self._mode == "snippet":
            suffix = f"active pane · {self._pane_count} {pane_word} in draft"
            title = f"Save pane as snippet — {suffix}"
        else:
            marker = "✓" if not self._frontmatter.is_empty else "—"
            noun = "skill" if self._frontmatter.skill else "xprompt"
            title = (
                f"Save draft as {noun} — {self._pane_count} {pane_word} · "
                f"frontmatter {marker}"
            )
        self.query_one("#unified-save-title", Label).update(title)

    def _current_name(self) -> str:
        return self.query_one("#unified-save-name", UnifiedSaveInput).value.strip()

    def _validation_error(self) -> str | None:
        name = self._current_name()
        if self._mode == "snippet":
            if not self._snippet_body.strip():
                return "The active pane is empty"
            return validate_snippet_trigger(name)
        error = validate_xprompt_name(name)
        if error is not None:
            return error
        row = self._selected_row()
        if row is not None and row.namespace:
            prefix = f"{row.namespace}/"
            if not name.startswith(prefix):
                return f"Names saved here must start with {prefix}"
            return validate_xprompt_name(name.removeprefix(prefix))
        return None

    def _storage_name(self, row: UnifiedSaveLocation, name: str) -> str:
        if row.namespace:
            return name.removeprefix(f"{row.namespace}/")
        return name

    def _prepared_frontmatter(self) -> PromptFrontmatter:
        description = self.query_one(
            "#unified-save-description", UnifiedSaveInput
        ).value.strip()
        if description:
            return replace(self._frontmatter, description=description)
        return replace(self._frontmatter)

    def _target_path(self, row: UnifiedSaveLocation, name: str) -> str:
        if self._mode == "xprompt" and row.location.location_type == "directory":
            filename, _ = markdown_save_plan(
                self._storage_name(row, name), self._prepared_frontmatter()
            )
            return str(Path(row.location.path) / filename)
        return row.location.path

    def _collision_key(self, row: UnifiedSaveLocation, name: str) -> str:
        if self._mode == "xprompt" and row.location.location_type == "directory":
            filename, _ = markdown_save_plan(
                self._storage_name(row, name), self._prepared_frontmatter()
            )
            return Path(filename).stem
        return self._storage_name(row, name)

    def _collides(self, row: UnifiedSaveLocation, name: str) -> bool:
        return bool(name) and self._collision_key(row, name) in row.names

    def _current_collision(self) -> bool:
        row = self._selected_row()
        return row is not None and self._collides(row, self._current_name())

    def _identity(self) -> tuple[SaveMode, str, str] | None:
        row = self._selected_row()
        name = self._current_name()
        if row is None or not name:
            return None
        return (self._mode, row.location.path, name)

    def _disarm(self) -> None:
        self._armed_identity = None
        self._armed_at = 0.0

    def _resolution(self, row: UnifiedSaveLocation, name: str) -> SaveResolution:
        sources = [
            ResolutionSource(
                candidate.location.path,
                self._collides(candidate, name),
            )
            for candidate in sorted(self._locations, key=lambda item: item.precedence)
        ]
        return resolution_after_save(row.location.path, sources)

    def _refresh(self) -> None:
        self._refresh_verdict()
        self._refresh_preview()

    @staticmethod
    def _load_definition(kind: DefinitionKind, path: str, definition_name: str) -> str:
        """Load through this module to preserve its monkeypatching boundary."""
        return load_definition(kind, path, definition_name)

    def _refresh_verdict(self) -> None:
        verdict = self.query_one("#unified-save-verdict", Static)
        error = self._validation_error()
        row = self._selected_row()
        if row is None:
            verdict.set_classes("unified-save-verdict-error")
            verdict.update("✗ No writable destinations found")
            return
        if error is not None:
            verdict.set_classes("unified-save-verdict-error")
            verdict.update(f"✗ Invalid name: {error}")
            return
        name = self._current_name()
        path = self._target_path(row, name)
        display = shorten_xprompt_location_path(path, str(Path.cwd()), str(Path.home()))
        collision = self._collides(row, name)
        resolution = self._resolution(row, name)
        identity = self._identity()
        reference = self._reference_label(row, name)
        if collision:
            verdict.set_classes("unified-save-verdict-warning")
            if self._armed_identity == identity:
                message = f"⚠ Press Enter again to overwrite {reference} at {display}"
            else:
                message = f"⚠ {reference} exists here — press Enter to review overwrite"
            if resolution.shadowed_by:
                message += f" · shadowed by {self._short_path(resolution.shadowed_by)}"
            verdict.update(message)
            return
        if resolution.shadowed_by:
            verdict.set_classes("unified-save-verdict-warning")
            verdict.update(
                f"⚠ Saving here will be shadowed by {self._short_path(resolution.shadowed_by)}"
            )
            return
        verdict.set_classes("unified-save-verdict-success")
        message = f"✓ Create {reference} at {display}"
        if resolution.shadows:
            message += f" · shadows {self._short_path(resolution.shadows)}"
        verdict.update(message)

    @staticmethod
    def _reference_label(row: UnifiedSaveLocation, name: str) -> str:
        """Return how the saved definition will be referenced.

        A skill has two names: the namespaced ``#`` reference that expands it
        and the ``/`` name it installs as. Both are shown so the panel never
        implies a skill answers to ``#<name>``.
        """
        if not row.is_skill_destination:
            return f"#{name}"
        return f"#{skill_reference_name(name, row.skill_project)} · /{name}"

    @staticmethod
    def _short_path(path: str) -> str:
        return shorten_xprompt_location_path(path, str(Path.cwd()), str(Path.home()))

    def action_save(self) -> None:
        row = self._selected_row()
        if row is None or self._validation_error() is not None:
            self._refresh()
            return
        name = self._current_name()
        identity = self._identity()
        collision = self._collides(row, name)
        if collision and self._armed_identity != identity:
            self._armed_identity = identity
            self._armed_at = time.monotonic()
            self._preview_tab = "diff"
            self._refresh()
            return
        if collision and time.monotonic() - self._armed_at < 0.25:
            return
        frontmatter = self._prepared_frontmatter()
        storage_name = self._storage_name(row, name)
        target_format: SaveTargetFormat | None
        entry_name: str | None
        if self._mode == "snippet":
            target_format = None
            entry_name = name
        elif row.location.location_type == "directory":
            _, frontmatter = markdown_save_plan(storage_name, frontmatter)
            target_format = SaveTargetFormat.MARKDOWN
            entry_name = None
        else:
            target_format = SaveTargetFormat.CONFIG
            entry_name = storage_name
        path = self._target_path(row, name)
        self.dismiss(
            UnifiedXPromptSaveResult(
                mode=self._mode,
                name=name,
                path=path,
                location_path=row.location.path,
                target_format=target_format,
                entry_name=entry_name,
                display_path=self._short_path(path),
                exists=collision,
                frontmatter=frontmatter,
            )
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = [
    "UnifiedSaveLocation",
    "UnifiedXPromptSaveModal",
    "UnifiedXPromptSaveResult",
    "load_unified_save_locations",
    "load_unified_snippet_locations",
]
