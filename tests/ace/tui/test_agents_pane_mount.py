"""End-to-end mount and lifecycle coverage for the Artifacts Agent pane.

``AcePage``'s default "fast" startup policy patches ``resolve_artifacts_subtabs``
to a fixed stub (see ``sase.ace.testing._startup._install_fast_startup_overrides``),
which would silently bypass the ``artifacts_agents_pane`` flag gate entirely.
This uses ``startup_policy="real"`` so the live, flag-gated resolution actually
runs, proving the pane mounts, activates, loads a real (if empty in this
sandboxed environment) catalog snapshot, and renders the shared shell without
crashing -- the part the widget-free contract/conformance tests cannot see.
"""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.artifact_tabs import reset_artifacts_subtabs_cache
from sase.ace.tui.widgets.artifacts.agents_pane import ArtifactsAgentsPane
from sase.ace.tui.widgets.artifacts.shell import ArtifactsPaneState
from sase.feature_flags import override_flags


async def test_agents_pane_mounts_activates_and_loads() -> None:
    with override_flags(artifacts_agents_pane=True):
        reset_artifacts_subtabs_cache()
        try:
            async with AcePage(initial_tab="patches", startup_policy="real") as page:
                await page.press(page.artifacts_digit("agents"))
                await page.pause()
                pane = page.query_one_widget(
                    "#artifacts-agents-pane", ArtifactsAgentsPane
                )
                assert pane.artifacts_active is True
                assert pane.first_activation_count == 1
                await page.pause()
                assert pane.pane_state() in {
                    ArtifactsPaneState.RESULTS,
                    ArtifactsPaneState.EMPTY,
                }
                assert pane.snapshot is not None
        finally:
            reset_artifacts_subtabs_cache()
