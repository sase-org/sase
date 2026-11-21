"""Slow-pass progress lines for the agent publication job."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync import (
    _publication_job_run as job_run,
    publication_job,
)
from tests._conftest_environment import redirect_sase_home
from tests.agents_sync._publication_job_helpers import publication_target


def _install_single_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = publication_target(tmp_path)
    monkeypatch.setattr(
        job_run,
        "list_project_records",
        lambda *_a, **_k: [
            SimpleNamespace(
                project_name="proj", workspace_dir="/tmp/proj", is_project=True
            )
        ],
    )
    monkeypatch.setattr(
        job_run,
        "resolve_sync_targets",
        lambda _keys: SimpleNamespace(targets=(target,), outcomes=()),
    )
    monkeypatch.setattr(
        job_run,
        "drain_project",
        lambda *_a, **_k: SimpleNamespace(
            hood_drained=0,
            link_drained=0,
            referenced_by_drained=0,
            lock_busy=False,
            deferred=False,
            deferred_projects=0,
            retained_hints=False,
            claim_unfinished=False,
            error=None,
            outcome="empty",
        ),
    )
    monkeypatch.setattr(job_run, "safe_active_items", lambda _key: ())
    monkeypatch.setattr(job_run, "safe_referenced_by_count", lambda _key: 0)
    monkeypatch.setattr(job_run, "write_publication_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(job_run, "save_standing_alerts", lambda *_a, **_k: None)
    monkeypatch.setattr(job_run, "load_standing_alerts", lambda: {})


def test_fast_pass_emits_no_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _install_single_project(monkeypatch, tmp_path)

    messages: list[str] = []
    summary = publication_job.run_publication_job(
        work_budget_seconds=10, progress=messages.append
    )

    assert summary.projects == 1
    assert messages == []


def test_slow_pass_emits_progress_per_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _install_single_project(monkeypatch, tmp_path)

    calls = {"count": 0}
    base = 1000.0

    def fake_monotonic() -> float:
        calls["count"] += 1
        if calls["count"] == 1:
            return base
        return base + 61.0 + calls["count"] * 0.01

    monkeypatch.setattr(job_run.time, "monotonic", fake_monotonic)

    messages: list[str] = []
    summary = publication_job.run_publication_job(
        work_budget_seconds=240, progress=messages.append
    )

    assert summary.projects == 1
    assert any("project discovery" in message for message in messages)
    assert any("resolve_sync_targets" in message for message in messages)
    assert any("drain_project(proj)" in message for message in messages)
    assert any("heartbeat write" in message for message in messages)
    assert all("61." in message or "62." in message for message in messages)


def _stub_drain_stages(
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
    *,
    phase_seconds: tuple[tuple[str, float], ...] = (),
) -> None:
    """Stub every drain_project stage so each records when its work starts."""

    from sase.agents_sync import (
        _commit_publication_queue as publication_queue,
        _publication_job_drain as job_drain,
        referenced_by_publication,
    )
    from sase.agents_sync.publication_doorbell import PublicationHintClaim

    item = SimpleNamespace(
        id="item-1",
        created_at=1.0,
        local_hood="hood",
        logical_key=("alice.athena.worker", "a" * 40),
    )
    queue = [item]
    claim = PublicationHintClaim(
        project_key="proj",
        paths=(),
        hints=(
            {
                "global_agent": "alice.athena.worker",
                "primary_revision": "a" * 40,
                "link_outbox_agent_name": "alice.athena.worker",
            },
        ),
    )
    monkeypatch.setattr(job_drain, "active_diverged_replay_marker", lambda *_a: None)
    monkeypatch.setattr(job_drain, "claim_publication_hints", lambda _key: claim)
    monkeypatch.setattr(job_drain, "finish_hint_claim", lambda *_a, **_k: None)
    monkeypatch.setattr(job_drain, "active_items", lambda _key: tuple(queue))
    monkeypatch.setattr(job_drain, "publication_is_ready", lambda _item: True)

    def drain_hoods(*_a: object, **_k: object) -> SimpleNamespace:
        events.append("work:hood")
        queue.clear()
        return SimpleNamespace(
            drained=1,
            failure_stage=None,
            error=None,
            skip_reason=None,
            failure_scope=None,
        )

    monkeypatch.setattr(
        publication_queue, "drain_selected_agent_publications", drain_hoods
    )

    def resolve_store(*_a: object, **_k: object) -> object:
        events.append("work:link store resolve")
        return object()

    def drain_links(**_k: object) -> SimpleNamespace:
        events.append("work:link drain")
        return SimpleNamespace(
            drained=1,
            selected_retained=0,
            deferred=False,
            phase_seconds=phase_seconds,
        )

    monkeypatch.setattr(job_drain, "resolve_machine_artifact_link_store", resolve_store)
    monkeypatch.setattr(job_drain, "drain_artifact_link_outbox", drain_links)
    refby = [SimpleNamespace()]
    monkeypatch.setattr(
        job_drain, "safe_referenced_by_items", lambda _key: tuple(refby)
    )

    def drain_refby(*_a: object, **_k: object) -> list[str]:
        events.append("work:referenced-by drain")
        refby.clear()
        return []

    monkeypatch.setattr(
        referenced_by_publication, "drain_referenced_by_requests", drain_refby
    )

    def sweep(*_a: object, **_k: object) -> None:
        events.append("work:quarantine sweep")

    monkeypatch.setattr(job_drain, "_sweep_quarantined_prompts", sweep)


def test_drain_project_emits_stage_lines_before_each_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from sase.agents_sync import _publication_job_drain as job_drain

    events: list[str] = []
    _stub_drain_stages(monkeypatch, events)

    job_drain.drain_project(
        publication_target(tmp_path),
        deadline=time.monotonic() + 60,
        git_runner=lambda *_a, **_k: None,  # type: ignore[arg-type]
        progress=lambda message: events.append(f"stage:{message}"),
    )

    stage_events = [
        event for event in events if not event.startswith("stage:link drain phases")
    ]
    assert stage_events == [
        "stage:hood batch 1 (1 keys)",
        "work:hood",
        "stage:link store resolve",
        "work:link store resolve",
        "stage:link drain (1 agents)",
        "work:link drain",
        "stage:referenced-by drain",
        "work:referenced-by drain",
        "stage:quarantine sweep",
        "work:quarantine sweep",
    ]


def test_drain_project_link_phase_line_formats_publish_and_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from sase.agents_sync import _publication_job_drain as job_drain

    events: list[str] = []
    _stub_drain_stages(
        monkeypatch,
        events,
        phase_seconds=(
            ("read", 0.5),
            ("publish", 3.0),
            ("publish.admission", 1.0),
            ("publish.aggregate", 2.0),
            ("rewrite", 0.25),
        ),
    )
    lines: list[str] = []

    job_drain.drain_project(
        publication_target(tmp_path),
        deadline=time.monotonic() + 60,
        git_runner=lambda *_a, **_k: None,  # type: ignore[arg-type]
        progress=lines.append,
    )

    assert (
        "link drain phases: read=0.50s evidence=skipped eligibility=skipped "
        "catalog=skipped publish=3.00s publish.admission=1.00s "
        "publish.aggregate=2.00s rewrite=0.25s"
    ) in lines


def _stage_emitting_drain(*_a: object, **kwargs: object) -> SimpleNamespace:
    kwargs["progress"]("link store resolve")  # type: ignore[operator]
    return SimpleNamespace(
        hood_drained=0,
        link_drained=0,
        referenced_by_drained=0,
        lock_busy=False,
        deferred=False,
        deferred_projects=0,
        retained_hints=False,
        claim_unfinished=False,
        error=None,
        outcome="empty",
    )


def test_slow_pass_forwards_drain_stage_lines_with_project_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _install_single_project(monkeypatch, tmp_path)
    monkeypatch.setattr(job_run, "drain_project", _stage_emitting_drain)
    clock = {"first": True}

    def fake_monotonic() -> float:
        if clock["first"]:
            clock["first"] = False
            return 1000.0
        return 1061.0

    monkeypatch.setattr(job_run.time, "monotonic", fake_monotonic)
    messages: list[str] = []

    publication_job.run_publication_job(
        work_budget_seconds=240, progress=messages.append
    )

    assert any(
        "link store resolve" in m and m.endswith("project=proj") for m in messages
    )


def test_fast_pass_keeps_drain_stage_lines_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _install_single_project(monkeypatch, tmp_path)
    monkeypatch.setattr(job_run, "drain_project", _stage_emitting_drain)
    messages: list[str] = []

    publication_job.run_publication_job(
        work_budget_seconds=240, progress=messages.append
    )

    assert messages == []
