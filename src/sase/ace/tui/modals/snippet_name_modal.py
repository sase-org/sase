"""Trigger-name panel for opening a snippet target pane."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.modals.save_location_choices import ChangeSaveLocationRequest
from sase.ace.tui.modals.snippet_name_analysis import (
    SnippetMatchPreview,
    SnippetNameAnalysis,
    build_snippet_name_analysis,
    derived_from_for,
    existing_body_for,
)
from sase.macro.naming import validate_snippet_trigger
from sase.macro.snippet_targets import SnippetConfigLocation, SnippetSaveTarget
from sase.snippet.catalog import empty_snippet_catalog
from sase.snippet.models import SnippetCatalog


@dataclass(frozen=True, slots=True)
class SnippetNameResult:
    """Trigger and starting body chosen by the snippet-name panel."""

    trigger: str
    target: SnippetSaveTarget
    exists: bool
    existing_body: str | None
    derived_from: str | None
    save_warning: str | None = None


class _SnippetNameInput(Input):
    """Single-line trigger field whose navigation keys stay modal-scoped."""

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


class _SnippetMatchList(OptionList):
    """Read-only match list with Tab completion forwarded to the screen."""

    BINDINGS = [
        Binding("tab", "forward('complete_match')", show=False),
        Binding("shift+tab", "forward('change_location')", show=False),
        Binding("up", "forward('prev_match')", show=False),
        Binding("down", "forward('next_match')", show=False),
    ]

    def action_forward(self, action_name: str) -> None:
        action = getattr(self.screen, f"action_{action_name}", None)
        if callable(action):
            action()


class SnippetNameModal(
    ModalScreen[SnippetNameResult | ChangeSaveLocationRequest | None]
):
    """Ask for a snippet trigger and report collisions live.

    The destination is locked by the location picker that pushed this modal:
    ``↑``/``↓``/``Ctrl+N``/``Ctrl+P`` move the match highlight and ``⇧Tab``
    asks the orchestrator to reopen the picker. Analysis reads the loaded
    snippet catalog in memory; it never opens files on the event loop.
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
        target: SnippetSaveTarget,
        locations: Sequence[SnippetConfigLocation],
        *,
        catalog: SnippetCatalog | None = None,
        initial_trigger: str = "",
    ) -> None:
        super().__init__()
        self._initial_target = target
        self._target = target
        self._locations = list(locations)
        self._catalog = catalog if catalog is not None else empty_snippet_catalog()
        self._initial_trigger = initial_trigger
        self._updating_matches = False
        self._analysis_cache: dict[tuple[str, str], SnippetNameAnalysis] = {}

    def compose(self) -> ComposeResult:
        with Container(id="snippet-name-container"):
            yield Label(
                f"✓ {self._location_label()} › ● Name",
                id="snippet-name-title",
            )
            with Horizontal(classes="snippet-name-field"):
                yield Label("Trigger", classes="snippet-name-field-label")
                yield _SnippetNameInput(
                    value=self._initial_trigger,
                    placeholder="todo",
                    id="snippet-name-trigger",
                )
            with Horizontal(id="snippet-name-body"):
                with Vertical(id="snippet-name-matches-panel"):
                    yield Static("Matches", classes="snippet-name-panel-title")
                    yield _SnippetMatchList(id="snippet-name-matches")
                with Vertical(id="snippet-name-destination-panel"):
                    yield Static("Saving to", classes="snippet-name-panel-title")
                    yield Static("", id="snippet-name-destination", markup=False)
                    yield Static(
                        "⇧tab change location",
                        classes="snippet-name-change-hint",
                        markup=False,
                    )
            yield Static("", id="snippet-name-verdict", markup=False)
            yield Static(
                "tab complete · ↑↓ matches · ⇧tab location · enter open · esc cancel",
                id="snippet-name-hints",
                markup=False,
            )

    def on_mount(self) -> None:
        field = self.query_one("#snippet-name-trigger", _SnippetNameInput)
        field.focus()
        field.cursor_position = len(field.value)
        self._refresh()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "snippet-name-trigger":
            self._refresh()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "snippet-name-trigger":
            await self.action_open()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if (
            event.option_list.id == "snippet-name-matches"
            and not self._updating_matches
        ):
            self._refresh_matches()

    def _current_trigger(self) -> str:
        return self.query_one("#snippet-name-trigger", _SnippetNameInput).value.strip()

    def _identity(self) -> tuple[str, str] | None:
        trigger = self._current_trigger()
        if validate_snippet_trigger(trigger) is not None:
            return None
        return (trigger, str(self._target.write_path))

    def _analysis(self) -> SnippetNameAnalysis | None:
        identity = self._identity()
        if identity is None:
            return None
        cached = self._analysis_cache.get(identity)
        if cached is not None:
            return cached
        analysis = build_snippet_name_analysis(
            identity[0],
            self._target,
            tuple(self._locations),
            self._catalog,
        )
        self._analysis_cache[identity] = analysis
        return analysis

    def _refresh(self) -> None:
        self._refresh_destination()
        self._refresh_matches()
        self._refresh_verdict()

    def _location_label(self) -> str:
        """Return the picker label for the locked destination."""
        wanted = {str(self._target.write_path), str(self._target.read_path)}
        for location in self._locations:
            if location.path in wanted:
                return location.label
        return "Configured snippet config"

    def _refresh_destination(self) -> None:
        line = self.query_one("#snippet-name-destination", Static)
        message = self._target.display_path
        if self._target.via_chezmoi:
            message += " · chezmoi-managed"
        if self._target.fallback_reason:
            message += f" · configured path unusable: {self._target.fallback_reason}"
        disabled = self._destination_disabled_reason()
        if disabled is not None:
            message += f" · {disabled}"
        line.update(message)

    def _refresh_matches(self) -> None:
        option_list = self.query_one("#snippet-name-matches", _SnippetMatchList)
        analysis = self._analysis()
        selected_trigger = self._highlighted_match_trigger()
        self._updating_matches = True
        try:
            option_list.clear_options()
            if self._current_trigger() and analysis is None:
                option_list.add_option(
                    Option(Text("  No prefix matches", style="dim"), disabled=True)
                )
                option_list.highlighted = None
                return
            matches = analysis.matches if analysis is not None else ()
            if not matches:
                option_list.add_option(
                    Option(Text("  No prefix matches", style="dim"), disabled=True)
                )
                option_list.highlighted = None
                return
            highlighted = 0
            for index, match in enumerate(matches):
                if match.trigger == selected_trigger:
                    highlighted = index
                option_list.add_option(
                    Option(self._match_label(match), id=f"match-{index}")
                )
            option_list.highlighted = highlighted
        finally:
            self._updating_matches = False

    def _refresh_verdict(self) -> None:
        verdict = self.query_one("#snippet-name-verdict", Static)
        trigger = self._current_trigger()
        error = validate_snippet_trigger(trigger)
        if error is not None:
            verdict.set_classes("snippet-name-verdict-error")
            verdict.update(f"✗ Invalid trigger: {error}")
            return
        disabled = self._destination_disabled_reason()
        if disabled is not None:
            verdict.set_classes("snippet-name-verdict-error")
            verdict.update(f"✗ {disabled}")
            return
        analysis = self._analysis()
        if analysis is None:
            verdict.set_classes("snippet-name-verdict-warning")
            verdict.update(f"Checking ⇥ {trigger} in {self._target.display_path}…")
            return
        verdict.set_classes(f"snippet-name-verdict-{analysis.verdict_kind}")
        verdict.update(analysis.verdict)

    async def action_open(self) -> None:
        trigger = self._current_trigger()
        if validate_snippet_trigger(trigger) is not None:
            self._refresh()
            return
        if self._destination_disabled_reason() is not None:
            self._refresh()
            return
        analysis = self._analysis()
        if analysis is None:
            self._refresh()
            return
        redef = analysis.redefinition
        self.dismiss(
            SnippetNameResult(
                trigger=trigger,
                target=self._target,
                exists=analysis.has_collision,
                existing_body=existing_body_for(redef),
                derived_from=derived_from_for(redef),
                save_warning=analysis.save_warning,
            )
        )

    def action_complete_match(self) -> None:
        match = self._highlighted_match()
        if match is None:
            return
        field = self.query_one("#snippet-name-trigger", _SnippetNameInput)
        field.value = match.trigger
        field.cursor_position = len(field.value)
        field.focus()
        self._refresh()

    def action_next_match(self) -> None:
        self._move_match(1)

    def action_prev_match(self) -> None:
        self._move_match(-1)

    def action_change_location(self) -> None:
        """Ask the orchestrator to reopen the location picker."""
        try:
            text = self.query_one("#snippet-name-trigger", _SnippetNameInput).value
        except Exception:
            text = self._initial_trigger
        self.dismiss(ChangeSaveLocationRequest(text=text))

    def _move_match(self, direction: int) -> None:
        option_list = self.query_one("#snippet-name-matches", _SnippetMatchList)
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
        self.query_one("#snippet-name-trigger", _SnippetNameInput).focus()

    def _destination_disabled_reason(self) -> str | None:
        return self._disabled_reason_for_path(str(self._target.write_path))

    def _disabled_reason_for_path(self, path: str) -> str | None:
        location = self._location_for_path(path)
        return location.disabled_reason if location is not None else None

    def _location_for_path(self, path: str) -> SnippetConfigLocation | None:
        from sase.snippet.redefinition import paths_equivalent

        return next(
            (
                location
                for location in self._locations
                if location.path == path or paths_equivalent(location.path, path)
            ),
            None,
        )

    def _highlighted_match(self) -> SnippetMatchPreview | None:
        analysis = self._analysis()
        if analysis is None:
            return None
        option_list = self.query_one("#snippet-name-matches", _SnippetMatchList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return analysis.matches[0] if analysis.matches else None
        option = option_list.get_option_at_index(highlighted)
        if not option.id or not str(option.id).startswith("match-"):
            return analysis.matches[0] if analysis.matches else None
        try:
            index = int(str(option.id).removeprefix("match-"))
        except ValueError:
            return None
        return analysis.matches[index] if 0 <= index < len(analysis.matches) else None

    def _highlighted_match_trigger(self) -> str | None:
        match = self._highlighted_match()
        return match.trigger if match is not None else None

    @staticmethod
    def _match_label(match: SnippetMatchPreview) -> Text:
        text = Text()
        marker = "⇥"
        text.append(f"  {marker} {match.trigger}", style="bold")
        if match.is_destination:
            text.append("  here", style="yellow")
        if match.derived_from:
            text.append(f"  {match.derived_from}", style="dim")
        text.append(f"\n     {match.display_path}", style="dim")
        if match.body_preview:
            text.append(f"   {match.body_preview}", style="italic dim")
        return text

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = [
    "SnippetNameModal",
    "SnippetNameResult",
]
