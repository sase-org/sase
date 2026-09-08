"""TUI-level Fleet refresh laziness regressions."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.actions.agents import _fleet as fleet_mod
from sase.ace.tui.actions.agents._fleet import AgentFleetMixin
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.fleet_agents import FleetRowsProjection
from sase.dispatch.federation import FederationConfig, FederationWorkerSettings
from sase.dispatch.follow_store import FollowStoreSnapshot
from tests.ace.tui.fleet_fixture import (
    OfflineFleetFacade,
    fleet_attention_response,
    fleet_config,
    fleet_follow_snapshot,
    fleet_host_response,
    fleet_summary,
)


class _FleetRefreshHarness(AgentFleetMixin):
    """Minimal Agents-tab host for exercising fleet refresh projection."""

    def __init__(self, *, mode: str = "focus") -> None:
        self.current_agents_subtab = mode
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_local_with_children: list[Agent] = []
        self._agents_local_visible: list[Agent] = []
        self._agents_fleet_rows: list[Agent] = []
        self._agents_fleet_focus_rows: list[Agent] = []
        self._agents_fleet_projection = FleetRowsProjection()
        self._agents_fleet_async_tasks: set[Any] = set()
        self._agents_fleet_refresh_generation = 1
        self._agents_fleet_loading = True
        self._agents_fleet_available = False
        self._agents_fleet_last_error = None
        self._agents_refresh_active_source = "unknown"
        self.header_updates = 0
        self.reproject_sources: list[str] = []
        self.attention_announcements: list[FleetRowsProjection] = []

    def _update_agents_header(self) -> None:
        self.header_updates += 1

    def _reproject_agents_from_current_mode(
        self,
        *,
        source: str,
        selected_identity: object | None = None,
    ) -> None:
        del selected_identity
        self.reproject_sources.append(source)
        local_base = list(self._agents_local_with_children)
        self._agents_with_children = self._agents_source_for_current_mode(local_base)
        self._agents = list(self._agents_with_children)

    def _announce_remote_attention(self, projection: FleetRowsProjection) -> None:
        self.attention_announcements.append(projection)

    def notify(self, *_args: object, **_kwargs: object) -> None:
        pass


def test_fleet_status_text_labels_partial_and_zero_results() -> None:
    app = _FleetRefreshHarness(mode="fleet")
    app._agents_fleet_loading = False
    app._agents_fleet_projection = FleetRowsProjection(
        configured_host_count=2,
        partial=True,
        counts={"fleet": 0},
    )

    assert app._fleet_status_text() == "2 machines · partial · 0 results"

    app.current_agents_subtab = "focus"
    assert app._fleet_status_text() == "2 machines · partial"


@pytest.mark.asyncio
async def test_hidden_fleet_refresh_skips_catalog_hydration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = fleet_summary(agent_id="agent-a", needs_attention=True)
    response = fleet_host_response(
        summaries=(summary,),
        diagnostics=(
            {
                "code": "cached_projection",
                "severity": "info",
                "message": "offline fixture response",
            },
        ),
    )
    attention_response = fleet_attention_response(
        (
            {
                "kind": "question",
                "state": "pending",
                "logical_key": summary["logical_key"],
            },
        )
    )
    facade = OfflineFleetFacade(
        summary_response=response,
        followed_response=response,
        catalog_response={"unexpected": "catalog hydration"},
        attention_response=attention_response,
    )
    app = _FleetRefreshHarness(mode="focus")

    monkeypatch.setattr(fleet_mod, "load_federation_config", fleet_config)
    monkeypatch.setattr(
        fleet_mod,
        "_load_reconciled_follow_snapshot",
        lambda: fleet_follow_snapshot(summary["logical_locator"]),
    )
    monkeypatch.setattr(fleet_mod, "build_federation_facade", lambda _config: facade)

    await app._run_agents_fleet_refresh(generation=1, source="apply")

    assert facade.calls == ["summary", "followed_batch", "attention"]
    assert "catalog" not in facade.calls
    assert [row.fleet_logical_key for row in app._agents_fleet_focus_rows] == [
        summary["logical_key"]
    ]
    assert app._agents[0].status == "QUESTION"
    assert app._agents_fleet_projection.diagnostics[0]["code"] == "cached_projection"
    assert app.reproject_sources == ["fleet_refresh"]


@pytest.mark.asyncio
async def test_zero_machine_config_refresh_performs_no_remote_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FleetRefreshHarness(mode="fleet")
    built_facades: list[FederationConfig] = []
    empty_config = FederationConfig(
        worker=FederationWorkerSettings(enabled=True),
        hosts=(),
    )

    def build_facade(config: FederationConfig) -> OfflineFleetFacade:
        built_facades.append(config)
        raise AssertionError("zero-machine refresh must not build a federation facade")

    monkeypatch.setattr(fleet_mod, "load_federation_config", lambda: empty_config)
    monkeypatch.setattr(
        fleet_mod,
        "_load_reconciled_follow_snapshot",
        lambda: FollowStoreSnapshot(
            schema_version=1,
            records=(),
            tombstones=(),
            path="/tmp/sase-fleet-follows.json",
        ),
    )
    monkeypatch.setattr(fleet_mod, "build_federation_facade", build_facade)

    await app._run_agents_fleet_refresh(generation=1, source="manual")

    assert built_facades == []
    assert app.current_agents_subtab == "focus"
    assert app._agents_fleet_available is False
    assert app._agents_fleet_rows == []
    assert app._agents_fleet_focus_rows == []
    assert app._agents == []
    assert app.reproject_sources == ["fleet_refresh"]
