"""Name panel for opening a pane-scoped mini-macro target."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer

from .mini_macro_target_catalog import (
    MiniMacroDefinition,
    MiniMacroDestinationTarget,
    MiniMacroTargetCatalog,
    mini_macro_prefix_matches,
    validate_name_for_destination,
)
from .mini_macro_redefinition import (
    MacroRedefinition,
    macro_redefinition,
    macro_redefinition_warning,
)
from .save_location_choices import ChangeSaveLocationRequest
from .unified_macro_save_support import UnifiedSaveLocation

MiniMacroOpenAction = Literal["create", "edit", "fork", "override"]
MiniMacroVerdictKind = Literal["success", "warning", "error"]


@dataclass(frozen=True, slots=True)
class MiniMacroNameResult:
    """Chosen mini-macro target and destination metadata."""

    name: str
    action: MiniMacroOpenAction
    destination: MiniMacroDestinationTarget
    definition: MiniMacroDefinition | None
    existing_definition: MiniMacroDefinition | None
    save_warning: str | None = None


@dataclass(frozen=True, slots=True)
class _MiniMacroNameVerdict:
    """One rendered verdict for the current name/destination identity."""

    kind: MiniMacroVerdictKind
    message: str
    action: MiniMacroOpenAction | None
    can_open: bool
    save_warning: str | None = None


@dataclass(frozen=True, slots=True)
class _MiniMacroNameAnalysis:
    """Cached analysis keyed by typed name and destination path."""

    name: str
    destination: MiniMacroDestinationTarget
    exact_definition: MiniMacroDefinition | None
    destination_definition: MiniMacroDefinition | None
    matches: tuple[MiniMacroDefinition, ...]
    verdict: _MiniMacroNameVerdict


class _MiniMacroNameInput(Input):
    """Single-line name field whose navigation keys stay modal-scoped."""

    BINDINGS = [
        Binding("tab", "forward('complete_match')", show=False),
        Binding("shift+tab", "forward('change_location')", show=False),
        Binding("up", "forward('prev_match')", show=False),
        Binding("down", "forward('next_match')", show=False),
        Binding("ctrl+n", "forward('next_match')", show=False),
        Binding("ctrl+p", "forward('prev_match')", show=False),
    ]

    def action_forward(self, action_name: str) -> None:
        action = getattr(self.screen, f"action_{action_name}", None)
        if callable(action):
            action()


class _MiniMacroMatchList(OptionList):
    """Read-only match list with completion and navigation forwarding."""

    BINDINGS = [
        Binding("tab", "forward('complete_match')", show=False),
        Binding("shift+tab", "forward('change_location')", show=False),
        Binding("up", "forward('prev_match')", show=False),
        Binding("down", "forward('next_match')", show=False),
        Binding("ctrl+n", "forward('next_match')", show=False),
        Binding("ctrl+p", "forward('prev_match')", show=False),
    ]

    def action_forward(self, action_name: str) -> None:
        action = getattr(self.screen, f"action_{action_name}", None)
        if callable(action):
            action()


class MiniMacroNameModal(
    ModalScreen[MiniMacroNameResult | ChangeSaveLocationRequest | None]
):
    """Ask for a mini-macro name at a locked destination.

    The destination is chosen by the location picker before this step; this
    modal never changes it. ``Shift+Tab`` asks the orchestrator to reopen the
    picker while keeping the typed text.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "open", "Open", show=False),
        Binding("tab", "complete_match", "Complete", show=False),
        Binding("shift+tab", "change_location", "Change location", show=False),
        Binding("up", "prev_match", "Previous match", show=False),
        Binding("down", "next_match", "Next match", show=False),
        Binding("ctrl+n", "next_match", "Next match", show=False),
        Binding("ctrl+p", "prev_match", "Previous match", show=False),
    ]

    def __init__(
        self,
        catalog: MiniMacroTargetCatalog,
        destination: UnifiedSaveLocation,
        *,
        initial_name: str = "",
    ) -> None:
        super().__init__()
        self._catalog = catalog
        self._initial_name = initial_name
        self._destination = destination
        self._updating_matches = False
        self._analysis_debouncer: DetailPanelDebouncer | None = None
        self._analysis_tasks: set[asyncio.Task[None]] = set()
        self._pending_analyses: set[tuple[str, str]] = set()
        self._analysis_cache: dict[tuple[str, str], _MiniMacroNameAnalysis] = {}

    def compose(self) -> ComposeResult:
        with Container(id="mini-macro-name-container"):
            yield Label(
                f"✓ {self._destination.location.label} › ● Name",
                id="mini-macro-name-title",
            )
            with Horizontal(classes="mini-macro-name-field"):
                yield Label("Name", classes="mini-macro-name-field-label")
                yield _MiniMacroNameInput(
                    value=self._initial_name,
                    placeholder="review",
                    id="mini-macro-name-input",
                )
            with Horizontal(id="mini-macro-name-body"):
                with Vertical(id="mini-macro-name-matches-panel"):
                    yield Static("Matches", classes="mini-macro-name-panel-title")
                    yield _MiniMacroMatchList(id="mini-macro-name-matches")
                with Vertical(id="mini-macro-name-destination-panel"):
                    yield Static(
                        "Saving to",
                        classes="mini-macro-name-panel-title",
                    )
                    yield Static(
                        "",
                        id="mini-macro-name-destination",
                        markup=False,
                    )
            yield Static("", id="mini-macro-name-verdict", markup=False)
            yield Static(
                "tab complete · ↑↓ matches · ⇧tab location · enter open · esc cancel",
                id="mini-macro-name-hints",
                markup=False,
            )

    def on_mount(self) -> None:
        self._analysis_debouncer = DetailPanelDebouncer(self.app)
        field = self.query_one("#mini-macro-name-input", _MiniMacroNameInput)
        field.focus()
        field.cursor_position = len(field.value)
        self._refresh()

    def on_unmount(self) -> None:
        if self._analysis_debouncer is not None:
            self._analysis_debouncer.cancel()
        for task in self._analysis_tasks:
            task.cancel()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "mini-macro-name-input":
            self._refresh()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "mini-macro-name-input":
            await self.action_open()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if (
            event.option_list.id == "mini-macro-name-matches"
            and not self._updating_matches
        ):
            self.query_one("#mini-macro-name-input", _MiniMacroNameInput).focus()

    def _current_name(self) -> str:
        return self.query_one(
            "#mini-macro-name-input", _MiniMacroNameInput
        ).value.strip()

    def _identity(self) -> tuple[str, str] | None:
        name = self._current_name()
        if validate_name_for_destination(name, self._destination) is not None:
            return None
        return (name, self._destination.location.path)

    def _refresh(self) -> None:
        self._refresh_saving_to()
        self._refresh_matches()
        self._refresh_verdict()
        identity = self._identity()
        if identity is not None and identity not in self._analysis_cache:
            self._schedule_analysis(identity)

    def _refresh_saving_to(self) -> None:
        target = self.query_one("#mini-macro-name-destination", Static)
        name = self._current_name()
        lines = []
        if name and validate_name_for_destination(name, self._destination) is None:
            destination = macro_redefinition(
                self._catalog,
                name,
                self._destination,
            ).destination
            lines.append(f"→ {destination.display_path}")
            notes = []
            if self._destination.namespace:
                notes.append(f"namespace {self._destination.namespace}/")
            if destination.via_chezmoi:
                notes.append("via chezmoi")
            if notes:
                lines.append(" · ".join(notes))
        else:
            lines.append(f"→ {self._destination.display_path}")
            if self._destination.namespace:
                lines.append(f"namespace {self._destination.namespace}/")
        lines.append("⇧Tab change location")
        target.update("\n".join(lines))

    def _refresh_matches(self) -> None:
        option_list = self.query_one(
            "#mini-macro-name-matches",
            _MiniMacroMatchList,
        )
        selected_name = self._highlighted_match_name()
        matches = mini_macro_prefix_matches(self._current_name(), self._catalog)
        self._updating_matches = True
        try:
            option_list.clear_options()
            if not matches:
                option_list.add_option(
                    Option(Text("  No prefix matches", style="dim"), disabled=True)
                )
                option_list.highlighted = None
                return
            highlighted = 0
            for index, definition in enumerate(matches):
                if definition.name == selected_name:
                    highlighted = index
                option_list.add_option(
                    Option(self._match_label(definition), id=f"match-{index}")
                )
            option_list.highlighted = highlighted
        finally:
            self._updating_matches = False

    def _refresh_verdict(self) -> None:
        verdict = self.query_one("#mini-macro-name-verdict", Static)
        name = self._current_name()
        error = validate_name_for_destination(name, self._destination)
        if error is not None:
            verdict.set_classes("mini-macro-name-verdict-error")
            verdict.update(f"Invalid name: {error}")
            return
        identity = self._identity()
        analysis = self._analysis_cache.get(identity) if identity is not None else None
        if analysis is None:
            verdict.set_classes("mini-macro-name-verdict-warning")
            verdict.update(f"Checking #{name} in {self._destination.display_path}...")
            return
        verdict.set_classes(f"mini-macro-name-verdict-{analysis.verdict.kind}")
        verdict.update(analysis.verdict.message)

    def _schedule_analysis(self, identity: tuple[str, str]) -> None:
        if identity in self._pending_analyses or self._analysis_debouncer is None:
            return
        self._pending_analyses.add(identity)

        def start() -> None:
            if self._identity() != identity:
                self._pending_analyses.discard(identity)
                return
            task = asyncio.create_task(self._load_analysis(identity))
            self._analysis_tasks.add(task)
            task.add_done_callback(self._analysis_tasks.discard)

        self._analysis_debouncer.schedule(start)

    async def _load_analysis(self, identity: tuple[str, str]) -> None:
        name, destination_path = identity
        destination = self._destination
        try:
            if destination.location.path != destination_path:
                return
            analysis = await asyncio.to_thread(
                _build_mini_macro_name_analysis,
                self._catalog,
                name,
                destination,
            )
        finally:
            self._pending_analyses.discard(identity)
        if self.is_mounted and self._identity() == identity:
            self._analysis_cache[identity] = analysis
            self._refresh()

    async def action_open(self) -> None:
        name = self._current_name()
        if validate_name_for_destination(name, self._destination) is not None:
            self._refresh()
            return
        identity = self._identity()
        if identity is None:
            self._refresh()
            return
        analysis = self._analysis_cache.get(identity)
        if analysis is None:
            analysis = await asyncio.to_thread(
                _build_mini_macro_name_analysis,
                self._catalog,
                name,
                self._destination,
            )
            if self._identity() != identity:
                self._refresh()
                return
            self._analysis_cache[identity] = analysis
        if not analysis.verdict.can_open or analysis.verdict.action is None:
            self._refresh()
            return
        self.dismiss(
            MiniMacroNameResult(
                name=name,
                action=analysis.verdict.action,
                destination=analysis.destination,
                definition=analysis.destination_definition,
                existing_definition=analysis.exact_definition,
                save_warning=analysis.verdict.save_warning,
            )
        )

    def action_complete_match(self) -> None:
        match = self._highlighted_match()
        if match is None:
            return
        field = self.query_one("#mini-macro-name-input", _MiniMacroNameInput)
        field.value = match.name
        field.cursor_position = len(field.value)
        field.focus()
        self._refresh()

    def action_change_location(self) -> None:
        field = self.query_one("#mini-macro-name-input", _MiniMacroNameInput)
        self.dismiss(ChangeSaveLocationRequest(text=field.value))

    def action_next_match(self) -> None:
        self._move_match(1)

    def action_prev_match(self) -> None:
        self._move_match(-1)

    def _move_match(self, direction: int) -> None:
        option_list = self.query_one(
            "#mini-macro-name-matches",
            _MiniMacroMatchList,
        )
        selectable = [
            index
            for index in range(option_list.option_count)
            if not getattr(option_list.get_option_at_index(index), "disabled", False)
        ]
        if not selectable:
            return
        current = option_list.highlighted
        if current not in selectable:
            selected = selectable[0 if direction > 0 else -1]
        else:
            index = selectable.index(current)
            selected = selectable[(index + direction) % len(selectable)]
        self._updating_matches = True
        try:
            option_list.highlighted = selected
        finally:
            self._updating_matches = False
        self.query_one("#mini-macro-name-input", _MiniMacroNameInput).focus()

    def _highlighted_match(self) -> MiniMacroDefinition | None:
        matches = mini_macro_prefix_matches(self._current_name(), self._catalog)
        if not matches:
            return None
        option_list = self.query_one(
            "#mini-macro-name-matches",
            _MiniMacroMatchList,
        )
        highlighted = option_list.highlighted
        if highlighted is None:
            return matches[0]
        option = option_list.get_option_at_index(highlighted)
        if not option.id or not str(option.id).startswith("match-"):
            return matches[0]
        try:
            index = int(str(option.id).removeprefix("match-"))
        except ValueError:
            return None
        return matches[index] if 0 <= index < len(matches) else None

    def _highlighted_match_name(self) -> str | None:
        match = self._highlighted_match()
        return match.name if match is not None else None

    @staticmethod
    def _match_label(definition: MiniMacroDefinition) -> Text:
        text = Text()
        text.append(f"  #{definition.name}", style="bold")
        status = _definition_status_label(definition)
        if status:
            text.append(f"  {status}", style=_definition_status_style(definition))
        text.append(f"  {definition.workflow_kind}", style="dim")
        text.append(f"\n     {definition.display_path}", style="dim")
        if definition.shadows:
            text.append(f"  shadows {definition.shadows}", style="italic dim")
        if definition.shadowed_by:
            text.append(f"  shadowed by {definition.shadowed_by}", style="italic dim")
        return text

    def action_cancel(self) -> None:
        self.dismiss(None)


