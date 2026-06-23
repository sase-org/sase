"""Config tab pane for the Config Center modal.

Phase 3 ships only the skeleton layout: a source rail, a field tree, and a
detail / provenance region, each showing a placeholder. Phases 4 and 5 wire
these regions to the Rust-backed config inventory (browse / inspect /
provenance) and the edit / validate / write flow respectively.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Label, Static


class ConfigPane(Vertical):
    """Placeholder skeleton for the schema-driven config editor."""

    can_focus = True

    def compose(self) -> ComposeResult:
        yield Label("Configuration", id="config-pane-title")
        with Horizontal(id="config-pane-panels"):
            with Vertical(id="config-source-rail"):
                yield Label("Sources", classes="config-region-header")
                yield Static(
                    "built-in · plugins · user base · overlays · local",
                    classes="config-placeholder",
                )
            with Vertical(id="config-field-tree"):
                yield Label("Fields", classes="config-region-header")
                with VerticalScroll(id="config-field-scroll"):
                    yield Static(
                        "The schema-driven field browser arrives in Phase 4.",
                        classes="config-placeholder",
                    )
            with Vertical(id="config-detail"):
                yield Label("Detail", classes="config-region-header")
                with VerticalScroll(id="config-detail-scroll"):
                    yield Static(
                        "Select a field to see its effective value, default, "
                        "and provenance.",
                        classes="config-placeholder",
                    )
        yield Static(
            "Config editing lands in later phases  ·  [ / ]: switch tab  Esc: close",
            id="config-pane-hints",
            markup=False,
        )

    def focus_default(self) -> None:
        """Focus the pane itself when the Config tab activates."""
        try:
            self.focus()
        except Exception:
            pass
