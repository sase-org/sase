"""Widget-level coverage for the Artifacts degraded provider surface."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.widgets.artifacts.panes import ArtifactsDegradedPane


class _DegradedApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield ArtifactsDegradedPane(
            provider_kind="research",
            provider_label="Research",
            error="ref.inventory is missing a root",
            error_code="ref_inventory_missing_root",
            error_source="sidecar.yml",
            id="artifacts-ref-research-pane",
        )


async def test_degraded_pane_renders_provider_identity_and_diagnostics() -> None:
    app = _DegradedApp()
    async with app.run_test():
        pane = app.query_one(ArtifactsDegradedPane)
        hero = pane.query_one(".artifacts-degraded-hero", Static)
        card = pane.query_one(".artifacts-degraded-card", Static)

        hero_text = hero.render()
        card_text = card.render()

        assert "Research" in str(hero_text)
        assert "research" in str(hero_text)
        assert "ref_inventory_missing_root" in str(card_text)
        assert "ref.inventory is missing a root" in str(card_text)
        assert "sidecar.yml" in str(card_text)
        assert card.border_title == "Provider unavailable"


async def test_degraded_pane_stays_mounted_and_named_without_error_source() -> None:
    class _App(App[None]):
        ENABLE_COMMAND_PALETTE = False

        def compose(self) -> ComposeResult:
            yield ArtifactsDegradedPane(
                provider_kind="unknown",
                provider_label="Unknown",
                error="Provider failed to load",
            )

    app = _App()
    async with app.run_test():
        pane = app.query_one(ArtifactsDegradedPane)
        assert pane.is_mounted
        assert pane.provider_label == "Unknown"
        card = pane.query_one(".artifacts-degraded-card", Static)
        assert "source:" not in str(card.render())
