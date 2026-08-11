"""Modals for Beads external issue actions."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from sase.ace.tui.widgets.artifacts.beads_data_models import ExternalIssueLink

from .base import OptionListNavigationMixin


class BeadIssueSelectModal(
    OptionListNavigationMixin,
    ModalScreen[ExternalIssueLink | None],
):
    """Pick one linked external issue for a Beads action."""

    _option_list_id = "bead-issue-select-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "select_current", "Select"),
    ]

    def __init__(self, links: tuple[ExternalIssueLink, ...]) -> None:
        super().__init__()
        self._links = links
        self._by_id = {str(index): link for index, link in enumerate(links)}

    def compose(self) -> ComposeResult:
        with Container(id="bead-issue-select-container"):
            yield Label("Select Issue", id="modal-title")
            yield OptionList(
                *(
                    Option(_issue_option_text(index, link), id=str(index))
                    for index, link in enumerate(self._links)
                ),
                id=self._option_list_id,
            )

    def on_option_list_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        if event.option and event.option.id:
            self.dismiss(self._by_id.get(event.option.id))

    def action_select_current(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        if option_list.highlighted is None:
            self.dismiss(None)
            return
        option = option_list.get_option_at_index(option_list.highlighted)
        self.dismiss(self._by_id.get(option.id or ""))


def _issue_option_text(index: int, link: ExternalIssueLink) -> Text:
    state = link.state
    glyph = "?" if link.stale else "●" if state == "closed" else "○"
    text = Text()
    text.append(f"{index + 1}. ", style="dim")
    text.append(f"{glyph} ", style="bold #FF5F5F")
    text.append(f"{link.display_project} #{link.issue_id}", style="bold white")
    text.append(f"  {state}", style="#FF5F5F")
    text.append(f"  {link.relation}", style="dim")
    if link.drift:
        text.append("  drift", style="bold #FF5F5F")
    if link.issue is not None and link.issue.title:
        text.append(f"  {link.issue.title}", style="white")
    return text


__all__ = ["BeadIssueSelectModal"]
