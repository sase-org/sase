"""Downstream freshness contracts: polling, -r gating, clocks, capacity, archive."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from rich.text import Text

from sase.ace.tui.actions.agents._archive_controller import (
    note_inbox_applied_for_archive,
    schedule_archive_idle_tick,
)
from sase.ace.tui.actions.event_refresh._auto_refresh_capacity_signatures import (
    CAPACITY_REPORT_POLL_SECONDS,
)
from sase.ace.tui.actions.event_refresh._surface_tokens import SurfaceTokenSnapshot
from sase.ace.tui.relations.artifact_links import ArtifactLinksSnapshot
from sase.ace.tui.widgets.axe_info_panel import AxeInfoPanel
from sase.ace.tui.widgets.patch_info_panel import PatchInfoPanel
from tests.ace.tui._agent_archive_controller_helpers import (
    archive_tokens,
    complete_load,
    instrument,
    make_owner,
)
from tests.ace.tui._event_handlers_dirty_flags_helpers import (
    _FakeApp,
    _axe_kinded_snapshot,
    _completed_tokens,
    _surface_token_snapshot,
)
from tests.ace.tui._freshness_fixtures import (
    AGENTS_LOAD_MIN_INTERVAL_SECONDS,
    FULL_SANITY_REFRESH_SECONDS,
    FreshnessApp,
    LatencySample,
    isolate_freshness_home,
)
from tests.ace.tui._machine_capacity_report_feed_helpers import make_report
from tests.ace.tui._machine_capacity_report_feed_revalidation_tests import (
    _FakeClock,
    _installed_count,
    _run_tick,
    _stable_feed,
)

__all__ = [
    "test_archive_link_facet_change_applies_new_corpus",
    "test_broad_agents_refresh_stays_tab_gated",
    "test_capacity_hold_expiry_without_token_mutation",
    "test_disabled_auto_refresh_skips_clean_tick",
    "test_polling_fallback_reloads_on_token_drift",
    "test_process_death_without_token_mutation",
    "test_r_zero_keeps_watcher_dirty_without_broad_load",
    "test_service_transition_reloads_axe",
    "test_visible_clock_publishes_each_countdown_tick",
    "test_visible_clock_quiet_when_auto_refresh_disabled",
]


def _seed(app: _FakeApp, snapshot: Any) -> None:
    app._probed_surface_tokens = snapshot
    app._last_completed_surface_tokens = _completed_tokens(snapshot)


@pytest.mark.asyncio
async def test_polling_fallback_reloads_on_token_drift() -> None:
    """Watcher-off ticks still apply when consumed tokens drift."""
    app = FreshnessApp()
    assert app._watcher_active() is False
    snapshot = _axe_kinded_snapshot()
    _seed(app, snapshot)
    app.current_tab = "artifacts"
    drifted = _surface_token_snapshot(notifications=4, patches=4)
    app._probed_surface_tokens = SurfaceTokenSnapshot(
        agents=snapshot.agents,
        axe=snapshot.axe,
        notifications=drifted.notifications,
        patches=drifted.patches,
        procs=snapshot.procs,
        tool_runs=snapshot.tool_runs,
    )
    mutation = time.monotonic()
    await app._run_auto_refresh()
    visible = app.last_visible_mono()
    assert visible is not None
    sample = LatencySample(
        case="polling_fallback",
        mutation_mono=mutation,
        callback_mono=None,
        visible_mono=visible,
        cadence_s=float(app.refresh_interval),
    )
    assert "notifications" in app.refresh_calls
    assert "patches" in app.refresh_calls
    assert sample.event_to_visible_s is not None
    assert sample.event_to_visible_s < 1.0


@pytest.mark.asyncio
async def test_disabled_auto_refresh_skips_clean_tick() -> None:
    """``-r 0`` does not start work on an unchanged stray tick."""
    app = FreshnessApp()
    app.refresh_interval = 0
    app._fs_watcher = object()
    _seed(app, _axe_kinded_snapshot())
    await app._run_auto_refresh()
    assert app.refresh_calls == []
    assert app.axe_load_kwargs == []


def test_r_zero_keeps_watcher_dirty_without_broad_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``-r 0`` starts no timer; watcher still marks Agents dirty without a load."""
    home = isolate_freshness_home(tmp_path, monkeypatch)
    app = FreshnessApp(sdd_beads_dir=home.beads_dir)
    app.refresh_interval = 0
    app._fs_watcher = object()
    app.current_tab = "agents"
    app._on_artifact_change((home.agent_dir / "agent_meta.json",))
    assert app._dirty_agents is True
    assert "agents" not in app.refresh_calls
    assert app.refresh_interval == 0


