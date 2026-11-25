"""Degraded stranded reports never replace a complete generation."""

from __future__ import annotations

from sase.ace.tui.models import _agent_stranded_cache as stranded_cache

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.models import agent_stranded
from sase.bead import _stranded_facts_snapshot as snapshot
from sase.bead import stranded as stranded_module
from sase.bead.stranded import load_stranded_report
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict
from tests._stranded_collector_helpers import (
    PROJECT,
    phase,
    record,
    wire_collector,
)

_NOW = 1_700_000_000.0


@pytest.fixture(autouse=True)
def _clear_stranded_cache():
    stranded_cache._STRANDED_REPORT_CACHE.clear()
    yield
    stranded_cache._STRANDED_REPORT_CACHE.clear()


def _dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "artifacts" / name
    path.mkdir(parents=True)
    return path


def _report(
    bead_id: str = "sase-demo.1",
    *,
    records_unavailable: int = 0,
    verdicts: tuple[StrandedWorkVerdict, ...] | None = None,
) -> stranded_module.StrandedReport:
    if verdicts is None:
        verdicts = (
            StrandedWorkVerdict(
                bead_id=bead_id,
                kind="phase",
                state="stranded",
                blocked_by=(),
            ),
        )
    return stranded_module.StrandedReport(
        report=StrandedWorkReport(
            verdicts=verdicts,
            stranded_ids=tuple(
                verdict.bead_id for verdict in verdicts if verdict.state == "stranded"
            ),
        ),
        titles={bead_id: "Phase"},
        generated_at=1.0,
        collection_failed=False,
        stable_rebuild=True,
        records_unavailable=records_unavailable,
    )


def _degraded_report() -> stranded_module.StrandedReport:
    verdicts = (
        StrandedWorkVerdict(
            bead_id="sase-demo.1",
            kind="phase",
            state="unknown",
            reason="records_unavailable",
        ),
    )
    return _report(
        verdicts=verdicts,
        records_unavailable=1,
    )


def test_lock_contention_returns_degraded_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [record(artifact, name="sase-1.2", session="sase-1.2")],
    )

    def boom(_project: str, _keys: list[str]) -> object:
        raise RuntimeError("artifact index operation lock is busy")

    monkeypatch.setattr(snapshot, "_query_session_records_chunk", boom)
    report = load_stranded_report(PROJECT, now=_NOW)
    assert report.collection_failed is False
    assert report.degraded is True
    assert report.records_unavailable > 0


def test_degraded_load_does_not_replace_complete_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(stranded_cache, "monotonic", lambda: now[0])
    monkeypatch.setattr(stranded_cache, "_project_fingerprint", lambda _p: "store")
    complete = _report()
    degraded = _degraded_report()
    refreshed = _report()
    loads = {"count": 0}

    def load(project_key: str) -> stranded_module.StrandedReport:
        loads["count"] += 1
        if loads["count"] == 2:
            return degraded
        if loads["count"] >= 3:
            return refreshed
        return complete

    monkeypatch.setattr(stranded_module, "load_stranded_report", load)
    telemetry: dict[str, int] = {}
    changed = agent_stranded.warm_stranded_work_reports(("demo",), telemetry=telemetry)
    assert changed == {"demo": frozenset({"sase-demo.1"})}
    cached = agent_stranded.cached_stranded_report("demo")
    assert cached is complete

    now[0] = 200.0
    changed = agent_stranded.warm_stranded_work_reports(("demo",), telemetry=telemetry)
    assert changed == {}
    assert agent_stranded.cached_stranded_report("demo") is complete
    assert telemetry["stranded_degraded_skips"] == 1

    now[0] = 300.0
    agent_stranded.warm_stranded_work_reports(("demo",), telemetry=telemetry)
    assert agent_stranded.cached_stranded_report("demo") is refreshed


def test_cold_degraded_load_installs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stranded_cache, "monotonic", lambda: 100.0)
    monkeypatch.setattr(stranded_cache, "_project_fingerprint", lambda _p: "store")
    degraded = _degraded_report()
    monkeypatch.setattr(stranded_module, "load_stranded_report", lambda _p: degraded)
    agent_stranded.warm_stranded_work_reports(
        ("demo",), force=True, force_immediate=True
    )
    cached = agent_stranded.cached_stranded_report("demo")
    assert cached is degraded
    assert cached is not None and cached.degraded is True


def test_degraded_over_degraded_installs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stranded_cache, "monotonic", lambda: 100.0)
    monkeypatch.setattr(stranded_cache, "_project_fingerprint", lambda _p: "store")
    first = _degraded_report()
    monkeypatch.setattr(stranded_module, "load_stranded_report", lambda _p: first)
    agent_stranded.warm_stranded_work_reports(
        ("demo",), force=True, force_immediate=True
    )
    assert agent_stranded.cached_stranded_report("demo") is first

    second = _degraded_report()
    monkeypatch.setattr(stranded_module, "load_stranded_report", lambda _p: second)
    agent_stranded.warm_stranded_work_reports(
        ("demo",), force=True, force_immediate=True
    )
    assert agent_stranded.cached_stranded_report("demo") is second


def _fingerprint(token: str) -> SimpleNamespace:
    return SimpleNamespace(token=token)
