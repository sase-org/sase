"""Fleet skip-path repaint: rendered-only panel rebuilds."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from rich.text import Text

from sase.ace.tui.models import _agent_tree as agent_tree_mod
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups._tree_summary import _host_feed_status_label
from sase.ace.tui.models.fleet_agents import FleetRowsProjection
from sase.ace.tui.widgets._agent_list_render_agent import _append_fleet_summary
from tests.ace.tui._agents_fleet_refresh_laziness_shared import FleetRefreshHarness
from tests.ace.tui.fleet_fixture import fleet_config

__all__ = [
    "test_skip_path_ignores_observed_and_fresh_cache_age",
    "test_skip_path_stale_repaints_only_affected_panel",
]


def _remote_row(
    name: str = "sase-main",
    *,
    status: str = "RUNNING",
    revision: int = 1,
    freshness: str | None = "fresh",
    observed_at_unix: float | None = 100.0,
    host_cache_age_seconds: float | None = 2.0,
    host_running_count: int | None = 3,
    host_total_count: int | None = 5,
    diagnostic: str | None = None,
) -> Agent:
    return Agent(
        AgentType.RUNNING,
        name,
        "/fleet/apollo/project.yml",
        status,
        None,
        agent_name=name,
        raw_suffix=f"apollo:{name}",
        fleet_origin_alias="apollo",
        fleet_origin_installation_id="install-apollo",
        fleet_logical_key=f"apollo:{name}",
        fleet_exact_key=f"apollo:{name}:exact",
        fleet_revision=revision,
        fleet_freshness=freshness,
        fleet_observed_at_unix=observed_at_unix,
        fleet_host_cache_age_seconds=host_cache_age_seconds,
        fleet_host_running_count=host_running_count,
        fleet_host_total_count=host_total_count,
        fleet_diagnostic=diagnostic,
    )


def _count_tree_projections(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[int, int]]:
    """Count project_mixed_agent_tree runs (local-size, remote-size)."""
    calls: list[tuple[int, int]] = []
    real = agent_tree_mod.project_mixed_agent_tree

    def _counting(
        local_agents: list[Agent],
        remote_agents: list[Agent],
    ) -> list[Agent]:
        calls.append((len(local_agents), len(remote_agents)))
        return real(local_agents, remote_agents)

    monkeypatch.setattr(
        agent_tree_mod,
        "project_mixed_agent_tree",
        _counting,
    )
    return calls


class _PanelTrackingHarness(FleetRefreshHarness):
    """Harness with a fake panel index and panel-rebuild tracking."""

    def __init__(self) -> None:
        super().__init__()
        self.rebuilt_panels: list[set[str]] = []
        self.display_refreshes = 0
        self.info_refreshes = 0
        self.detail_refreshes = 0

    def _agent_panel_index(self) -> SimpleNamespace:
        return SimpleNamespace(
            keys_per_agent=[f"key-{idx}" for idx in range(len(self._agents))],
        )

    def _refresh_affected_panel_widgets(self, affected_keys: set[str]) -> bool:
        self.rebuilt_panels.append(set(affected_keys))
        return True

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        self.display_refreshes += 1

    def _update_agents_info_panel(self) -> None:
        self.info_refreshes += 1

    def _refresh_agent_focus_detail(self) -> None:
        self.detail_refreshes += 1
        self.info_refreshes += 1


def test_skip_path_ignores_observed_and_fresh_cache_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only observed time / fresh-host cache age changes rebuild no panel."""
    tree_calls = _count_tree_projections(monkeypatch)
    app = _PanelTrackingHarness()
    snapshot = (("snapshot", "snap-1"),)

    app._apply_fleet_projection(
        FleetRowsProjection(
            fleet_rows=(_remote_row(),),
            snapshot_identities=snapshot,
            configured_host_count=1,
        ),
        config=fleet_config(),
        generation=1,
        source="apply",
    )
    assert len(tree_calls) == 1
    header_after_first = app.header_updates

    app._apply_fleet_projection(
        FleetRowsProjection(
            fleet_rows=(
                _remote_row(observed_at_unix=200.0, host_cache_age_seconds=9.0),
            ),
            snapshot_identities=snapshot,
            configured_host_count=1,
        ),
        config=fleet_config(),
        generation=1,
        source="apply",
    )

    assert len(tree_calls) == 1
    assert app.header_updates == header_after_first + 1
    assert app.rebuilt_panels == []
    assert app.display_refreshes == 0
    live = app._agents[0]
    assert live.fleet_observed_at_unix == 200.0
    assert live.fleet_host_cache_age_seconds == 9.0


def test_skip_path_stale_repaints_only_affected_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh-to-stale on the skip path repaints only that host's panel."""
    tree_calls = _count_tree_projections(monkeypatch)
    app = _PanelTrackingHarness()
    snapshot = (("snapshot", "snap-1"),)

    app._apply_fleet_projection(
        FleetRowsProjection(
            fleet_rows=(
                _remote_row("sase-main"),
                _remote_row("sase-other"),
            ),
            snapshot_identities=snapshot,
            configured_host_count=1,
        ),
        config=fleet_config(),
        generation=1,
        source="apply",
    )
    assert len(tree_calls) == 1
    header_after_first = app.header_updates

    app._apply_fleet_projection(
        FleetRowsProjection(
            fleet_rows=(
                _remote_row(
                    "sase-main",
                    freshness="stale",
                    observed_at_unix=200.0,
                    host_cache_age_seconds=95.0,
                ),
                _remote_row("sase-other"),
            ),
            snapshot_identities=snapshot,
            configured_host_count=1,
        ),
        config=fleet_config(),
        generation=1,
        source="apply",
    )

    assert len(tree_calls) == 1
    assert app.header_updates == header_after_first + 1
    assert app.rebuilt_panels == [{"key-0"}]
    assert app.display_refreshes == 0
    live = app._agents[0]
    assert live.fleet_freshness == "stale"
    row_text = Text()
    _append_fleet_summary(row_text, live)
    assert "stale" in row_text.plain
    assert _host_feed_status_label(live) is not None
    assert "stale" in str(_host_feed_status_label(live))