@pytest.mark.asyncio
async def test_broad_agents_refresh_stays_tab_gated() -> None:
    app = FreshnessApp()
    app._fs_watcher = object()
    app.current_tab = "services"
    app._dirty_agents = True
    app._last_agents_load_mono = 0.0
    _seed(app, _axe_kinded_snapshot())
    await app._run_auto_refresh()
    assert "agents" not in app.refresh_calls
    assert app._dirty_agents is True
    app.current_tab = "agents"
    app._last_agents_load_mono = time.monotonic() - AGENTS_LOAD_MIN_INTERVAL_SECONDS
    await app._run_auto_refresh()
    assert "agents" in app.refresh_calls


def test_visible_clock_publishes_each_countdown_tick() -> None:
    panel = AxeInfoPanel()
    published: list[tuple[float, str]] = []

    def _update(text: Text) -> None:
        published.append((time.monotonic(), text.plain))

    with patch.object(panel, "update", _update):
        start = time.monotonic()
        panel.update_countdown(10, 10)
        for remaining in (9, 8, 7):
            panel.update_countdown(remaining, 10)
    stamps = [stamp - start for stamp, _ in published]
    assert len(published) == 4
    assert published[-1][1].endswith("(auto-refresh in 7s)")
    assert stamps[-1] < 1.0
    patch_panel = PatchInfoPanel()
    patch_published: list[str] = []
    with patch.object(
        patch_panel, "update", lambda text: patch_published.append(text.plain)
    ):
        patch_panel.update_countdown(5, 10)
        patch_panel.update_countdown(4, 10)
    assert len(patch_published) == 2


def test_visible_clock_quiet_when_auto_refresh_disabled() -> None:
    panel = AxeInfoPanel()
    published: list[str] = []
    with patch.object(panel, "update", lambda text: published.append(text.plain)):
        panel.update_countdown(0, 0)
        settled = len(published)
        panel.update_countdown(0, 0)
        panel.update_countdown(0, 0)
    assert len(published) == settled


@pytest.mark.asyncio
async def test_capacity_hold_expiry_without_token_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock(monkeypatch)
    holds: list[dict[str, object]] = [{"id": "hold-1"}]
    reports = {"occupied": 5.0}

    def source() -> object:
        return make_report(occupied=reports["occupied"])

    app = _stable_feed(source, holds=holds)
    mutation = time.monotonic()
    await _run_tick(app)
    clock.advance(CAPACITY_REPORT_POLL_SECONDS)
    holds.clear()
    reports["occupied"] = 4.0
    await _run_tick(app)
    visible = time.monotonic()
    assert app._feed_counters["builds"] == 2  # type: ignore[attr-defined]
    assert _installed_count(app) == 2
    sample = LatencySample(
        case="capacity_hold_expiry",
        mutation_mono=mutation,
        callback_mono=None,
        visible_mono=visible,
        cadence_s=CAPACITY_REPORT_POLL_SECONDS,
    )
    assert sample.event_to_visible_s is not None
    assert app._machine_capacity_report.occupied_capacity == 4.0


