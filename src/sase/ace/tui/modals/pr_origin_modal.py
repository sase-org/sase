"""PR_ORIGIN selection modal for the ace TUI."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from ...patch import PR_ORIGIN_VALUES, normalize_pr_origin
from .base import OptionListNavigationMixin


class PrOriginModal(OptionListNavigationMixin, ModalScreen[str | None]):
    """Modal for deliberately marking a Patch's PR_ORIGIN."""

    _option_list_id = "pr-origin-list"
    BINDINGS = [*OptionListNavigationMixin.NAVIGATION_BINDINGS]

    def __init__(self, current_pr_origin: str) -> None:
        """Initialize the PR_ORIGIN modal.

        Args:
            current_pr_origin: The Patch's current (unnormalized) PR_ORIGIN value.
        """
        super().__init__()
        self.current_pr_origin = normalize_pr_origin(current_pr_origin)

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            yield Label("Mark PR Origin", id="modal-title")
            yield OptionList(
                *[
                    Option(
                        f"{origin} (current)"
                        if origin == self.current_pr_origin
                        else origin,
                        id=origin,
                    )
                    for origin in sorted(PR_ORIGIN_VALUES)
                ],
                id="pr-origin-list",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        if event.option and event.option.id:
            self.dismiss(str(event.option.id))
