"""Name panel for opening a pane-scoped mini-xprompt target."""

from __future__ import annotations

import asyncio
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

from .mini_xprompt_target_catalog import (
    MiniXPromptDefinition,
    MiniXPromptDestinationTarget,
    MiniXPromptTargetCatalog,
    default_mini_xprompt_destination,
    destination_target_for_name,
    mini_xprompt_prefix_matches,
    validate_name_for_destination,
)
from .unified_xprompt_save_support import UnifiedSaveLocation

MiniXPromptOpenAction = Literal["create", "edit", "fork", "override"]
MiniXPromptVerdictKind = Literal["success", "warning", "error"]


@dataclass(frozen=True, slots=True)
class MiniXPromptNameResult:
    """Chosen mini-xprompt target and destination metadata."""

    name: str
    action: MiniXPromptOpenAction
    destination: MiniXPromptDestinationTarget
    definition: MiniXPromptDefinition | None
    existing_definition: MiniXPromptDefinition | None
    save_warning: str | None = None


@dataclass(frozen=True, slots=True)
class _MiniXPromptNameVerdict:
    """One rendered verdict for the current name/destination identity."""

    kind: MiniXPromptVerdictKind
    message: str
    action: MiniXPromptOpenAction | None
    can_open: bool
    save_warning: str | None = None


@dataclass(frozen=True, slots=True)
class _MiniXPromptNameAnalysis:
    """Cached analysis keyed by typed name and destination path."""

    name: str
    destination: MiniXPromptDestinationTarget
    exact_definition: MiniXPromptDefinition | None
    destination_definition: MiniXPromptDefinition | None
    matches: tuple[MiniXPromptDefinition, ...]
    verdict: _MiniXPromptNameVerdict


class _MiniXPromptNameInput(Input):
    """Single-line name field whose navigation keys stay modal-scoped."""

    BINDINGS = [
        Binding("tab", "forward('complete_match')", show=False),
        Binding("up", "forward('prev_match')", show=False),
        Binding("down", "forward('next_match')", show=False),
        Binding("ctrl+n", "forward('next_destination')", show=False),
        Binding("ctrl+p", "forward('prev_destination')", show=False),
    ]

    def action_forward(self, action_name: str) -> None:
        action = getattr(self.screen, f"action_{action_name}", None)
        if callable(action):
            action()


class _MiniXPromptMatchList(OptionList):
    """Read-only match list with completion and navigation forwarding."""

    BINDINGS = [
        Binding("tab", "forward('complete_match')", show=False),
        Binding("up", "forward('prev_match')", show=False),
        Binding("down", "forward('next_match')", show=False),
        Binding("ctrl+n", "forward('next_destination')", show=False),
        Binding("ctrl+p", "forward('prev_destination')", show=False),
    ]

    def action_forward(self, action_name: str) -> None:
        action = getattr(self.screen, f"action_{action_name}", None)
        if callable(action):
            action()


