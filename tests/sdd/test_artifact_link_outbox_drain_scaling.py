"""Scaling, catalog, deadline, and rewrite contracts for the outbox drain."""

from __future__ import annotations

from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from sase.sdd import _artifact_link_outbox_drain as outbox_drain
from sase.sdd import _artifact_link_outbox_drain_support as drain_support
from sase.sdd._artifact_link_outbox_drain_support import AgentTerminalTimes
from sase.sdd._artifact_link_outbox_io import (
    _artifact_link_outbox_dropped_path,
    _artifact_link_outbox_path,
    read_artifact_link_outbox_entries,
)
from sase.sdd.artifact_link_outbox import (
    append_artifact_link_outbox_entry,
    drain_artifact_link_outbox,
)
from sase.sdd.artifact_link_release_evidence import (
    record_artifact_link_release_evidence,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.main.artifact_link_outbox_helpers import _init_plans_repo
from tests.sdd._artifact_link_store_helpers import _row, allow_machine_sidecar_writes

PROJECT_KEY = "gh_sase-org__sase"
OTHER_PROJECT_KEY = "gh_example__other"


def _store(tmp_path: Path, project_key: str = PROJECT_KEY) -> ArtifactLinkStore:
    repo = tmp_path / f"plans-{project_key}"
    _init_plans_repo(repo)
    return ArtifactLinkStore(project_key=project_key, sidecar_roots={"plan": repo})


def _queue_read(
    project_key: str,
    *,
    agent: str,
    run_id: str,
    target: str = "plan:doc.md",
    now: float | None = None,
) -> None:
    append_artifact_link_outbox_entry(
        project_key=project_key,
        agent_name=agent,
        run_id=run_id,
        row=_row(source=f"agent:{agent}", target=target, origin="read"),
        now=now,
    )


def _catalog(*rows: tuple[str, float]) -> SimpleNamespace:
    return SimpleNamespace(
        rows=[
            SimpleNamespace(
                name=name, state="completed", status="DONE", finished_at=finished
            )
            for name, finished in rows
        ]
    )


def _old_rows_setup(
    monkeypatch: pytest.MonkeyPatch, project_key: str, *, agent: str
) -> float:
    """Queue two never-publishable rows well past a patched retention cutoff."""

    created_at = time.time() - 5_000.0
    _queue_read(project_key, agent=agent, run_id="run-a", now=created_at)
    _queue_read(
        project_key, agent=agent, run_id="run-a", target="plan:b.md", now=created_at
    )
    monkeypatch.setattr(outbox_drain, "_terminal_cutoff", lambda now: now - 1_000.0)
    return created_at


def test_drain_loads_evidence_once_for_the_whole_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    store = _store(tmp_path)
    for index in range(300):
        _queue_read(
            PROJECT_KEY,
            agent=f"reader-{index}",
            run_id=f"run-{index}",
            target=f"plan:{index}.md",
        )
        # Evidence for other runs, plus three runs that really did qualify.
        released = index in {7, 150, 299}
        record_artifact_link_release_evidence(
            project_key=PROJECT_KEY,
            run_id=f"run-{index}" if released else f"elsewhere-{index}",
            agent_id=f"reader-{index}",
            qualifying_repo_ids=("/tmp/plans",),
        )

    from sase.sdd import artifact_link_release_evidence as evidence_module

    loads = 0
    original_load = evidence_module.load_artifact_link_release_evidence_index

    def counted_load(project_key: str) -> frozenset[tuple[str, str]]:
        nonlocal loads
        loads += 1
        return original_load(project_key)

    monkeypatch.setattr(
        evidence_module, "load_artifact_link_release_evidence_index", counted_load
    )

    report = drain_artifact_link_outbox(
        store=store,
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    assert loads == 1
    assert report.queued == 300
    assert report.drained == 3
    assert report.retained == 297
    remaining = {
        entry.run_id for entry in read_artifact_link_outbox_entries(PROJECT_KEY)
    }
    assert len(remaining) == 297
    assert not remaining & {"run-7", "run-150", "run-299"}
    assert {name for name, _ in report.phase_seconds} >= {
        "read",
        "evidence",
        "eligibility",
        "publish",
        "rewrite",
    }


def test_no_catalog_build_when_no_ineligible_row_is_old_enough(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    store = _store(tmp_path)
    _queue_read(PROJECT_KEY, agent="reader", run_id="run-1")
    terminal_times = AgentTerminalTimes(
        snapshot_builder=lambda: pytest.fail("catalog must not be built")
    )

    report = drain_artifact_link_outbox(
        store=store,
        drop_stale_terminal=True,
        push_after_commit=False,
        terminal_times=terminal_times,
    )

    assert terminal_times.built is False
    assert report.stale_checked is True
    assert report.dropped == 0
    assert "catalog" not in dict(report.phase_seconds)
    assert len(read_artifact_link_outbox_entries(PROJECT_KEY)) == 1


def test_one_catalog_build_is_shared_by_two_drains_and_drops_stale_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    first_store = _store(tmp_path, PROJECT_KEY)
    second_store = _store(tmp_path, OTHER_PROJECT_KEY)
    created_at = _old_rows_setup(monkeypatch, PROJECT_KEY, agent="reader-one")
    _old_rows_setup(monkeypatch, OTHER_PROJECT_KEY, agent="reader-two")
    # A fresh row from a finished agent is never stale: it postdates the cutoff.
    _queue_read(PROJECT_KEY, agent="reader-one", run_id="run-b", target="plan:c.md")
    builds = 0

    def build() -> SimpleNamespace:
        nonlocal builds
        builds += 1
        finished = created_at + 1.0
        return _catalog(("reader-one", finished), ("reader-two", finished))

    terminal_times = AgentTerminalTimes(snapshot_builder=build)

    first = drain_artifact_link_outbox(
        store=first_store,
        push_after_commit=False,
        terminal_times=terminal_times,
    )
    second = drain_artifact_link_outbox(
        store=second_store,
        push_after_commit=False,
        terminal_times=terminal_times,
    )

    assert builds == 1
    assert terminal_times.ok is True
    assert (first.dropped, second.dropped) == (2, 2)
    assert first.stale_checked is True and second.stale_checked is True
    [kept] = read_artifact_link_outbox_entries(PROJECT_KEY)
    assert kept.run_id == "run-b"
    assert read_artifact_link_outbox_entries(OTHER_PROJECT_KEY) == ()
    dropped_lines = (
        _artifact_link_outbox_dropped_path(PROJECT_KEY)
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(dropped_lines) == 2


def test_catalog_build_failure_drops_nothing_and_is_not_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    store = _store(tmp_path)
    _old_rows_setup(monkeypatch, PROJECT_KEY, agent="reader")

    def broken() -> SimpleNamespace:
        raise RuntimeError("catalog unavailable")

    terminal_times = AgentTerminalTimes(snapshot_builder=broken)

    report = drain_artifact_link_outbox(
        store=store,
        push_after_commit=False,
        terminal_times=terminal_times,
    )

    assert terminal_times.built is True
    assert terminal_times.ok is False
    assert report.dropped == 0
    assert report.stale_checked is False
    assert len(read_artifact_link_outbox_entries(PROJECT_KEY)) == 2


def test_catalog_is_not_built_without_enough_deadline_headroom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    store = _store(tmp_path)
    _old_rows_setup(monkeypatch, PROJECT_KEY, agent="reader")
    terminal_times = AgentTerminalTimes(
        snapshot_builder=lambda: pytest.fail("catalog must not be built")
    )

    report = drain_artifact_link_outbox(
        store=store,
        push_after_commit=False,
        terminal_times=terminal_times,
        deadline=time.monotonic()
        + outbox_drain._STALE_CATALOG_MIN_HEADROOM_SECONDS / 2,
    )

    assert terminal_times.built is False
    assert report.dropped == 0
    assert report.stale_checked is False
    assert report.deferred is False
    assert outbox_drain._STALE_DROP_DEFERRED_DIAGNOSTIC in report.skip_diagnostics
    assert len(read_artifact_link_outbox_entries(PROJECT_KEY)) == 2


def test_deadline_crossed_mid_eligibility_defers_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    store = _store(tmp_path)
    for index in range(3):
        _queue_read(
            PROJECT_KEY,
            agent="reader",
            run_id="run-1",
            target=f"plan:{index}.md",
        )
    record_artifact_link_release_evidence(
        project_key=PROJECT_KEY,
        run_id="run-1",
        agent_id="reader",
        qualifying_repo_ids=("/tmp/plans",),
    )
    outbox_path = _artifact_link_outbox_path(PROJECT_KEY)
    before = outbox_path.read_bytes()
    clock = [0.0]
    monkeypatch.setattr(drain_support, "_DEADLINE_CHECK_STRIDE", 1)
    monkeypatch.setattr(outbox_drain.time, "monotonic", lambda: clock[0])
    original_eligible = outbox_drain._entry_is_eligible

    def eligible_then_late(entry, evidence_index):  # type: ignore[no-untyped-def]
        clock[0] = 100.0
        return original_eligible(entry, evidence_index)

    monkeypatch.setattr(outbox_drain, "_entry_is_eligible", eligible_then_late)

    report = drain_artifact_link_outbox(
        store=store,
        drop_stale_terminal=False,
        push_after_commit=False,
        deadline=50.0,
    )

    assert report.deferred is True
    assert report.drained == 0
    assert report.retained == 3
    assert outbox_path.read_bytes() == before
    assert not list((store.sidecar_roots["plan"] / "link-events").rglob("*.json"))


def test_drain_that_settles_nothing_does_not_rewrite_the_outbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    store = _store(tmp_path)
    _queue_read(PROJECT_KEY, agent="reader", run_id="run-1")
    outbox_path = _artifact_link_outbox_path(PROJECT_KEY)
    before = outbox_path.stat()

    report = drain_artifact_link_outbox(
        store=store,
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    after = outbox_path.stat()
    assert report.retained == 1
    assert "rewrite" not in dict(report.phase_seconds)
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


def test_drain_still_rewrites_a_queue_with_duplicate_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    store = _store(tmp_path)
    _queue_read(PROJECT_KEY, agent="reader", run_id="run-1")
    outbox_path = _artifact_link_outbox_path(PROJECT_KEY)
    [line] = outbox_path.read_text(encoding="utf-8").splitlines()
    outbox_path.write_text(f"{line}\n{line}\n", encoding="utf-8")

    report = drain_artifact_link_outbox(
        store=store,
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    assert report.queued == 2
    assert "rewrite" in dict(report.phase_seconds)
    assert outbox_path.read_text(encoding="utf-8").splitlines() == [line]
