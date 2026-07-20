"""Shared helpers for model picker modal tests."""

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.tui.modals.model_picker_modal import AliasSelectionContext
from tests._models_panel_helpers import make_alias_view

_ROOT = Path(__file__).resolve().parents[1]


class ModelPickerTestApp(App[str | None]):
    """Minimal app for async model picker tests."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


class StyledModelPickerTestApp(ModelPickerTestApp):
    """Model picker test app with the production TUI styles loaded."""

    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"


def make_alias_context(
    *,
    target: str = "big_epic_lander",
    operation: str = "persistent",
    views=None,
) -> AliasSelectionContext:
    """Build the standard alias selection context used by picker tests."""
    if views is None:
        views = [
            make_alias_view(
                "default",
                "default",
                provider="claude",
                model="opus",
                description="Default launch model.",
            ),
            make_alias_view(
                "coder",
                "role",
                provider="codex",
                model="gpt-5.6-sol",
                description="Implementation follow-up agents.",
            ),
            make_alias_view("epic_lander", "role", provider="claude", model="opus"),
            make_alias_view("big_epic_lander", "role", provider="claude", model="opus"),
            make_alias_view("phase_worker", "role", provider="claude", model="sonnet"),
        ]
    return AliasSelectionContext(
        views=tuple(views),
        target_alias=target,
        operation=operation,  # type: ignore[arg-type]
    )