class MiniXPromptNameModal(ModalScreen[MiniXPromptNameResult | None]):
    """Ask for a mini-xprompt name and report target resolution live."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "open", "Open", show=False),
        Binding("tab", "complete_match", "Complete", show=False),
        Binding("up", "prev_match", "Previous match", show=False),
        Binding("down", "next_match", "Next match", show=False),
        Binding("ctrl+n", "next_destination", "Next destination", show=False),
        Binding("ctrl+p", "prev_destination", "Previous destination", show=False),
    ]

    def __init__(
        self,
        catalog: MiniXPromptTargetCatalog,
        *,
        initial_name: str = "",
        last_used_path: str | None = None,
    ) -> None:
        super().__init__()
        self._catalog = catalog
        self._initial_name = initial_name
        self._destination = default_mini_xprompt_destination(
            catalog,
            name=initial_name,
            last_used_path=last_used_path,
        )
        self._updating_matches = False
        self._analysis_debouncer: DetailPanelDebouncer | None = None
        self._analysis_tasks: set[asyncio.Task[None]] = set()
        self._pending_analyses: set[tuple[str, str]] = set()
        self._analysis_cache: dict[tuple[str, str], _MiniXPromptNameAnalysis] = {}

    def compose(self) -> ComposeResult:
        with Container(id="mini-xprompt-name-container"):
            yield Label("Open mini-xprompt", id="mini-xprompt-name-title")
            with Horizontal(classes="mini-xprompt-name-field"):
                yield Label("Name", classes="mini-xprompt-name-field-label")
                yield _MiniXPromptNameInput(
                    value=self._initial_name,
                    placeholder="review",
                    id="mini-xprompt-name-input",
                )
            with Horizontal(id="mini-xprompt-name-body"):
                with Vertical(id="mini-xprompt-name-matches-panel"):
                    yield Static("Matches", classes="mini-xprompt-name-panel-title")
                    yield _MiniXPromptMatchList(id="mini-xprompt-name-matches")
                with Vertical(id="mini-xprompt-name-destination-panel"):
                    yield Static(
                        "Destination",
                        classes="mini-xprompt-name-panel-title",
                    )
                    yield Static(
                        "",
                        id="mini-xprompt-name-destination",
                        markup=False,
                    )
            yield Static("", id="mini-xprompt-name-verdict", markup=False)
            yield Static(
                "tab complete · up/down matches · ^n/^p destination · enter open · esc cancel",
                id="mini-xprompt-name-hints",
                markup=False,
            )

    def on_mount(self) -> None:
        self._analysis_debouncer = DetailPanelDebouncer(self.app)
        field = self.query_one("#mini-xprompt-name-input", _MiniXPromptNameInput)
        field.focus()
        field.cursor_position = len(field.value)
        self._refresh()

    def on_unmount(self) -> None:
        if self._analysis_debouncer is not None:
            self._analysis_debouncer.cancel()
        for task in self._analysis_tasks:
            task.cancel()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "mini-xprompt-name-input":
            self._refresh()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "mini-xprompt-name-input":
            await self.action_open()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if (
            event.option_list.id == "mini-xprompt-name-matches"
            and not self._updating_matches
        ):
            self.query_one("#mini-xprompt-name-input", _MiniXPromptNameInput).focus()

    def _current_name(self) -> str:
        return self.query_one(
            "#mini-xprompt-name-input", _MiniXPromptNameInput
        ).value.strip()

    def _identity(self) -> tuple[str, str] | None:
        name = self._current_name()
        if self._destination is None:
            return None
        if validate_name_for_destination(name, self._destination) is not None:
            return None
        return (name, self._destination.location.path)

    def _refresh(self) -> None:
        self._refresh_destination()
        self._refresh_matches()
        self._refresh_verdict()
        identity = self._identity()
        if identity is not None and identity not in self._analysis_cache:
            self._schedule_analysis(identity)

    def _refresh_destination(self) -> None:
        target = self.query_one("#mini-xprompt-name-destination", Static)
        if self._destination is None:
            target.update("No writable xprompt destinations found")
            return
        name = self._current_name()
        details = [self._destination.display_path]
        if name and validate_name_for_destination(name, self._destination) is None:
            destination = destination_target_for_name(
                self._destination,
                name,
                destinations=self._catalog.destinations,
            )
            details.append(destination.display_path)
        if self._destination.namespace:
            details.append(f"namespace {self._destination.namespace}/")
        target.update(" · ".join(details))

    def _refresh_matches(self) -> None:
        option_list = self.query_one(
            "#mini-xprompt-name-matches",
            _MiniXPromptMatchList,
        )
        selected_name = self._highlighted_match_name()
        matches = mini_xprompt_prefix_matches(self._current_name(), self._catalog)
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
        verdict = self.query_one("#mini-xprompt-name-verdict", Static)
        name = self._current_name()
        error = validate_name_for_destination(name, self._destination)
        if self._destination is None:
            verdict.set_classes("mini-xprompt-name-verdict-error")
            verdict.update("Invalid target: no writable xprompt destinations found")
            return
        if error is not None:
            verdict.set_classes("mini-xprompt-name-verdict-error")
            verdict.update(f"Invalid name: {error}")
            return
        identity = self._identity()
        analysis = self._analysis_cache.get(identity) if identity is not None else None
        if analysis is None:
            verdict.set_classes("mini-xprompt-name-verdict-warning")
            verdict.update(f"Checking #{name} in {self._destination.display_path}...")
            return
        verdict.set_classes(f"mini-xprompt-name-verdict-{analysis.verdict.kind}")
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
            if destination is None or destination.location.path != destination_path:
                return
            analysis = await asyncio.to_thread(
                _build_mini_xprompt_name_analysis,
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
        if self._destination is None:
            self._refresh()
            return
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
                _build_mini_xprompt_name_analysis,
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
            MiniXPromptNameResult(
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
        field = self.query_one("#mini-xprompt-name-input", _MiniXPromptNameInput)
        field.value = match.name
        field.cursor_position = len(field.value)
        field.focus()
        self._destination = default_mini_xprompt_destination(
            self._catalog,
            name=match.name,
            last_used_path=(
                self._destination.location.path
                if self._destination is not None
                else None
            ),
        )
        self._refresh()

    def action_next_match(self) -> None:
        self._move_match(1)

    def action_prev_match(self) -> None:
        self._move_match(-1)

    def action_next_destination(self) -> None:
        self._move_destination(1)

    def action_prev_destination(self) -> None:
        self._move_destination(-1)

    def _move_match(self, direction: int) -> None:
        option_list = self.query_one(
            "#mini-xprompt-name-matches",
            _MiniXPromptMatchList,
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
        self.query_one("#mini-xprompt-name-input", _MiniXPromptNameInput).focus()

    def _move_destination(self, direction: int) -> None:
        choices = [row for row in self._catalog.destinations if row.is_selectable]
        if not choices:
            return
        if self._destination is None:
            self._destination = choices[0 if direction > 0 else -1]
            self._refresh()
            return
        try:
            current = next(
                index
                for index, row in enumerate(choices)
                if row.location.path == self._destination.location.path
            )
        except StopIteration:
            current = -1 if direction > 0 else 0
        self._destination = choices[(current + direction) % len(choices)]
        self._refresh()
        self.query_one("#mini-xprompt-name-input", _MiniXPromptNameInput).focus()

    def _highlighted_match(self) -> MiniXPromptDefinition | None:
        matches = mini_xprompt_prefix_matches(self._current_name(), self._catalog)
        if not matches:
            return None
        option_list = self.query_one(
            "#mini-xprompt-name-matches",
            _MiniXPromptMatchList,
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
    def _match_label(definition: MiniXPromptDefinition) -> Text:
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


def _build_mini_xprompt_name_analysis(
    catalog: MiniXPromptTargetCatalog,
    name: str,
    destination: UnifiedSaveLocation,
) -> _MiniXPromptNameAnalysis:
    """Return the cached target-resolution analysis for one identity."""

    destination_target = destination_target_for_name(
        destination,
        name,
        destinations=catalog.destinations,
    )
    definitions = catalog.definitions_for_name(name)
    exact = definitions[0] if definitions else None
    destination_definition = next(
        (
            definition
            for definition in definitions
            if definition.location_path == destination.location.path
        ),
        None,
    )
    matches = mini_xprompt_prefix_matches(name, catalog)
    verdict = _build_mini_xprompt_verdict(
        name,
        destination_target,
        exact_definition=exact,
        destination_definition=destination_definition,
    )
    return _MiniXPromptNameAnalysis(
        name=name,
        destination=destination_target,
        exact_definition=exact,
        destination_definition=destination_definition,
        matches=matches,
        verdict=verdict,
    )


def _build_mini_xprompt_verdict(
    name: str,
    destination: MiniXPromptDestinationTarget,
    *,
    exact_definition: MiniXPromptDefinition | None,
    destination_definition: MiniXPromptDefinition | None,
) -> _MiniXPromptNameVerdict:
    """Return the exact Enter behavior for one mini-name analysis."""

    reference = f"#{name}"
    if exact_definition is not None and not exact_definition.is_compatible:
        reason = exact_definition.incompatible_reason or "not a simple xprompt"
        return _MiniXPromptNameVerdict(
            kind="error",
            message=f"Cannot open {reference}: {reason}",
            action=None,
            can_open=False,
        )
    if destination_definition is not None and destination_definition.is_editable:
        return _MiniXPromptNameVerdict(
            kind="success",
            message=f"Edit {reference} at {destination_definition.display_path}",
            action="edit",
            can_open=True,
        )
    if exact_definition is not None and exact_definition.compatibility == "read_only":
        message = (
            f"Override read-only {reference} from "
            f"{exact_definition.display_path} in {destination.display_path}"
        )
        return _MiniXPromptNameVerdict(
            kind="warning",
            message=message,
            action="override",
            can_open=True,
            save_warning=message,
        )
    if exact_definition is not None:
        message = f"Fork {reference} from {exact_definition.display_path} into {destination.display_path}"
        return _MiniXPromptNameVerdict(
            kind="warning",
            message=message,
            action="fork",
            can_open=True,
            save_warning=message,
        )
    message = f"Create {reference} at {destination.display_path}"
    if destination.resolution.shadowed_by:
        message += f" (will be shadowed by {destination.resolution.shadowed_by})"
        return _MiniXPromptNameVerdict(
            kind="warning",
            message=message,
            action="create",
            can_open=True,
            save_warning=message,
        )
    if destination.resolution.shadows:
        message += f" (shadows {destination.resolution.shadows})"
    return _MiniXPromptNameVerdict(
        kind="success",
        message=message,
        action="create",
        can_open=True,
    )


def _definition_status_label(definition: MiniXPromptDefinition) -> str:
    if definition.compatibility == "editable":
        return "editable" if definition.effective else "shadowed"
    if definition.compatibility == "read_only":
        return "read-only"
    return "incompatible"


def _definition_status_style(definition: MiniXPromptDefinition) -> str:
    if definition.compatibility == "editable" and definition.effective:
        return "green"
    if definition.compatibility == "incompatible":
        return "red"
    return "yellow"


__all__ = [
    "MiniXPromptNameModal",
    "MiniXPromptNameResult",
    "MiniXPromptOpenAction",
]
