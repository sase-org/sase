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
    target: str = "large",
    operation: str = "persistent",
    views=None,
) -> AliasSelectionContext:
    """Build the standard alias selection context used by picker tests."""
    if views is None:
        views = [
            make_alias_view("xsmall", "role", provider="claude", model="sonnet"),
            make_alias_view("small", "role", provider="claude", model="sonnet"),
            make_alias_view(
                "medium",
                "role",
                provider="codex",
                model="gpt-5.5",
            ),
            make_alias_view("large", "role", provider="claude", model="opus"),
            make_alias_view("xlarge", "role", provider="claude", model="opus"),
        ]
    return AliasSelectionContext(
        views=tuple(views),
        target_alias=target,
        operation=operation,  # type: ignore[arg-type]
    )
