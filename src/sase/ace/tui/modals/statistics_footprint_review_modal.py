"""Decision and finish-confirmation modals for Statistics Footprint review."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from .base import OptionListNavigationMixin

_KEEP_REASONS: tuple[tuple[str, str], ...] = (
    ("rare_by_design", "Rare by design"),
    ("safety", "Safety"),
    ("agent_facing", "Agent-facing API"),
    ("api_contract", "API contract"),
    ("other", "Other"),
)


@dataclass(frozen=True)
class FootprintReviewCounts:
    """Counts shown before a marked review set is sent to an agent."""

    keep: int
    later: int
    cut: int

    @property
    def actionable(self) -> int:
        """Keep and cut decisions need repository follow-up."""
        return self.keep + self.cut


class StatisticsFootprintKeepReasonModal(
    OptionListNavigationMixin,
    ModalScreen[str | None],
):
    """Choose one curated reason for keeping a Footprint feature."""

    _option_list_id = "statistics-footprint-keep-reason-list"
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        *OptionListNavigationMixin.NAVIGATION_BINDINGS[2:],
        ("enter", "select_highlighted", "Apply"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="statistics-footprint-keep-reason-container"):
            yield Static(
                "Keep this feature because…",
                id="statistics-footprint-keep-reason-title",
            )
            yield OptionList(
                *[
                    Option(Text(label, style="bold"), id=reason)
                    for reason, label in _KEEP_REASONS
                ],
                id=self._option_list_id,
            )
            yield Static(
                "Enter choose · j/k or ↑/↓ move · q/Esc cancel",
                id="statistics-footprint-keep-reason-hints",
            )

    def on_mount(self) -> None:
        self.query_one(f"#{self._option_list_id}", OptionList).highlighted = 0
        self.query_one(f"#{self._option_list_id}", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id))

    def action_select_highlighted(self) -> None:
        options = self.query_one(f"#{self._option_list_id}", OptionList)
        highlighted = options.highlighted
        if highlighted is not None and 0 <= highlighted < len(_KEEP_REASONS):
            self.dismiss(_KEEP_REASONS[highlighted][0])

    def action_cancel(self) -> None:
        self.dismiss(None)


class StatisticsFootprintFinishReviewModal(ModalScreen[bool]):
    """Confirm launching an agent to process the marked Footprint decisions."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("enter", "launch", "Launch review"),
        ("a", "launch", "Launch review"),
    ]

    def __init__(self, counts: FootprintReviewCounts) -> None:
        super().__init__()
        self._counts = counts

    def compose(self) -> ComposeResult:
        with Container(id="statistics-footprint-finish-container"):
            yield Static(
                "Finish Footprint review?", id="statistics-footprint-finish-title"
            )
            yield Static(
                Text(
                    f"{self._counts.keep} keep · {self._counts.later} later · "
                    f"{self._counts.cut} cut\n\n"
                    "This launches #footprint_review with the marked decisions. "
                    "The agent can record keep reasons in the repo overlay and file "
                    "task beads for cuts. It will not delete code.",
                    justify="center",
                ),
                id="statistics-footprint-finish-summary",
            )
            yield Static(
                "Enter launch · q/Esc cancel",
                id="statistics-footprint-finish-hints",
            )

    def action_launch(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


__all__ = [
    "FootprintReviewCounts",
    "StatisticsFootprintFinishReviewModal",
    "StatisticsFootprintKeepReasonModal",
]
