"""Completion state and catalog loading for the wait modal."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from rich.text import Text
from textual.screen import ModalScreen
from textual.widgets import OptionList
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.ace.tui.models.tribe_display import named_tribe_identity_colors
from sase.ace.tui.models.wait_bead_catalog import (
    WaitBeadCandidate,
    WaitBeadCatalog,
    filter_wait_bead_candidates,
    load_wait_bead_catalog,
)
from sase.project_display_names import project_display_name_for

from .wait_modal_beads import (
    BeadsValidation,
    bead_candidate_option,
    empty_bead_option,
    loading_bead_option,
    overflow_bead_option,
)
from .wait_modal_types import WaitAgentCandidate, WaitModalResult
from .wait_modal_values import (
    active_fragment,
    parse_beads_value,
    prefill_time_token,
    replace_active_fragment,
)
from .wait_modal_widgets import (
    AgentCompletionList,
    BeadCompletionList,
    WaitInput,
    candidate_option,
)

_BEAD_ROW_LIMIT = 100
_ActiveCompletion = Literal["agents", "beads"]


class WaitModalCompletionScreen(ModalScreen[WaitModalResult | None]):
    """Base screen containing state shared by wait completion behaviors."""

    def __init__(
        self,
        current_waiting_for: list[str] | None = None,
        current_waiting_for_beads: list[str] | None = None,
        current_wait_duration: float | None = None,
        current_wait_until: str | None = None,
        current_wait_runners: int | None = None,
        current_wait_priority: int | None = None,
        candidates: list[WaitAgentCandidate] | None = None,
        is_running: bool = False,
        bead_project_key: str | None = None,
        own_bead_ids: frozenset[str] = frozenset(),
        bead_catalog_loader: Callable[..., WaitBeadCatalog] = load_wait_bead_catalog,
    ) -> None:
        """Initialize wait fields and completion state."""
        super().__init__()
        self._current_waiting_for = current_waiting_for or []
        self._current_waiting_for_beads = current_waiting_for_beads or []
        self._bead_prefill = ", ".join(self._current_waiting_for_beads)
        self._time_prefill = prefill_time_token(
            current_wait_duration,
            current_wait_until,
        )
        self._runners_prefill = (
            str(current_wait_runners) if current_wait_runners is not None else ""
        )
        self._priority_prefill = (
            str(current_wait_priority) if current_wait_priority is not None else ""
        )
        self._current_wait_priority = current_wait_priority
        self._candidates = candidates or []
        self._tribe_colors = named_tribe_identity_colors(
            {
                candidate.tribe.removeprefix("@")
                for candidate in self._candidates
                if candidate.tribe
            }
        )
        self._filtered_candidates: list[WaitAgentCandidate] = []
        self._is_running = is_running
        self._programmatic_highlight = False

        self._bead_project_key = bead_project_key
        self._own_bead_ids = frozenset(own_bead_ids)
        self._bead_catalog_loader = bead_catalog_loader
        self._bead_catalog: WaitBeadCatalog | None = None
        self._project_label = bead_project_key or ""
        self._filtered_bead_candidates: list[WaitBeadCandidate] = []
        self._programmatic_bead_highlight = False
        self._active_completion: _ActiveCompletion = "agents"
        self._bead_guard_armed = False
        self._bead_catalog_worker: Worker[tuple[WaitBeadCatalog, str]] | None = None

    def _active_completion_list(self) -> OptionList:
        widget_id = (
            "bead-completion"
            if self._active_completion == "beads"
            else "agent-completion"
        )
        return self.query_one(f"#{widget_id}", OptionList)

    def _set_active_completion(self, name: _ActiveCompletion) -> None:
        if self._active_completion == name:
            return
        self._active_completion = name
        self._apply_active_completion_visibility()

    def _apply_active_completion_visibility(self) -> None:
        agent_list = self.query_one("#agent-completion", AgentCompletionList)
        bead_list = self.query_one("#bead-completion", BeadCompletionList)
        show_agents = self._active_completion == "agents"
        agent_list.display = show_agents
        agent_list.can_focus = show_agents
        bead_list.display = not show_agents
        bead_list.can_focus = not show_agents

    def _refresh_completion(self) -> None:
        """Filter the dropdown on the active comma fragment."""
        agents_input = self.query_one("#agents-input", WaitInput)
        fragment = active_fragment(agents_input.value).lower()
        if fragment:
            self._filtered_candidates = [
                candidate
                for candidate in self._candidates
                if fragment in candidate.search_text
            ]
        else:
            self._filtered_candidates = list(self._candidates)

        option_list = self.query_one("#agent-completion", AgentCompletionList)
        options: list[Option] = [
            candidate_option(
                candidate,
                index,
                tribe_colors=self._tribe_colors,
            )
            for index, candidate in enumerate(self._filtered_candidates)
        ]
        if not options:
            options = [
                Option(Text("  no matching visible agents", style="dim"), disabled=True)
            ]

        self._programmatic_highlight = True
        try:
            option_list.clear_options()
            option_list.add_options(options)
            option_list.highlighted = 0 if self._filtered_candidates else None
        finally:
            self._programmatic_highlight = False

    def _refresh_bead_completion(self) -> None:
        """Filter the bead dropdown on the active comma fragment."""
        beads_input = self.query_one("#beads-input", WaitInput)
        fragment = active_fragment(beads_input.value)
        selected_ids = frozenset(parse_beads_value(beads_input.value))
        option_list = self.query_one("#bead-completion", BeadCompletionList)

        if self._bead_catalog is None:
            self._filtered_bead_candidates = []
            options: list[Option] = [loading_bead_option()]
        else:
            results = filter_wait_bead_candidates(
                self._bead_catalog, fragment, limit=_BEAD_ROW_LIMIT
            )
            self._filtered_bead_candidates = list(results.rows)
            options = [
                bead_candidate_option(candidate, index, selected_ids=selected_ids)
                for index, candidate in enumerate(results.rows)
            ]
            if not options:
                options = [empty_bead_option()]
            elif results.omitted:
                options.append(overflow_bead_option(results.omitted))

        self._programmatic_bead_highlight = True
        try:
            option_list.clear_options()
            option_list.add_options(options)
            option_list.highlighted = 0 if self._filtered_bead_candidates else None
        finally:
            self._programmatic_bead_highlight = False

    def _accept_highlighted_candidate(self) -> bool:
        """Accept the currently highlighted candidate."""
        option_list = self.query_one("#agent-completion", AgentCompletionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return False
        return self._accept_candidate_index(highlighted)

    def _accept_candidate_index(self, index: int | None) -> bool:
        """Insert a candidate into the agents input."""
        if index is None or not (0 <= index < len(self._filtered_candidates)):
            return False
        candidate = self._filtered_candidates[index]
        agents_input = self.query_one("#agents-input", WaitInput)
        agents_input.value = replace_active_fragment(
            agents_input.value,
            candidate.wait_name,
        )
        agents_input.cursor_position = len(agents_input.value)
        agents_input.focus()
        self._refresh_completion()
        return True

    def _accept_highlighted_bead_candidate(self) -> bool:
        """Accept the currently highlighted bead candidate."""
        option_list = self.query_one("#bead-completion", BeadCompletionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return False
        return self._accept_bead_candidate_index(highlighted)

    def _accept_bead_candidate_index(self, index: int | None) -> bool:
        """Insert a bead candidate into the beads input."""
        if index is None or not (0 <= index < len(self._filtered_bead_candidates)):
            return False
        candidate = self._filtered_bead_candidates[index]
        beads_input = self.query_one("#beads-input", WaitInput)
        beads_input.value = replace_active_fragment(
            beads_input.value,
            candidate.bead_id,
        )
        beads_input.cursor_position = len(beads_input.value)
        beads_input.focus()
        self._bead_guard_armed = False
        self._refresh_bead_completion()
        self._update_beads_preview()
        self._update_footer()
        return True

    def _load_bead_catalog(self) -> tuple[WaitBeadCatalog, str]:
        """Load the bead catalog and its project label off the event loop."""
        try:
            if not self._bead_project_key:
                return WaitBeadCatalog(), ""
            catalog = self._bead_catalog_loader(
                self._bead_project_key, own_bead_ids=self._own_bead_ids
            )
            label = project_display_name_for(self._bead_project_key)
            return catalog, label
        except Exception:  # noqa: BLE001 - a failed load must degrade, never raise.
            return WaitBeadCatalog(), self._project_label

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Apply the loaded bead catalog once the worker completes."""
        if event.worker is not self._bead_catalog_worker:
            return
        if event.state != WorkerState.SUCCESS:
            return
        result = event.worker.result
        if result is None:
            return
        catalog, label = result
        self._bead_catalog = catalog
        if label:
            self._project_label = label
        self._refresh_bead_completion()
        self._update_beads_preview()

    def _update_beads_preview(self) -> BeadsValidation:
        """Update the bead preview; implemented by the concrete modal."""
        raise NotImplementedError

    def _update_footer(self) -> None:
        """Update the footer; implemented by the concrete modal."""
        raise NotImplementedError
