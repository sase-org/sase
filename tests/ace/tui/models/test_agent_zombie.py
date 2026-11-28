"""Tests for the cached Beads-pane zombie-plan projection."""

from __future__ import annotations

import pytest

from sase.ace.tui.models import _zombie_report_cache as zombie_cache
from sase.ace.tui.models import agent_zombie
from sase.bead import zombie as zombie_module
from sase.bead.zombie import ZombieReport
from sase.core.zombie_facade import ZombieEvaluationReport, ZombieVerdict


@pytest.fixture(autouse=True)
def _clear_zombie_cache():
    zombie_cache._ZOMBIE_REPORT_CACHE.clear()
    yield
    zombie_cache._ZOMBIE_REPORT_CACHE.clear()


def _row(plan_id: str, state: str = "zombie") -> ZombieVerdict:
    return ZombieVerdict(
        plan_id=plan_id, title="Epic", state=state, zombie=state == "zombie"
    )


def _snapshot(*rows: ZombieVerdict) -> ZombieReport:
    return ZombieReport(
        report=ZombieEvaluationReport(rows=rows),
        project="demo",
        titles={row.plan_id: row.title for row in rows},
        generated_at=1.0,
    )


def test_warm_reports_reuse_ttl_and_invalidate_on_store_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprints = ["store-1"]
    snapshots = iter(
        (_snapshot(_row("sase-demo.1")), _snapshot(_row("sase-demo.1", "owned")))
    )
    loads: list[str] = []

    monkeypatch.setattr(
        zombie_cache, "project_store_fingerprint", lambda _project: fingerprints[0]
    )

    def load(project_key: str, *, now: float | None = None) -> ZombieReport:
        loads.append(project_key)
        return next(snapshots)

    monkeypatch.setattr(zombie_module, "load_zombie_report", load)

    first = agent_zombie.warm_zombie_reports(("demo",))
    cached = agent_zombie.warm_zombie_reports(("demo",))
    fingerprints[0] = "store-2"
    refreshed = agent_zombie.warm_zombie_reports(("demo",))

    assert first == {"demo": frozenset({"sase-demo.1"})}
    assert cached == {}
    assert refreshed == {"demo": frozenset({"sase-demo.1"})}
    assert loads == ["demo", "demo"]
    assert agent_zombie.cached_zombie_verdict("demo", "sase-demo.1") is not None


def test_zombie_report_ttl_expires_after_60_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(zombie_cache, "monotonic", lambda: now[0])
    zombie_cache._ZOMBIE_REPORT_CACHE.set("demo", _snapshot(), "store")

    assert zombie_cache._CACHE_TTL_SECONDS == 60.0
    assert agent_zombie.should_resolve_zombie_report("demo") is False
    now[0] += 59.999
    assert agent_zombie.should_resolve_zombie_report("demo") is False
    now[0] += 0.001
    assert agent_zombie.should_resolve_zombie_report("demo") is True


def test_forced_warmup_has_30_second_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    loads: list[str] = []
    monkeypatch.setattr(zombie_cache, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        zombie_cache, "project_store_fingerprint", lambda _project: "store"
    )

    def load(project_key: str, *, now: float | None = None) -> ZombieReport:
        loads.append(project_key)
        return _snapshot(_row("sase-demo.1"))

    monkeypatch.setattr(zombie_module, "load_zombie_report", load)

    agent_zombie.warm_zombie_reports(("demo",))
    now[0] = 129.999
    agent_zombie.warm_zombie_reports(("demo",), force=True)
    assert loads == ["demo"]

    now[0] = 130.0
    agent_zombie.warm_zombie_reports(("demo",), force=True)
    assert loads == ["demo", "demo"]


def test_failed_collection_never_replaces_a_good_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        zombie_cache, "project_store_fingerprint", lambda _project: "store"
    )
    good = _snapshot(_row("sase-demo.1"))
    zombie_cache._ZOMBIE_REPORT_CACHE.set("demo", good, "store")

    def load(project_key: str, *, now: float | None = None) -> ZombieReport:
        return ZombieReport(
            report=ZombieEvaluationReport(),
            project=project_key,
            titles={},
            generated_at=2.0,
            collection_failed=True,
            failure_reason="boom",
        )

    monkeypatch.setattr(zombie_module, "load_zombie_report", load)
    assert agent_zombie.warm_zombie_reports(("demo",), force=True) == {}
    assert agent_zombie.cached_zombie_report("demo") is good


def test_cached_zombie_verdict_returns_none_without_a_report() -> None:
    assert agent_zombie.cached_zombie_verdict("demo", "sase-demo.1") is None