def _build_mini_macro_name_analysis(
    catalog: MiniMacroTargetCatalog,
    name: str,
    destination: UnifiedSaveLocation,
) -> _MiniMacroNameAnalysis:
    """Return the cached target-resolution analysis for one identity."""

    redefinition = macro_redefinition(catalog, name, destination)
    destination_target = redefinition.destination
    exact = redefinition.active
    destination_definition = redefinition.destination_definition
    matches = mini_macro_prefix_matches(name, catalog)
    verdict = _build_mini_macro_verdict(
        name,
        redefinition,
        destinations=catalog.destinations,
    )
    return _MiniMacroNameAnalysis(
        name=name,
        destination=destination_target,
        exact_definition=exact,
        destination_definition=destination_definition,
        matches=matches,
        verdict=verdict,
    )


def _build_mini_macro_verdict(
    name: str,
    redefinition: MacroRedefinition,
    *,
    destinations: Sequence[UnifiedSaveLocation] = (),
) -> _MiniMacroNameVerdict:
    """Return the exact Enter behavior for one mini-name analysis."""

    reference = f"#{name}"
    destination = redefinition.destination
    exact_definition = redefinition.active
    destination_definition = redefinition.destination_definition
    if destination_definition is not None and not destination_definition.is_compatible:
        reason = destination_definition.incompatible_reason or "not a simple macro"
        return _MiniMacroNameVerdict(
            kind="error",
            message=(
                f"Cannot open {reference} at "
                f"{destination_definition.display_path}: {reason}"
            ),
            action=None,
            can_open=False,
        )
    if exact_definition is not None and not exact_definition.is_compatible:
        reason = exact_definition.incompatible_reason or "not a simple macro"
        return _MiniMacroNameVerdict(
            kind="error",
            message=f"Cannot open {reference}: {reason}",
            action=None,
            can_open=False,
        )
    if destination_definition is not None and destination_definition.is_editable:
        warning = macro_redefinition_warning(redefinition)
        if warning is not None:
            return _MiniMacroNameVerdict(
                kind="warning",
                message=warning,
                action="edit",
                can_open=True,
                save_warning=warning,
            )
        return _MiniMacroNameVerdict(
            kind="success",
            message=(
                f"✓ Edit {reference} in place · {destination_definition.display_path}"
            ),
            action="edit",
            can_open=True,
        )
    if exact_definition is not None and exact_definition.compatibility == "read_only":
        message = macro_redefinition_warning(redefinition) or (
            f"⚠ {reference} is {exact_definition.origin_label or exact_definition.display_path} "
            "(read-only) — Enter picks where your override should live"
        )
        return _MiniMacroNameVerdict(
            kind="warning",
            message=message,
            action="override",
            can_open=True,
            save_warning=message,
        )
    if exact_definition is not None:
        message = macro_redefinition_warning(redefinition) or (
            f"⚠ {reference} already exists in {exact_definition.display_path} — "
            f"saving to {destination.display_path} adds another definition"
        )
        if (
            exact_definition.location_path
            and exact_definition.location_path != destination.location_path
            and exact_definition.is_editable
        ):
            other = next(
                (
                    row
                    for row in destinations
                    if row.location.path == exact_definition.location_path
                    and row.location.path != destination.location_path
                ),
                None,
            )
            if other is not None:
                message += f" · ⇧tab to edit it in {other.location.label} instead"
        return _MiniMacroNameVerdict(
            kind="warning",
            message=message,
            action="fork",
            can_open=True,
            save_warning=message,
        )
    warning = macro_redefinition_warning(redefinition)
    if warning is not None:
        return _MiniMacroNameVerdict(
            kind="warning",
            message=warning,
            action="create",
            can_open=True,
            save_warning=warning,
        )
    return _MiniMacroNameVerdict(
        kind="success",
        message=f"✓ Create {reference} at {destination.display_path}",
        action="create",
        can_open=True,
    )


def _definition_status_label(definition: MiniMacroDefinition) -> str:
    if definition.compatibility == "editable":
        return "editable" if definition.effective else "shadowed"
    if definition.compatibility == "read_only":
        return "read-only"
    return "incompatible"


def _definition_status_style(definition: MiniMacroDefinition) -> str:
    if definition.compatibility == "editable" and definition.effective:
        return "green"
    if definition.compatibility == "incompatible":
        return "red"
    return "yellow"


__all__ = [
    "MiniMacroNameModal",
    "MiniMacroNameResult",
    "MiniMacroOpenAction",
]
