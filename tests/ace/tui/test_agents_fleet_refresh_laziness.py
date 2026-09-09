"""TUI-level Fleet refresh laziness regressions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _fleet as fleet_mod
from sase.ace.tui.actions.agents._fleet import AgentFleetMixin
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.fleet_agents import FleetRowsProjection
from sase.dispatch.federation import FederationConfig, FederationWorkerSettings
from sase.dispatch.follow_store import FollowStoreMutationOutcome, FollowStoreSnapshot
from tests.ace.tui.fleet_fixture import (
    OfflineFleetFacade,
    fleet_attention_response,
    fleet_config,
    fleet_follow_snapshot,
    fleet_host_response,
    fleet_logical_locator,
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


@pytest.mark.asyncio
async def test_empty_follow_snapshot_skips_hydration_and_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = fleet_summary(agent_id="agent-a")
    response = fleet_host_response(summaries=(summary,))
    facade = OfflineFleetFacade(summary_response=response, catalog_response=response)
    app = _FleetRefreshHarness(mode="focus")

    def fail_reconcile(**_kwargs: object) -> object:
        raise AssertionError("empty follow store must not reconcile promotions")

    monkeypatch.setattr(fleet_mod, "load_federation_config", lambda: fleet_config())
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
    monkeypatch.setattr(fleet_mod, "reconcile_follow_store", fail_reconcile)
    monkeypatch.setattr(fleet_mod, "build_federation_facade", lambda _config: facade)

    await app._run_agents_fleet_refresh(generation=1, source="apply")

    assert facade.calls == ["summary"]
    assert app._agents_fleet_focus_rows == []


@pytest.mark.asyncio
async def test_fleet_catalog_refresh_requests_legal_pages_and_logical_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = fleet_summary(agent_id="agent-a")
    page_one = fleet_host_response(summaries=(summary,))
    page_one["hosts"][0]["payload"] = {
        "page": {
            "rows": [summary],
            "next_cursor": "off:100",
            "has_more": True,
        },
        "counts": {"running": 1},
    }
    page_two_summary = fleet_summary(agent_id="agent-b", status="done")
    page_two = fleet_host_response(summaries=(page_two_summary,))
    page_two["hosts"][0]["payload"] = {
        "page": {
            "rows": [page_two_summary],
            "next_cursor": None,
            "has_more": False,
        },
        "counts": {"running": 1},
    }

    class _PagingFacade(OfflineFleetFacade):
        async def catalog(
            self,
            query: dict[str, Any],
            *,
            cache_only: bool = False,
            timeout_seconds: float | None = None,
        ) -> dict[str, Any]:
            self.calls.append("catalog")
            self.requests.append(
                {
                    "operation": "catalog",
                    "request": dict(query),
                    "cache_only": cache_only,
                    "timeout_seconds": timeout_seconds,
                }
            )
            if query.get("cursor") == "off:100":
                return dict(page_two)
            return dict(page_one)

        async def catalog_hosts(
            self,
            queries: Iterable[Mapping[str, Any]],
            *,
            cache_only: bool = False,
            timeout_seconds: float | None = None,
        ) -> dict[str, Any]:
            self.calls.append("catalog_hosts")
            request = [dict(query) for query in queries]
            self.requests.append(
                {
                    "operation": "catalog_hosts",
                    "request": request,
                    "cache_only": cache_only,
                    "timeout_seconds": timeout_seconds,
                }
            )
            query = request[0]["query"] if request else {}
            if query.get("cursor") == "off:100":
                return dict(page_two)
            return dict(page_one)

    facade = _PagingFacade(
        summary_response=page_one,
        followed_response=page_one,
        attention_response=fleet_attention_response(()),
    )
    app = _FleetRefreshHarness(mode="fleet")
    monkeypatch.setattr(fleet_mod, "load_federation_config", fleet_config)
    monkeypatch.setattr(
        fleet_mod,
        "_load_reconciled_follow_snapshot",
        lambda: fleet_follow_snapshot(summary["logical_locator"]),
    )
    monkeypatch.setattr(fleet_mod, "build_federation_facade", lambda _config: facade)

    await app._run_agents_fleet_refresh(generation=1, source="manual")

    catalog_requests = [
        item["request"] for item in facade.requests if item["operation"] == "catalog"
    ]
    assert catalog_requests[0] == {
        "schema_version": 1,
        "limit": 100,
        "include_terminal": True,
    }
    catalog_host_requests = [
        item["request"]
        for item in facade.requests
        if item["operation"] == "catalog_hosts"
    ]
    assert catalog_host_requests == [
        [
            {
                "schema_version": 1,
                "installation_id": summary["logical_locator"]["project"]["origin"][
                    "installation_id"
                ],
                "query": {
                    "schema_version": 1,
                    "limit": 100,
                    "include_terminal": True,
                    "cursor": "off:100",
                },
            }
        ]
    ]
    followed_request = next(
        item["request"]
        for item in facade.requests
        if item["operation"] == "followed_batch"
    )
    assert "logical_keys" in followed_request
    assert "logical_locators" not in followed_request
    assert {row.fleet_logical_key for row in app._agents_fleet_rows} == {
        summary["logical_key"],
        page_two_summary["logical_key"],
    }


@pytest.mark.asyncio
async def test_followed_batch_promotes_singleton_before_attention_and_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation_id = "sase_inst_v1_" + "d" * 64
    singleton = fleet_logical_locator(
        installation_id=installation_id,
        agent_id="worker",
        family_id=None,
    )
    family = fleet_logical_locator(
        installation_id=installation_id,
        agent_id="worker",
        family_id="family-1",
    )
    summary = fleet_summary(installation_id=installation_id, agent_id="worker")
    followed = fleet_host_response(
        installation_id=installation_id,
        summaries=(summary,),
    )
    family_record = {
        **fleet_follow_snapshot(family).records[0],
        "logical_key": "family-logical-key",
    }
    family_snapshot = FollowStoreSnapshot(
        schema_version=1,
        records=(family_record,),
        tombstones=(),
        path="/tmp/sase-fleet-follows.json",
    )
    facade = OfflineFleetFacade(
        summary_response=followed,
        followed_response=followed,
        attention_response=fleet_attention_response(()),
    )
    app = _FleetRefreshHarness(mode="focus")
    promotions_seen: list[dict[str, Any]] = []

    def reconcile(*, promotions: object = (), **_kwargs: object) -> object:
        promotions_seen.extend(item for item in promotions if isinstance(item, dict))
        return FollowStoreMutationOutcome(
            changed=True,
            snapshot=family_snapshot,
        )

    monkeypatch.setattr(fleet_mod, "load_federation_config", lambda: fleet_config())
    monkeypatch.setattr(
        fleet_mod,
        "_load_reconciled_follow_snapshot",
        lambda: fleet_follow_snapshot(singleton),
    )
    monkeypatch.setattr(fleet_mod, "reconcile_follow_store", reconcile)
    monkeypatch.setattr(fleet_mod, "build_federation_facade", lambda _config: facade)

    await app._run_agents_fleet_refresh(generation=1, source="apply")

    assert promotions_seen == [
        {
            "schema_version": 1,
            "from": singleton,
            "to": family,
        }
    ]
    assert [request["operation"] for request in facade.requests] == [
        "summary",
        "followed_batch",
        "attention",
    ]
    attention_request = facade.requests[-1]["request"]
    assert attention_request == {
        "schema_version": 1,
        "logical_keys": ["family-logical-key"],
    }
    assert [row.fleet_logical_locator for row in app._agents_fleet_focus_rows] == [
        family
    ]


@pytest.mark.asyncio
async def test_followed_batch_promotion_preserves_tombstoned_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation_id = "sase_inst_v1_" + "e" * 64
    singleton = fleet_logical_locator(
        installation_id=installation_id,
        agent_id="worker",
        family_id=None,
    )
    family = fleet_logical_locator(
        installation_id=installation_id,
        agent_id="worker",
        family_id="family-1",
    )
    summary = fleet_summary(installation_id=installation_id, agent_id="worker")
    followed = fleet_host_response(
        installation_id=installation_id,
        summaries=(summary,),
    )
    tombstone = {
        "schema_version": 1,
        "logical_locator": family,
        "logical_key": "family-logical-key",
        "unfollowed_at_unix": 1_800_000_010.0,
    }
    tombstoned_snapshot = FollowStoreSnapshot(
        schema_version=1,
        records=(),
        tombstones=(tombstone,),
        path="/tmp/sase-fleet-follows.json",
    )
    facade = OfflineFleetFacade(
        summary_response=followed,
        followed_response=followed,
    )
    app = _FleetRefreshHarness(mode="focus")

    def reconcile(*, promotions: object = (), **_kwargs: object) -> object:
        assert tuple(promotions) == (
            {
                "schema_version": 1,
                "from": singleton,
                "to": family,
            },
        )
        return FollowStoreMutationOutcome(
            changed=True,
            snapshot=tombstoned_snapshot,
        )

    monkeypatch.setattr(fleet_mod, "load_federation_config", lambda: fleet_config())
    monkeypatch.setattr(
        fleet_mod,
        "_load_reconciled_follow_snapshot",
        lambda: fleet_follow_snapshot(singleton),
    )
    monkeypatch.setattr(fleet_mod, "reconcile_follow_store", reconcile)
    monkeypatch.setattr(fleet_mod, "build_federation_facade", lambda _config: facade)

    await app._run_agents_fleet_refresh(generation=1, source="apply")

    assert app._agents_fleet_focus_rows == []
    assert tombstoned_snapshot.tombstones == (tombstone,)