@pytest.mark.asyncio
async def test_process_death_without_token_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock(monkeypatch)
    alive: dict[str, bool] = {"/tmp/project/artifacts/worker": True}
    reports = {"occupied": 5.0}

    def source() -> object:
        return make_report(occupied=reports["occupied"])

    app = _stable_feed(source)
    app._machine_capacity_liveness_source = lambda: dict(alive)  # type: ignore[attr-defined]
    mutation = time.monotonic()
    await _run_tick(app)
    clock.advance(CAPACITY_REPORT_POLL_SECONDS)
    alive["/tmp/project/artifacts/worker"] = False
    reports["occupied"] = 4.0
    await _run_tick(app)
    visible = time.monotonic()
    assert app._feed_counters["builds"] == 2  # type: ignore[attr-defined]
    assert _installed_count(app) == 2
    sample = LatencySample(
        case="capacity_process_death",
        mutation_mono=mutation,
        callback_mono=None,
        visible_mono=visible,
        cadence_s=CAPACITY_REPORT_POLL_SECONDS,
    )
    assert sample.event_to_visible_s is not None
    assert app._machine_capacity_report.occupied_capacity == 4.0


@pytest.mark.asyncio
async def test_service_transition_reloads_axe() -> None:
    app = FreshnessApp()
    app.current_tab = "services"
    app._axe_services_visited = True
    app._axe_first_load_done = True
    _seed(app, _axe_kinded_snapshot())
    app._probed_surface_tokens = _axe_kinded_snapshot(pid=9, status=9, service=9)
    mutation = time.monotonic()
    await app._run_auto_refresh()
    visible = app.last_visible_mono()
    assert "axe" in app.refresh_calls
    assert visible is not None
    sample = LatencySample(
        case="service_transition",
        mutation_mono=mutation,
        callback_mono=None,
        visible_mono=visible,
        cadence_s=float(app.refresh_interval),
    )
    assert sample.event_to_visible_s is not None
    assert sample.event_to_visible_s < 1.0


@pytest.mark.asyncio
async def test_archive_link_facet_change_applies_new_corpus() -> None:
    owner = make_owner()
    spawn, corpus_lookups, facet_calls = instrument(owner)
    old_facets = {
        "worker": {"relations": ("uses",), "artifacts": ("file:old",), "count": 1}
    }
    new_facets = {
        "worker": {"relations": ("uses",), "artifacts": ("file:new",), "count": 1}
    }
    facet_results = [old_facets, new_facets]
    owner._archive_load_facets = lambda: (
        facet_calls.append("facets") or facet_results.pop(0)
    )
    original = ArtifactLinksSnapshot(
        rows=({"source_ref": "agent:worker", "target_ref": "file:old"},),
        source_key=(("proj", 1, 2),),
    )
    updated = ArtifactLinksSnapshot(
        rows=({"source_ref": "agent:worker", "target_ref": "file:new"},),
        source_key=(("proj", 9, 9),),
    )
    current_links = [original]
    owner._archive_load_link_snapshot = lambda: current_links[0]
    owner._archive_catalog_link_identity = lambda: "catalog-v1"
    note_inbox_applied_for_archive(owner, load_state=complete_load())
    await spawn.drain()
    first_corpus = owner._agents_archive_controller.corpus
    second_corpus = type(first_corpus)()

    def _get_changed_corpus(**kwargs: Any) -> SimpleNamespace:
        corpus_lookups.append(kwargs)
        return SimpleNamespace(
            corpus=second_corpus,
            profile=SimpleNamespace(digest="profile-1"),
        )

    owner._archive_get_corpus = _get_changed_corpus
    owner._archive_probe_tokens = lambda: replace(
        archive_tokens(), link_signature=(("proj", 9, 9),)
    )
    current_links[0] = updated
    mutation = time.monotonic()
    schedule_archive_idle_tick(owner)
    await spawn.drain()
    visible = time.monotonic()
    assert owner._agents_archive_controller.corpus is second_corpus
    assert owner._agents_archive_controller.link_facets == new_facets
    sample = LatencySample(
        case="archive_link_change",
        mutation_mono=mutation,
        callback_mono=None,
        visible_mono=visible,
        cadence_s=float(FULL_SANITY_REFRESH_SECONDS),
    )
    assert sample.event_to_visible_s is not None
    assert sample.event_to_visible_s < 1.0
