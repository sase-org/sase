"""sase's TUI PNG visual snapshots for Agents-tab Fleet surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import json

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents import _fleet as fleet_mod
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from sase.core.rust import require_rust_binding
from sase.dispatch.federation import FederationConfig, FederationWorkerSettings
from tests.ace.tui.fleet_fixture import (
    OfflineFleetFacade,
    fleet_config,
    fleet_follow_snapshot,
    fleet_host_response,
    fleet_installation_id,
    fleet_multi_host_response,
    fleet_summary,
)
from tests.ace.tui.owner_roster_fixture import write_owner_roster_fixture
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    assert_page_svg_styled_text_absent,
    pin_agents_visual_now,
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


def _patch_fleet_refresh(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: FederationConfig | None = None,
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
        "build_federation_facade",
        lambda _config: facade if facade is not None else OfflineFleetFacade(),
    )
    monkeypatch.setattr(
        fleet_mod,
        "_load_reconciled_follow_snapshot",
        lambda: fleet_follow_snapshot(),
    )


def _apply_fleet_visual_response(
    page: AcePage,
    response: Mapping[str, Any],
    *,
    config: FederationConfig | None = None,
) -> None:
    page.app._agent_search_query = ""
    page.app._agent_query_cache = None
    page.app._agents_live_query_facade = None
    projection = project_fleet_agents(
        summary_response=response,
        catalog_response=response,
        follow_snapshot=fleet_follow_snapshot(),
        local_agent_count=len(page.app._agents_local_with_children),
    )
    page.app._agents_fleet_refresh_generation += 1
    generation = page.app._agents_fleet_refresh_generation
    page.app._apply_fleet_projection(
        projection,
        config=config if config is not None else fleet_config(),
        generation=generation,
        source="visual_fixture",
    )
    fleet_rows = list(projection.fleet_rows)
    if fleet_rows:
        page.app._agents_with_children = fleet_rows
        page.app._agents = fleet_rows
        page.app.current_idx = 0
        page.app._refresh_agents_display(list_changed=True)
        page.app._update_agents_header()
    page.app._agents_fleet_loading = False


async def _open_agents(
    page: AcePage,
    *,
    fleet_response: Mapping[str, Any] | None = None,
    config: FederationConfig | None = None,
) -> None:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    if fleet_response is not None:
        _apply_fleet_visual_response(page, fleet_response, config=config)
    else:
        page.app._schedule_agents_fleet_refresh(source="visual_fixture", force=True)
    await page.wait_for(lambda _s: not page.app._agents_fleet_loading)


async def _show_fleet(page: AcePage) -> None:
    await page.wait_for(
        lambda _s: (
            page.app.current_agents_subtab == "focus"
            and not page.app._agents_fleet_loading
        )
    )
    await page.wait_for(
        lambda _s: any(
            bool(getattr(agent, "fleet_origin_alias", None))
            for agent in page.app._agents_fleet_rows
        )
    )


def _fleet_visual_responses() -> Mapping[str, Any]:
    apollo_installation = fleet_installation_id("a")
    mac_installation = fleet_installation_id("b")
    followed = fleet_summary(
        installation_id=apollo_installation,
        agent_id="remote-auth",
        run_id="run-auth",
        patch_name="remote-auth-fix",
        agent_name="dispatch.auth",
        bounded_intent="visual repair remote dispatch auth race",
        status="running",
        revision=7,
    )
    queued = fleet_summary(
        installation_id=apollo_installation,
        agent_id="queue-window",
        run_id="run-queue",
        patch_name="queue-window",
        agent_name="dispatch.queue",
        bounded_intent="visual review queued launch window",
        status="queued",
        revision=2,
    )
    cached = fleet_summary(
        installation_id=mac_installation,
        agent_id="cached-ci",
        run_id="run-ci",
        patch_name="ci-watch",
        agent_name="mac.ci",
        bounded_intent="visual cached result from offline host",
        status="running",
        revision=4,
    )
    cached["connection_health"] = "offline"
    cached["freshness"] = "stale"
    mac_host = fleet_host_response(
        alias="mac",
        installation_id=mac_installation,
        summaries=(cached,),
        freshness="cached 12m",
        connection_health="offline",
        observed_at_unix=1_783_076_400.0,
    )["hosts"][0]
    # Viewer freshness classifies cached copies from age_seconds; without
    # it the row renders as "unknown" instead of the fixture's stale cache.
    mac_host["cached"] = True
    mac_host["age_seconds"] = 720.0
    summary_response = fleet_multi_host_response(
        fleet_host_response(
            alias="apollo",
            installation_id=apollo_installation,
            summaries=(followed, queued),
            freshness="fresh",
            connection_health="online",
        )["hosts"][0],
        mac_host,
        configured_hosts=2,
        partial=True,
        diagnostics=(
            {
                "schema_version": 1,
                "code": "host_partial",
                "severity": "warning",
                "message": "mac returned cached rows only",
            },
        ),
    )
    return summary_response


async def test_agents_fleet_followed_partial_offline_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_response = _fleet_visual_responses()
    facade = OfflineFleetFacade(
        summary_response=summary_response,
        catalog_response=summary_response,
    )
    patch_startup_loaders(monkeypatch, agents=agents())
    _patch_fleet_refresh(monkeypatch, facade=facade)

    async with AcePage(patches=patches()) as page:
        await _open_agents(page, fleet_response=summary_response)
        await _show_fleet(page)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "apollo")
        assert_page_svg_contains(page, "mac")
        assert_page_svg_styled_text_absent(page, "here visual-plan")
        assert_page_svg_contains(page, "2 machine issues")
        assert_page_svg_contains(page, "offline")
        assert_page_svg_contains(page, "stale")
        ace_png_visual.assert_page_png(
            page,
            "agents_fleet_followed_partial_offline_120x40",
            title="ACE agents Fleet followed partial offline",
        )


async def test_agents_fleet_keyboard_focus_and_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_response = _fleet_visual_responses()
    facade = OfflineFleetFacade(
        summary_response=summary_response,
        catalog_response=summary_response,
    )
    patch_startup_loaders(monkeypatch, agents=agents())
    _patch_fleet_refresh(monkeypatch, facade=facade)

    async with AcePage(patches=patches(), size=(82, 28)) as page:
        await _open_agents(page, fleet_response=summary_response)
        await _show_fleet(page)
        await wait_for_visual_idle(page)

        assert page.app.current_agents_subtab == "focus"
        assert_page_svg_contains(page, "apollo")
        assert_page_svg_contains(page, "mac")
        assert_page_svg_styled_text_absent(page, "here visual-plan")
        ace_png_visual.assert_page_png(
            page,
            "agents_fleet_keyboard_focus_narrow_82x28",
            title="ACE agents Fleet keyboard focus narrow",
        )


async def test_agents_fleet_state_strip_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zero_response = fleet_host_response(summaries=())
    facade = OfflineFleetFacade(
        summary_response=zero_response,
        catalog_response=zero_response,
    )
    patch_startup_loaders(monkeypatch, agents=[])
    _patch_fleet_refresh(monkeypatch, facade=facade)

    async with AcePage(patches=patches()) as page:
        await _open_agents(page, fleet_response=zero_response)
        await page.expect_state("agent_count", 0)
        await wait_for_visual_idle(page)

        assert not page.query_one_widget("#agents-view").has_class("-onboarding-active")
        assert page.query_one_widget("#agents-header").has_class("hidden")
        assert_page_svg_styled_text_absent(page, "here: athena")
        ace_png_visual.assert_page_png(
            page,
            "agents_fleet_loaded_zero_results_120x40",
            title="ACE agents Fleet loaded zero results",
        )

        page.app._agents_fleet_loading = False
        page.app._apply_fleet_error(
            "fleet config unavailable",
            generation=page.app._agents_fleet_refresh_generation,
        )
        await wait_for_visual_idle(page)
        assert not page.query_one_widget("#agents-header").has_class("hidden")
        assert_page_svg_contains(page, "fleet config unavailable")
        assert_page_svg_styled_text_absent(page, "here: athena")
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


_FLEET_TRIBE_NOW = datetime(2026, 9, 18, 12, 0, 0)


def _unix(moment: datetime) -> float:
    return moment.timestamp()


def _fleet_tribe_family_response() -> Mapping[str, Any]:
    installation = fleet_installation_id("a")
    started = _FLEET_TRIBE_NOW - timedelta(hours=3)
    run_started = _FLEET_TRIBE_NOW - timedelta(minutes=27)
    done_started = _FLEET_TRIBE_NOW - timedelta(hours=8)
    done_stopped = _FLEET_TRIBE_NOW - timedelta(hours=6)

    def summary(agent_id: str, run_id: str, status: str, **overrides: object) -> dict:
        payload: dict[str, object] = {
            "installation_id": installation,
            "project_id": "sase-main",
            "project_name": "SASE",
            "agent_id": agent_id,
            "run_id": run_id,
            "agent_name": agent_id,
            "status": status,
            "tribe": "epic",
            "clan_tribe": "epic",
            "bounded_intent": "visual remote tribe family parity",
            "started_at_unix": _unix(started),
        }
        payload.update(overrides)
        return fleet_summary(**payload)  # type: ignore[arg-type]

    return fleet_host_response(
        alias="apollo",
        installation_id=installation,
        summaries=(
            summary(
                "remote-family",
                "fam-root",
                "TESTING",
                family_id="remote-family",
                family_role="root",
                run_started_at_unix=_unix(run_started),
            ),
            summary(
                "remote-family--code",
                "fam-code",
                "DONE",
                family_id="remote-family",
                family_role="member",
                parent_timestamp="fam-root",
                started_at_unix=_unix(started + timedelta(minutes=5)),
                stopped_at_unix=_unix(started + timedelta(hours=1)),
                current_instance=False,
            ),
            summary(
                "remote-family--mon",
                "fam-mon",
                "TESTING",
                family_id="remote-family",
                family_role="monitor",
                row_kind="monitor",
                parent_timestamp="fam-root",
                started_at_unix=_unix(run_started),
                occupied_runner_slot=False,
            ),
            summary(
                "remote-family--gate",
                "fam-gate",
                "RUNNING",
                family_id="remote-family",
                family_role="gate",
                row_kind="gate",
                parent_timestamp="fam-root",
                started_at_unix=_unix(run_started + timedelta(minutes=1)),
                occupied_runner_slot=False,
            ),
            summary(
                "remote-family--proc",
                "fam-proc",
                "DONE",
                family_id="remote-family",
                family_role="proc",
                row_kind="proc",
                parent_timestamp="fam-root",
                started_at_unix=_unix(started + timedelta(minutes=10)),
                stopped_at_unix=_unix(started + timedelta(minutes=20)),
                occupied_runner_slot=False,
                current_instance=False,
            ),
            summary(
                "done-family",
                "done-root",
                "TALE DONE",
                family_id="done-family",
                family_role="root",
                started_at_unix=_unix(done_started),
                stopped_at_unix=_unix(done_stopped),
                current_instance=False,
            ),
            summary(
                "done-family--plan",
                "done-plan",
                "TALE DONE",
                family_id="done-family",
                family_role="historical_shell",
                row_kind="historical_shell",
                parent_timestamp="done-root",
                started_at_unix=_unix(done_started),
                stopped_at_unix=_unix(done_started + timedelta(hours=1)),
                current_instance=False,
            ),
            summary(
                "done-family--code",
                "done-code",
                "TALE DONE",
                family_id="done-family",
                family_role="historical_shell",
                row_kind="historical_shell",
                parent_timestamp="done-root",
                started_at_unix=_unix(done_started + timedelta(hours=1)),
                stopped_at_unix=_unix(done_stopped),
                current_instance=False,
            ),
        ),
        observed_at_unix=_unix(_FLEET_TRIBE_NOW),
    )


async def test_agents_fleet_remote_tribe_families_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, _FLEET_TRIBE_NOW)
    response = _fleet_tribe_family_response()
    facade = OfflineFleetFacade(
        summary_response=response,
        catalog_response=response,
    )
    patch_startup_loaders(monkeypatch, agents=[])
    _patch_fleet_refresh(monkeypatch, facade=facade)

    async with AcePage(patches=patches()) as page:
        await _open_agents(page, fleet_response=response)
        await _show_fleet(page)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "apollo")
        assert_page_svg_contains(page, "@epic")
        assert_page_svg_contains(page, "remote-family")
        assert_page_svg_contains(page, "done-family")
        assert_page_svg_contains(page, "TESTING")
        assert_page_svg_contains(page, "TALE DONE")
        assert_page_svg_contains(page, "⚙")
        assert_page_svg_contains(page, "⋔")
        ace_png_visual.assert_page_png(
            page,
            "agents_fleet_remote_tribe_families_120x40",
            title="ACE agents Fleet remote tribe families",
        )


_PRODUCTION_FIXTURE_NOW = datetime(2026, 9, 20, 12, 0, 0)


def _production_fixture_response(home_root: Path) -> Mapping[str, Any]:
    """Real catalog payload assembled from the production-shaped owner fixture.

    Nothing here is hand-authored: the fixture is written in the persisted
    owner lifecycle shape and the summaries come out of the shared core's
    catalog assembly, exactly as a gateway would serve them.
    """
    fixture = write_owner_roster_fixture(home_root, now=_PRODUCTION_FIXTURE_NOW)
    # A fresh home would mint a random installation id, so pin the identity.
    installation = fleet_installation_id("a")
    (fixture.home / "installation_identity.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "installation_id": installation,
                "created_at_unix": _unix(_PRODUCTION_FIXTURE_NOW),
                "generation": 1,
            }
        ),
        encoding="utf-8",
    )
    payload = require_rust_binding("assemble_fleet_catalog")(
        {
            "sase_home": str(fixture.home),
            "agents_list_projection": True,
            "observations": fixture.observations,
            "now_unix": _unix(_PRODUCTION_FIXTURE_NOW),
        }
    )
    summaries = list(payload["summaries"])
    for summary in summaries:
        # The row revision hashes the record's absolute artifact path, which
        # differs per temporary directory; re-derive it from the stable key.
        revision = summary["row_revision"]
        digest = sha256(str(revision["logical_key"]).encode()).hexdigest()
        revision["revision"] = int(digest[:15], 16)
    return fleet_host_response(
        alias="apollo",
        installation_id=installation,
        summaries=summaries,
        observed_at_unix=_unix(_PRODUCTION_FIXTURE_NOW),
    )


async def test_agents_fleet_production_families_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, _PRODUCTION_FIXTURE_NOW)
    response = _production_fixture_response(tmp_path)
    facade = OfflineFleetFacade(
        summary_response=response,
        catalog_response=response,
    )
    patch_startup_loaders(monkeypatch, agents=[])
    _patch_fleet_refresh(monkeypatch, facade=facade)

    async with AcePage(patches=patches()) as page:
        await _open_agents(page, fleet_response=response)
        await _show_fleet(page)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "apollo")
        # The completed root-less plan-chain family renders as a family row
        # with its rich status, nested shells and the shell/neighbor chips.
        assert_page_svg_contains(page, "chain")
        assert_page_svg_contains(page, "TALE DONE")
        assert_page_svg_contains(page, "EPIC CREATED")
        ace_png_visual.assert_page_png(
            page,
            "agents_fleet_production_families_120x40",
            title="ACE agents Fleet production-derived families",
        )
