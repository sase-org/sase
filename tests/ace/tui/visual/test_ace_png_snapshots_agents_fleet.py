"""ACE TUI PNG visual snapshots for Agents-tab Fleet surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents import _fleet as fleet_mod
from sase.ace.tui.models.fleet_agents import FleetRowsProjection
from sase.dispatch.federation import FederationConfig, FederationWorkerSettings
from sase.dispatch.follow_store import FollowStoreSnapshot
from tests.ace.tui.fleet_fixture import (
    OfflineFleetFacade,
    fleet_attention_response,
    fleet_config,
    fleet_follow_snapshot,
    fleet_host_response,
    fleet_installation_id,
    fleet_logical_locator,
    fleet_summary,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    agents,
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _empty_follow_snapshot() -> FollowStoreSnapshot:
    return FollowStoreSnapshot(
        schema_version=1,
        records=(),
        tombstones=(),
        path="/tmp/sase-fleet-follows.json",
    )


def _patch_fleet_refresh(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: FederationConfig | None = None,
    follow_snapshot: FollowStoreSnapshot | None = None,
    facade: OfflineFleetFacade | None = None,
    config_error: str | None = None,
) -> None:
    if config_error is None:
        monkeypatch.setattr(
            fleet_mod,
            "load_federation_config",
            lambda: config if config is not None else fleet_config(),
        )
    else:

        def _raise_config_error() -> FederationConfig:
            raise fleet_mod.FederationConfigError(config_error)

        monkeypatch.setattr(fleet_mod, "load_federation_config", _raise_config_error)
    monkeypatch.setattr(
        fleet_mod,
        "_load_reconciled_follow_snapshot",
        lambda: (
            follow_snapshot if follow_snapshot is not None else _empty_follow_snapshot()
        ),
    )
    monkeypatch.setattr(
        fleet_mod,
        "build_federation_facade",
        lambda _config: facade if facade is not None else OfflineFleetFacade(),
    )


async def _open_agents(page: AcePage) -> None:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    await page.wait_for(lambda _s: not page.app._agents_fleet_loading)


async def _show_fleet(page: AcePage, *, expected_count: int) -> None:
    page.app._set_agents_subtab("fleet")
    await page.wait_for(
        lambda _s: (
            page.app.current_agents_subtab == "fleet"
            and not page.app._agents_fleet_loading
        )
    )
    await page.expect_state("agent_count", expected_count)


def _fleet_visual_responses() -> tuple[
    Mapping[str, Any],
    Mapping[str, Any],
    FollowStoreSnapshot,
]:
    apollo_installation = fleet_installation_id("a")
    mac_installation = fleet_installation_id("b")
    followed_locator = fleet_logical_locator(
        installation_id=apollo_installation,
        agent_id="remote-auth",
    )
    followed = fleet_summary(
        installation_id=apollo_installation,
        agent_id="remote-auth",
        run_id="run-auth",
        patch_name="remote-auth-fix",
        agent_name="dispatch.auth",
        bounded_intent="repair remote dispatch auth race",
        status="running",
        revision=7,
    )
    queued = fleet_summary(
        installation_id=apollo_installation,
        agent_id="queue-window",
        run_id="run-queue",
        patch_name="queue-window",
        agent_name="dispatch.queue",
        bounded_intent="review queued launch window",
        status="queued",
        revision=2,
    )
    cached = fleet_summary(
        installation_id=mac_installation,
        agent_id="cached-ci",
        run_id="run-ci",
        patch_name="ci-watch",
        agent_name="mac.ci",
        bounded_intent="cached result from offline host",
        status="running",
        revision=4,
    )
    cached["liveness"]["connection_health"] = "offline"
    summary_response = {
        "schema_version": 1,
        "configured_hosts": 2,
        "counts": {"hosts": 2, "total": 3, "running": 2},
        "partial": True,
        "diagnostics": (
            {
                "code": "host_partial",
                "severity": "warning",
                "message": "mac returned cached rows only",
            },
        ),
        "hosts": [
            fleet_host_response(
                alias="apollo",
                installation_id=apollo_installation,
                summaries=(followed, queued),
                freshness="fresh",
                connection_health="online",
            )["hosts"][0],
            fleet_host_response(
                alias="mac",
                installation_id=mac_installation,
                summaries=(cached,),
                freshness="cached 12m",
                connection_health="offline",
                observed_at_unix=1_783_076_400.0,
            )["hosts"][0],
        ],
    }
    attention_response = fleet_attention_response(
        (
            {
                "kind": "question",
                "state": "pending",
                "logical_key": followed["logical_key"],
            },
        ),
        alias="apollo",
    )
    return (
        summary_response,
        attention_response,
        fleet_follow_snapshot(followed_locator),
    )


async def test_agents_fleet_followed_partial_offline_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_response, attention_response, follow_snapshot = _fleet_visual_responses()
    facade = OfflineFleetFacade(
        summary_response=summary_response,
        followed_response=summary_response,
        catalog_response=summary_response,
        attention_response=attention_response,
    )
    patch_startup_loaders(monkeypatch, agents=agents())
    _patch_fleet_refresh(
        monkeypatch,
        follow_snapshot=follow_snapshot,
        facade=facade,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        await _show_fleet(page, expected_count=3)
        await wait_for_visual_idle(page)

        assert facade.calls[:3] == ["summary", "followed_batch", "attention"]
        assert "catalog" in facade.calls
        assert_page_svg_contains(page, "★apollo")
        assert_page_svg_contains(page, "☆apollo")
        assert_page_svg_contains(page, "☆mac")
        assert_page_svg_contains(page, "partial")
        assert_page_svg_contains(page, "offline")
        assert_page_svg_contains(page, "cached 12m")
        ace_png_visual.assert_page_png(
            page,
            "agents_fleet_followed_partial_offline_120x40",
            title="ACE agents Fleet followed partial offline",
        )


async def test_agents_fleet_keyboard_focus_and_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_response, attention_response, follow_snapshot = _fleet_visual_responses()
    facade = OfflineFleetFacade(
        summary_response=summary_response,
        followed_response=summary_response,
        catalog_response=summary_response,
        attention_response=attention_response,
    )
    patch_startup_loaders(monkeypatch, agents=agents())
    _patch_fleet_refresh(
        monkeypatch,
        follow_snapshot=follow_snapshot,
        facade=facade,
    )

    async with AcePage(query='"visual"', patches=patches(), size=(82, 28)) as page:
        await _open_agents(page)
        await _show_fleet(page, expected_count=3)
        page.app.action_view_agent_in_focus()
        await page.wait_for(
            lambda _s: (
                page.app.current_agents_subtab == "focus"
                and any(row.fleet_followed for row in page.app._agents)
            )
        )
        await wait_for_visual_idle(page)

        assert page.app.current_agents_subtab == "focus"
        assert_page_svg_contains(page, "★apollo")
        assert_page_svg_contains(page, "Focus")
        ace_png_visual.assert_page_png(
            page,
            "agents_fleet_keyboard_focus_narrow_82x28",
            title="ACE agents Fleet keyboard focus narrow",
        )


async def test_agents_fleet_state_strip_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zero_response = fleet_host_response(
        summaries=(),
        counts={"total": 0, "running": 0},
    )
    facade = OfflineFleetFacade(
        summary_response=zero_response,
        catalog_response=zero_response,
    )
    patch_startup_loaders(monkeypatch, agents=[])
    _patch_fleet_refresh(monkeypatch, facade=facade)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        await _show_fleet(page, expected_count=0)
        await wait_for_visual_idle(page)

        assert not page.query_one_widget("#agents-view").has_class("-onboarding-active")
        assert_page_svg_contains(page, "0 results")
        ace_png_visual.assert_page_png(
            page,
            "agents_fleet_loaded_zero_results_120x40",
            title="ACE agents Fleet loaded zero results",
        )

        page.app._agents_fleet_loading = True
        page.app._update_agents_header()
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "loading fleet")
        ace_png_visual.assert_page_png(
            page,
            "agents_fleet_loading_120x40",
            title="ACE agents Fleet loading",
        )

        page.app._agents_fleet_loading = False
        page.app._apply_fleet_error(
            "fleet config unavailable",
            generation=page.app._agents_fleet_refresh_generation,
        )
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "fleet config unavailable")
        ace_png_visual.assert_page_png(
            page,
            "agents_fleet_unavailable_120x40",
            title="ACE agents Fleet unavailable",
        )


async def test_agents_fleet_empty_without_enrolled_machine_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty_config = FederationConfig(
        worker=FederationWorkerSettings(enabled=True),
        hosts=(),
    )
    patch_startup_loaders(monkeypatch, agents=[])
    _patch_fleet_refresh(monkeypatch, config=empty_config)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "agents")
        await page.wait_for(lambda _s: not page.app._agents_fleet_loading)
        await page.expect_state("agent_count", 0)
        await wait_for_visual_idle(page)

        assert page.app.current_agents_subtab == "focus"
        assert not page.app._agents_fleet_available
        assert_page_svg_contains(page, "Every agent you launch")
        ace_png_visual.assert_page_png(
            page,
            "agents_fleet_empty_no_machine_120x40",
            title="ACE agents Fleet empty no machine",
        )
