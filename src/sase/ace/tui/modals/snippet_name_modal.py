"""Trigger-name panel for opening a snippet target pane."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.xprompt.naming import validate_snippet_trigger
from sase.xprompt.snippet_targets import (
    SnippetCollision,
    SnippetConfigLocation,
    SnippetSaveTarget,
    load_snippet_template,
    snippet_collision,
)
from sase.xprompt.write_targets import write_target_for_written_path


@dataclass(frozen=True, slots=True)
class SnippetNameResult:
    """Trigger and starting body chosen by the snippet-name panel."""

    trigger: str
    target: SnippetSaveTarget
    exists: bool
    existing_body: str | None
    derived_from: str | None
    save_warning: str | None = None


@dataclass(frozen=True, slots=True)
class _SnippetMatchPreview:
    trigger: str
    location_path: str | None
    display_path: str
    body_preview: str
    is_destination: bool = False
    derived_from: str | None = None


@dataclass(frozen=True, slots=True)
class _SnippetNameAnalysis:
    trigger: str
    destination_path: str
    collision: SnippetCollision
    destination_exists: bool
    matches: tuple[_SnippetMatchPreview, ...]

    @property
    def has_collision(self) -> bool:
        return self.destination_exists or bool(
            self.collision.matches or self.collision.derived_from
        )


class _SnippetNameInput(Input):
    """Single-line trigger field whose navigation keys stay modal-scoped."""

    BINDINGS = [
        Binding("tab", "forward('complete_match')", show=False),
        Binding("up", "forward('prev_destination')", show=False),
        Binding("down", "forward('next_destination')", show=False),
        Binding("ctrl+n", "forward('next_destination')", show=False),
        Binding("ctrl+p", "forward('prev_destination')", show=False),
    ]

    def action_forward(self, action_name: str) -> None:
        action = getattr(self.screen, f"action_{action_name}", None)
        if callable(action):
            action()


class _SnippetMatchList(OptionList):
    """Read-only match list with Tab completion forwarded to the screen."""

    BINDINGS = [
        Binding("tab", "forward('complete_match')", show=False),
        Binding("up", "forward('prev_destination')", show=False),
        Binding("down", "forward('next_destination')", show=False),
    ]

    def action_forward(self, action_name: str) -> None:
        action = getattr(self.screen, f"action_{action_name}", None)
        if callable(action):
            action()


class SnippetNameModal(ModalScreen[SnippetNameResult | None]):
    """Ask for a snippet trigger and report collisions live."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "open", "Open", show=False),
        Binding("tab", "complete_match", "Complete", show=False),
        Binding("up", "prev_destination", "Previous destination", show=False),
        Binding("down", "next_destination", "Next destination", show=False),
        Binding("ctrl+n", "next_destination", "Next destination", show=False),
        Binding("ctrl+p", "prev_destination", "Previous destination", show=False),
    ]

    def __init__(
        self,
        target: SnippetSaveTarget,
        locations: Sequence[SnippetConfigLocation],
        *,
        derived_snippets: Mapping[str, str] | None = None,
        derived_sources: Mapping[str, str] | None = None,
        initial_trigger: str = "",
    ) -> None:
        super().__init__()
        self._initial_target = target
        self._target = target
        self._locations = list(locations)
        self._derived_snippets = dict(derived_snippets or {})
        self._derived_sources = dict(derived_sources or {})
        self._initial_trigger = initial_trigger
        self._updating_matches = False
        self._analysis_debouncer: DetailPanelDebouncer | None = None
        self._analysis_tasks: set[asyncio.Task[None]] = set()
        self._pending_analyses: set[tuple[str, str]] = set()
        self._analysis_cache: dict[tuple[str, str], _SnippetNameAnalysis] = {}

    def compose(self) -> ComposeResult:
        with Container(id="snippet-name-container"):
            yield Label("New snippet", id="snippet-name-title")
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
                    yield Static("Destination", classes="snippet-name-panel-title")
                    yield Static("", id="snippet-name-destination", markup=False)
            yield Static("", id="snippet-name-verdict", markup=False)
            yield Static(
                "tab complete · ↑↓ destination · enter open · esc cancel",
                id="snippet-name-hints",
                markup=False,
            )

    def on_mount(self) -> None:
        self._analysis_debouncer = DetailPanelDebouncer(self.app)
        field = self.query_one("#snippet-name-trigger", _SnippetNameInput)
        field.focus()
        field.cursor_position = len(field.value)
        self._refresh()

    def on_unmount(self) -> None:
        if self._analysis_debouncer is not None:
            self._analysis_debouncer.cancel()
        for task in self._analysis_tasks:
            task.cancel()

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

    def _refresh(self) -> None:
        self._refresh_destination()
        self._refresh_matches()
        self._refresh_verdict()
        identity = self._identity()
        if identity is not None and identity not in self._analysis_cache:
            self._schedule_analysis(identity)

    def _refresh_destination(self) -> None:
        line = self.query_one("#snippet-name-destination", Static)
        message = self._target.display_path
        if self._target.fallback_reason:
            message += f" · configured path unusable: {self._target.fallback_reason}"
        disabled = self._destination_disabled_reason()
        if disabled is not None:
            message += f" · {disabled}"
        line.update(message)

    def _refresh_matches(self) -> None:
        option_list = self.query_one("#snippet-name-matches", _SnippetMatchList)
        identity = self._identity()
        analysis = self._analysis_cache.get(identity) if identity is not None else None
        selected_trigger = self._highlighted_match_trigger()
        self._updating_matches = True
        try:
            option_list.clear_options()
            if self._current_trigger() and analysis is None and identity is not None:
                option_list.add_option(
                    Option(Text("  Checking matches…"), disabled=True)
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
        identity = self._identity()
        analysis = self._analysis_cache.get(identity) if identity is not None else None
        if analysis is None:
            verdict.set_classes("snippet-name-verdict-warning")
            verdict.update(f"Checking ⇥ {trigger} in {self._target.display_path}…")
            return
        collision = analysis.collision
        if analysis.destination_exists:
            verdict.set_classes("snippet-name-verdict-warning")
            verdict.update(
                f"⚠ ⇥ {trigger} exists here — Enter loads its definition for editing"
            )
            return
        if collision.shadowed_by:
            verdict.set_classes("snippet-name-verdict-warning")
            source = self._display_for_path(collision.shadowed_by)
            verdict.update(
                f"⚠ ⇥ {trigger} is defined in {source} — saving here will be shadowed by {source}"
            )
            return
        if collision.shadows:
            verdict.set_classes("snippet-name-verdict-warning")
            source = self._display_for_path(collision.shadows)
            verdict.update(
                f"⚠ ⇥ {trigger} is defined in {source} — saving here will shadow it"
            )
            return
        if collision.matches:
            verdict.set_classes("snippet-name-verdict-warning")
            source = collision.matches[0].display_path
            verdict.update(
                f"⚠ ⇥ {trigger} is defined in {source} — saving here will shadow it"
            )
            return
        if collision.derived_from:
            verdict.set_classes("snippet-name-verdict-warning")
            verdict.update(
                f"⚠ ⇥ {trigger} comes from {collision.derived_from} — this entry will override it"
            )
            return
        verdict.set_classes("snippet-name-verdict-success")
        verdict.update(f"✓ Create ⇥ {trigger} in {self._target.display_path}")

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
        trigger = identity[0]
        target = self._target
        try:
            analysis = await asyncio.to_thread(
                self._build_analysis,
                trigger,
                target,
                tuple(self._locations),
                dict(self._derived_snippets),
                dict(self._derived_sources),
            )
        finally:
            self._pending_analyses.discard(identity)
        if self.is_mounted and self._identity() == identity:
            self._analysis_cache[identity] = analysis
            self._refresh()

    @staticmethod
    def _build_analysis(
        trigger: str,
        target: SnippetSaveTarget,
        locations: tuple[SnippetConfigLocation, ...],
        derived_snippets: dict[str, str],
        derived_sources: dict[str, str],
    ) -> _SnippetNameAnalysis:
        collision = snippet_collision(
            trigger,
            target,
            locations=locations,
            derived=derived_sources,
        )
        matches = _prefix_matches(
            trigger, target, locations, derived_snippets, derived_sources
        )
        destination_exists = any(match.is_destination for match in matches)
        if not destination_exists and str(target.write_path) not in {
            location.path for location in locations
        }:
            try:
                load_snippet_template(target.write_path, trigger)
            except (OSError, KeyError):
                destination_exists = False
            else:
                destination_exists = True
        return _SnippetNameAnalysis(
            trigger=trigger,
            destination_path=str(target.write_path),
            collision=collision,
            destination_exists=destination_exists,
            matches=matches,
        )

    async def action_open(self) -> None:
        trigger = self._current_trigger()
        if validate_snippet_trigger(trigger) is not None:
            self._refresh()
            return
        if self._destination_disabled_reason() is not None:
            self._refresh()
            return
        identity = self._identity()
        if identity is None:
            self._refresh()
            return
        analysis = self._analysis_cache.get(identity)
        if analysis is None:
            analysis = await asyncio.to_thread(
                self._build_analysis,
                trigger,
                self._target,
                tuple(self._locations),
                dict(self._derived_snippets),
                dict(self._derived_sources),
            )
            if self._identity() != identity:
                self._refresh()
                return
            self._analysis_cache[identity] = analysis
        try:
            result = await self._result_for_analysis(analysis)
        except Exception as exc:
            verdict = self.query_one("#snippet-name-verdict", Static)
            verdict.set_classes("snippet-name-verdict-error")
            verdict.update(f"✗ Failed to load snippet definition: {exc}")
            return
        self.dismiss(result)

    async def _result_for_analysis(
        self, analysis: _SnippetNameAnalysis
    ) -> SnippetNameResult:
        trigger = analysis.trigger
        existing_body: str | None = None
        derived_from: str | None = None
        if analysis.destination_exists:
            existing_body = await asyncio.to_thread(
                load_snippet_template,
                self._target.write_path,
                trigger,
            )
        else:
            other_path = self._collision_body_path(analysis)
            if other_path is not None:
                existing_body = await asyncio.to_thread(
                    load_snippet_template,
                    other_path,
                    trigger,
                )
            elif analysis.collision.derived_from:
                existing_body = self._derived_snippets.get(trigger)
                derived_from = analysis.collision.derived_from
        return SnippetNameResult(
            trigger=trigger,
            target=self._target,
            exists=analysis.has_collision,
            existing_body=existing_body,
            derived_from=derived_from,
            save_warning=self._save_warning_for_analysis(analysis),
        )

    def _collision_body_path(self, analysis: _SnippetNameAnalysis) -> str | None:
        collision = analysis.collision
        if collision.shadowed_by:
            return collision.shadowed_by
        if collision.shadows:
            return collision.shadows
        match = next(
            (item for item in collision.matches if not item.is_destination), None
        )
        return match.location_path if match is not None else None

    def _save_warning_for_analysis(self, analysis: _SnippetNameAnalysis) -> str | None:
        if analysis.destination_exists:
            return None
        collision = analysis.collision
        if collision.derived_from:
            return (
                f"⚠ ⇥ {analysis.trigger} comes from {collision.derived_from} — "
                "this entry will override it"
            )
        if collision.shadowed_by:
            source = self._display_for_path(collision.shadowed_by)
            return (
                f"⚠ ⇥ {analysis.trigger} is defined in {source} — "
                f"saving here will be shadowed by {source}"
            )
        if collision.shadows:
            source = self._display_for_path(collision.shadows)
            return (
                f"⚠ ⇥ {analysis.trigger} is defined in {source} — "
                "saving here will shadow it"
            )
        match = next(
            (item for item in collision.matches if not item.is_destination), None
        )
        if match is not None:
            return (
                f"⚠ ⇥ {analysis.trigger} is defined in {match.display_path} — "
                "saving here will shadow it"
            )
        return None

    def action_complete_match(self) -> None:
        match = self._highlighted_match()
        if match is None:
            return
        field = self.query_one("#snippet-name-trigger", _SnippetNameInput)
        field.value = match.trigger
        field.cursor_position = len(field.value)
        field.focus()
        self._refresh()

    def action_next_destination(self) -> None:
        self._move_destination(1)

    def action_prev_destination(self) -> None:
        self._move_destination(-1)

    def _move_destination(self, direction: int) -> None:
        choices = self._destination_choices()
        if not choices:
            return
        current_path = str(self._target.write_path)
        try:
            current = next(
                index
                for index, (_, target) in enumerate(choices)
                if str(target.write_path) == current_path
            )
        except StopIteration:
            current = -1 if direction > 0 else 0
        target = choices[(current + direction) % len(choices)][1]
        if target == self._target:
            return
        self._target = target
        self._refresh()

    def _destination_choices(
        self,
    ) -> tuple[tuple[SnippetConfigLocation | None, SnippetSaveTarget], ...]:
        seen: set[str] = set()
        choices: list[tuple[SnippetConfigLocation | None, SnippetSaveTarget]] = []

        initial_key = str(self._initial_target.write_path)
        initial_reason = self._disabled_reason_for_path(initial_key)
        if initial_reason is None:
            choices.append((self._location_for_path(initial_key), self._initial_target))
            seen.add(initial_key)
        for location in self._locations:
            if not location.is_selectable or location.path in seen:
                continue
            target = self._target_for_location(location)
            choices.append((location, target))
            seen.add(str(target.write_path))
        return tuple(choices)

    def _target_for_location(
        self, location: SnippetConfigLocation
    ) -> SnippetSaveTarget:
        write_target = write_target_for_written_path(location.path)
        return SnippetSaveTarget(
            read_path=write_target.read_path,
            write_path=write_target.write_path,
            apply_target=write_target.apply_target,
            via_chezmoi=write_target.via_chezmoi,
            display_path=location.display_path,
            source="configured",
            fallback_reason=None,
        )

    def _destination_disabled_reason(self) -> str | None:
        return self._disabled_reason_for_path(str(self._target.write_path))

    def _disabled_reason_for_path(self, path: str) -> str | None:
        location = self._location_for_path(path)
        return location.disabled_reason if location is not None else None

    def _location_for_path(self, path: str) -> SnippetConfigLocation | None:
        return next(
            (location for location in self._locations if location.path == path), None
        )

    def _highlighted_match(self) -> _SnippetMatchPreview | None:
        identity = self._identity()
        analysis = self._analysis_cache.get(identity) if identity is not None else None
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
    def _match_label(match: _SnippetMatchPreview) -> Text:
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

    def _display_for_path(self, path: str) -> str:
        location = self._location_for_path(path)
        return location.display_path if location is not None else path

    def action_cancel(self) -> None:
        self.dismiss(None)


def _prefix_matches(
    trigger: str,
    target: SnippetSaveTarget,
    locations: tuple[SnippetConfigLocation, ...],
    derived_snippets: dict[str, str],
    derived_sources: dict[str, str],
) -> tuple[_SnippetMatchPreview, ...]:
    if not trigger:
        return ()
    from sase.xprompt.save_index import names_for_location

    matches: list[tuple[tuple[object, ...], _SnippetMatchPreview]] = []
    for source_order, location in enumerate(locations):
        for name in sorted(names_for_location("snippet_config", location.path)):
            if not name.startswith(trigger):
                continue
            body = _preview_for_template(location.path, name)
            match = _SnippetMatchPreview(
                trigger=name,
                location_path=location.path,
                display_path=location.display_path,
                body_preview=body,
                is_destination=location.path == str(target.write_path),
            )
            matches.append(
                (
                    (
                        name != trigger,
                        name.casefold(),
                        source_order,
                        0,
                    ),
                    match,
                )
            )
    for source_order, (name, template) in enumerate(sorted(derived_snippets.items())):
        if not name.startswith(trigger):
            continue
        source = derived_sources.get(name, f"#{name}")
        match = _SnippetMatchPreview(
            trigger=name,
            location_path=None,
            display_path=source,
            body_preview=_single_line(template),
            derived_from=source,
        )
        matches.append(((name != trigger, name.casefold(), source_order, 1), match))
    return tuple(match for _, match in sorted(matches, key=lambda item: item[0])[:6])


def _preview_for_template(path: str, trigger: str) -> str:
    try:
        return _single_line(load_snippet_template(path, trigger))
    except Exception:
        return "(preview unavailable)"


def _single_line(value: str, *, max_chars: int = 52) -> str:
    line = " ".join(value.split())
    if len(line) <= max_chars:
        return line
    return line[: max_chars - 1] + "…"


__all__ = [
    "SnippetNameModal",
    "SnippetNameResult",
]
