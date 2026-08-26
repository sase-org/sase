"""Always-on query-bar invariant across every resolved Artifacts sub-tab."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.color import Color
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui._artifact_tab_descriptors import (
    assign_artifacts_digit_shortcuts,
    fixed_descriptor,
    provider_descriptors,
)
from sase.ace.tui._artifact_tab_model import PaneCapability, ProviderDiscoveryIssue
from sase.ace.tui.artifacts_description import DEFAULT_ARTIFACTS_DESCRIPTION_MODE
from sase.ace.tui.artifacts_split import DEFAULT_ARTIFACTS_SPLIT_MODE
from sase.ace.tui.widgets.artifacts.view import ArtifactsView
from sase.ace.tui.widgets.filter_bar import FilterBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


def _assert_idle_query_bar(bar: FilterBar, *, accent: str) -> None:
    editor = bar.query_one(f"#{bar.INPUT_ID}", SingleLineVimTextArea)
    sigil = bar.query_one(f"#{bar.SIGIL_ID}", Static)
    assert bar.display is True
    assert not bar._editing  # type: ignore[attr-defined]
    assert editor.read_only is True
    assert editor.can_focus is False
    assert bar.ACCENT == accent
    assert sigil.styles.color == Color.parse(accent)
    assert bar.DISPLAY_ID is not None
    display = bar.query_one(f"#{bar.DISPLAY_ID}", Static)
    assert display.display is True
    assert editor.display is False


async def test_every_resolved_subtab_mounts_idle_query_bar_in_own_accent() -> None:
    """Walk the live resolved tabs: FILTER_SESSION panes keep an idle bar."""
    async with AcePage(initial_tab="artifacts") as page:
        # Import after AcePage's fast-startup patch so this is the mounted set.
        from sase.ace.tui.artifact_tabs import resolve_artifacts_subtabs

        view = page.query_one_widget("#artifacts-view", ArtifactsView)
        descriptors = resolve_artifacts_subtabs()
        assert tuple(item.id for item in view.descriptors) == tuple(
            item.id for item in descriptors
        )
        saw_filter_session = False
        for descriptor in descriptors:
            await page.press(page.artifacts_digit(descriptor.id))
            await page.expect_state("artifacts_subtab", descriptor.id)
            pane = page.query_one_widget(f"#{descriptor.pane_id}")
            bars = list(pane.query(FilterBar))
            contract = descriptor.resolved_contract
            if descriptor.is_degraded or not contract.has(
                PaneCapability.FILTER_SESSION
            ):
                assert bars == [], f"{descriptor.id} must not mount a query bar"
                continue
            saw_filter_session = True
            assert len(bars) == 1, (
                f"{descriptor.id} must mount exactly one query bar, got {len(bars)}"
            )
            _assert_idle_query_bar(bars[0], accent=descriptor.accent)
        assert saw_filter_session


async def test_degraded_resolved_subtab_mounts_no_query_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A contract-failed provider pane has FILTER_SESSION off and no bar."""
    descriptors = assign_artifacts_digit_shortcuts(
        (
            fixed_descriptor("stitches"),
            *provider_descriptors(
                (),
                (
                    ProviderDiscoveryIssue(
                        message=(
                            "artifact ref provider 'research-docs' is not installed"
                        ),
                        code="missing_ref_provider",
                        kind="research",
                    ),
                ),
            ),
        )
    )
    degraded = next(item for item in descriptors if item.is_degraded)
    assert not degraded.resolved_contract.has(PaneCapability.FILTER_SESSION)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.view.resolve_artifacts_subtabs",
        lambda: descriptors,
    )

    class _App(App[None]):
        ENABLE_COMMAND_PALETTE = False
        artifacts_split_mode = DEFAULT_ARTIFACTS_SPLIT_MODE
        artifacts_description_mode = DEFAULT_ARTIFACTS_DESCRIPTION_MODE

        def compose(self) -> ComposeResult:
            yield ArtifactsView()

    app = _App()
    async with app.run_test():
        view = app.query_one(ArtifactsView)
        view.switch_to(degraded.id)
        pane = app.query_one(f"#{degraded.pane_id}")
        assert list(pane.query(FilterBar)) == []
