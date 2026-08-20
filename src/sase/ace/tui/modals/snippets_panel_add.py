"""Add/edit form for the Snippets panel.

Validation is pure computation over the already-loaded catalog: trigger
shape and ``#[...]`` composition run on a short debounce, and submit is
refused while any blocking diagnostic stands. Destination cycling uses the
snapshot's preloaded YAML locations. Disk writes stay on the panel.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Input, Static, TextArea

from sase.ace.tui.snippets_panel_catalog import SnippetDestination
from sase.core.snippet_catalog_facade import (
    compose_snippet_catalog,
    validate_snippet_trigger,
)
from sase.snippet.models import SnippetCatalog

_VALIDATE_DELAY_S = 0.15
_PREVIEW_MAX_CHARS = 400
_FormMode = Literal["add", "edit"]


@dataclass(frozen=True, slots=True)
class SnippetFormDraft:
    """Validated values the panel writes through the shared mutation engine."""

    trigger: str
    template: str
    target: str | None
    expected_digest: str | None
    force: bool
    mode: _FormMode


@dataclass(frozen=True, slots=True)
class _SnippetFormPlan:
    """Live add/edit feedback computed without touching disk."""

    trigger_errors: tuple[str, ...] = ()
    template_errors: tuple[str, ...] = ()
    destination_errors: tuple[str, ...] = ()
    collision: str | None = None
    action: Literal["created", "replaced", "shadowed"] | None = None
    composed_preview: str = ""
    call_diagnostics: tuple[str, ...] = ()
    force: bool = False

    @property
    def blocking(self) -> bool:
        return bool(
            self.trigger_errors or self.template_errors or self.destination_errors
        )


def _plan_snippet_form(
    *,
    trigger: str,
    template: str,
    destination: SnippetDestination | None,
    catalog: SnippetCatalog | None,
    mode: _FormMode,
) -> _SnippetFormPlan:
    """Validate a candidate add/edit against local rules and the Rust catalog."""
    trigger_errors: list[str] = []
    template_errors: list[str] = []
    destination_errors: list[str] = []

    cleaned_trigger = trigger.strip()
    if not cleaned_trigger:
        trigger_errors.append("snippet trigger must be a nonblank string")
    elif "\n" in trigger or "\r" in trigger:
        trigger_errors.append("snippet trigger must be a single-line string")
    else:
        validation = validate_snippet_trigger(cleaned_trigger)
        if not validation.valid:
            reason = validation.reason or "invalid_characters"
            trigger_errors.append(
                f"snippet trigger {cleaned_trigger!r} is invalid ({reason})"
            )

    if not template.strip():
        template_errors.append("snippet template must be a nonblank string")

    if destination is not None and not destination.selectable:
        destination_errors.append(f"destination is not writable: {destination.label}")

    if trigger_errors or template_errors or destination_errors:
        return _SnippetFormPlan(
            trigger_errors=tuple(trigger_errors),
            template_errors=tuple(template_errors),
            destination_errors=tuple(destination_errors),
        )

    collision, action, force = _collision_plan(
        cleaned_trigger, destination, catalog, mode=mode
    )
    composed_preview = ""
    call_diagnostics: tuple[str, ...] = ()
    templates = dict(catalog.explicit_templates) if catalog is not None else {}
    templates[cleaned_trigger] = template
    try:
        composed = compose_snippet_catalog(templates)
    except Exception:
        composed = None
    if composed is not None:
        composed_preview = composed.templates.get(cleaned_trigger, "")
        if len(composed_preview) > _PREVIEW_MAX_CHARS:
            composed_preview = composed_preview[: _PREVIEW_MAX_CHARS - 1] + "…"
        call_diagnostics = tuple(
            f"{item.code}: {item.message}"
            for item in composed.diagnostics
            if item.trigger == cleaned_trigger
            and (item.code == "missing_target" or "cycle" in item.code)
        )
    return _SnippetFormPlan(
        collision=collision,
        action=action,
        composed_preview=composed_preview,
        call_diagnostics=call_diagnostics,
        force=force,
    )


def _collision_plan(
    trigger: str,
    destination: SnippetDestination | None,
    catalog: SnippetCatalog | None,
    *,
    mode: _FormMode,
) -> tuple[str | None, Literal["created", "replaced", "shadowed"] | None, bool]:
    if catalog is None:
        return None, "created", False
    existing = catalog.entry_for(trigger)
    if existing is None:
        source = catalog.alias_provenance.get(trigger)
        if source is not None:
            return (
                f"collides with generated alias of {source}; submit will shadow it",
                "shadowed",
                True,
            )
        return None, "created", False
    origin_path = existing.origin.path or ""
    dest_path = destination.path if destination is not None else ""
    winner = existing.origin.display_path or existing.origin.kind
    if dest_path and origin_path == dest_path:
        if mode == "edit":
            return None, "replaced", True
        return (
            f"already exists in {winner}; submit replaces that definition",
            "replaced",
            True,
        )
    return (
        f"already exists in {winner}; submit will shadow that definition",
        "shadowed",
        True,
    )


class SnippetFormModal(ModalScreen[SnippetFormDraft | None]):
    """Collect a trigger, template, and destination for a create or edit."""

    AUTO_FOCUS = None
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
        Binding("ctrl+s", "submit", "Submit", show=False, priority=True),
        Binding("tab", "focus_next", "Next field", show=False, priority=True),
        Binding(
            "shift+tab",
            "focus_previous",
            "Previous field",
            show=False,
            priority=True,
        ),
        Binding("ctrl+n", "next_destination", "Next destination", show=False),
        Binding("ctrl+p", "prev_destination", "Previous destination", show=False),
    ]

    def __init__(
        self,
        *,
        mode: _FormMode = "add",
        catalog: SnippetCatalog | None = None,
        destinations: Sequence[SnippetDestination] = (),
        default_destination_path: str | None = None,
        project_display_name: str = "",
        initial_trigger: str = "",
        initial_template: str = "",
        accent: str = "#87D7FF",
    ) -> None:
        super().__init__()
        self._mode: _FormMode = mode
        self._catalog = catalog
        selectable = tuple(item for item in destinations if item.selectable)
        self._destinations = selectable or tuple(destinations)
        self._destination_index = _index_for_path(
            self._destinations, default_destination_path
        )
        self._project_display_name = project_display_name
        self._initial_trigger = initial_trigger
        self._initial_template = initial_template
        self._accent = accent
        self._submitted = False
        self._validate_timer: Timer | None = None
        self._plan = _SnippetFormPlan()

    def compose(self) -> ComposeResult:
        with Container(id="snippets-form-container"):
            yield Static(self._title_text(), id="snippets-form-title")
            with Vertical(id="snippets-form-fields"):
                yield Static("Trigger", classes="snippets-form-label")
                yield Input(
                    value=self._initial_trigger,
                    placeholder="alphanumeric or underscore",
                    id="snippets-form-trigger",
                    disabled=self._mode == "edit",
                )
                yield Static(
                    "",
                    id="snippets-form-trigger-error",
                    classes="snippets-form-error",
                )
                yield Static("Template", classes="snippets-form-label")
                yield TextArea(self._initial_template, id="snippets-form-template")
                yield Static(
                    "",
                    id="snippets-form-template-error",
                    classes="snippets-form-error",
                )
                yield Static("Destination", classes="snippets-form-label")
                yield Static(self._destination_text(), id="snippets-form-destination")
                yield Static(
                    "",
                    id="snippets-form-collision",
                    classes="snippets-form-warning",
                )
                yield Static("", id="snippets-form-preview")
            yield Static(
                "ctrl+s submit  ·  tab field  ·  ctrl+n/p destination  ·  esc cancel",
                id="snippets-form-hints",
            )

    def on_mount(self) -> None:
        if self._mode == "edit":
            self.query_one("#snippets-form-template", TextArea).focus()
        else:
            self.query_one("#snippets-form-trigger", Input).focus()
        self._validate_now()

    def on_unmount(self) -> None:
        self._cancel_validate_timer()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self._submitted = True
        self._cancel_validate_timer()
        plan = self._validate_now()
        if plan.blocking:
            return
        trigger = self.query_one("#snippets-form-trigger", Input).value.strip()
        template = self.query_one("#snippets-form-template", TextArea).text
        destination = self._current_destination()
        self.dismiss(
            SnippetFormDraft(
                trigger=trigger,
                template=template,
                target=None if destination is None else destination.path,
                expected_digest=(None if destination is None else destination.digest),
                force=plan.force or self._mode == "edit",
                mode=self._mode,
            )
        )

    def action_next_destination(self) -> None:
        self._cycle_destination(1)

    def action_prev_destination(self) -> None:
        self._cycle_destination(-1)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "snippets-form-trigger":
            self._schedule_validate()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "snippets-form-trigger":
            self.focus_next()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "snippets-form-template":
            self._schedule_validate()

    def _cycle_destination(self, delta: int) -> None:
        if self._mode == "edit" or len(self._destinations) <= 1:
            return
        self._destination_index = (self._destination_index + delta) % len(
            self._destinations
        )
        self.query_one("#snippets-form-destination", Static).update(
            self._destination_text()
        )
        self._schedule_validate()

    def _current_destination(self) -> SnippetDestination | None:
        if not self._destinations:
            return None
        return self._destinations[self._destination_index]

    def _destination_text(self) -> str:
        destination = self._current_destination()
        if destination is None:
            return "(default snippet config path)"
        count = len(self._destinations)
        index = self._destination_index + 1
        return f"{destination.label}  ·  {destination.display_path}  ({index}/{count})"

    def _title_text(self) -> Text:
        title = "Edit snippet" if self._mode == "edit" else "Add snippet"
        text = Text()
        text.append(title, style=f"bold {self._accent}")
        if self._project_display_name:
            text.append("  ·  ", style="dim")
            text.append(self._project_display_name, style="bold")
        return text

    def _schedule_validate(self) -> None:
        self._cancel_validate_timer()
        self._validate_timer = self.set_timer(_VALIDATE_DELAY_S, self._validate_now)

    def _cancel_validate_timer(self) -> None:
        if self._validate_timer is not None:
            self._validate_timer.stop()
            self._validate_timer = None

    def _validate_now(self) -> _SnippetFormPlan:
        self._validate_timer = None
        if not self.is_mounted:
            return self._plan
        plan = _plan_snippet_form(
            trigger=self.query_one("#snippets-form-trigger", Input).value,
            template=self.query_one("#snippets-form-template", TextArea).text,
            destination=self._current_destination(),
            catalog=self._catalog,
            mode=self._mode,
        )
        self._plan = plan
        self._render_plan(self._visible_plan(plan))
        return plan

    def _visible_plan(self, plan: _SnippetFormPlan) -> _SnippetFormPlan:
        if self._submitted:
            return plan
        return _SnippetFormPlan(
            trigger_errors=_live_messages(plan.trigger_errors),
            template_errors=_live_messages(plan.template_errors),
            destination_errors=plan.destination_errors,
            collision=plan.collision,
            action=plan.action,
            composed_preview=plan.composed_preview,
            call_diagnostics=plan.call_diagnostics,
            force=plan.force,
        )

    def _render_plan(self, plan: _SnippetFormPlan) -> None:
        self.query_one("#snippets-form-trigger-error", Static).update(
            _error_text(plan.trigger_errors)
        )
        template_bits = (*plan.template_errors, *plan.call_diagnostics)
        self.query_one("#snippets-form-template-error", Static).update(
            _error_text(template_bits)
        )
        collision = plan.collision or _error_text(plan.destination_errors)
        self.query_one("#snippets-form-collision", Static).update(collision)
        preview = plan.composed_preview
        preview_widget = self.query_one("#snippets-form-preview", Static)
        if preview:
            text = Text()
            text.append("COMPOSED  ", style=f"bold {self._accent}")
            text.append(preview, style="dim")
            preview_widget.update(text)
        else:
            preview_widget.update("")


def _index_for_path(
    destinations: Sequence[SnippetDestination], path: str | None
) -> int:
    if path:
        for index, item in enumerate(destinations):
            if item.path == path:
                return index
    return 0


def _live_messages(messages: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(message for message in messages if "nonblank" not in message)


def _error_text(messages: tuple[str, ...]) -> str:
    return "\n".join(messages)


__all__ = [
    "SnippetFormDraft",
    "SnippetFormModal",
]
