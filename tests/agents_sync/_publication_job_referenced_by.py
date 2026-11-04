"""Referenced-by conversion tests for the publication job."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync import publication_job
from tests._conftest_environment import redirect_sase_home
from tests.agents_sync._publication_job_helpers import (
    configure_single_project_job,
    publication_target,
)


def _referenced_by_item():
    from sase.agents_sync.referenced_by_outbox import ReferencedByOutboxItem

    return ReferencedByOutboxItem(
        project_key="proj",
        project="Project",
        global_agent="alice.athena.worker",
        agent_url="https://example.test/agents/worker",
        primary_revision="a" * 40,
        sidecar_role="plans",
        provider="plan",
        artifact_id="plan:202608/example.md",
        repo_relpath="202608/example.md",
        identity_value=None,
        canonical_ref="plan:202608/example.md",
        destination="https://example.test/prompts/1",
        uses=1,
        published_date="2026-08-12",
    )


def test_publisher_converts_fenced_referenced_by_requests_without_sidecar_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync import referenced_by_events, referenced_by_publication
    from sase.agents_sync.referenced_by_outbox import (
        enqueue_referenced_by_request,
        list_referenced_by_requests,
    )

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    target = publication_target(tmp_path)
    configure_single_project_job(monkeypatch, target)
    request = enqueue_referenced_by_request(_referenced_by_item())
    monkeypatch.setattr(
        referenced_by_publication,
        "legacy_referenced_by_writes_fenced",
        lambda _target: True,
    )
    emitted: list[object] = []
    monkeypatch.setattr(
        referenced_by_events,
        "emit_referenced_by_cites_events",
        lambda items, **_kwargs: emitted.extend(items) or (),
    )
    monkeypatch.setattr(
        referenced_by_publication,
        "_resolve_store",
        lambda *_args, **_kwargs: pytest.fail(
            "fenced conversion must not resolve a store"
        ),
    )
    monkeypatch.setattr(
        referenced_by_publication,
        "refresh_referenced_by",
        lambda *_args, **_kwargs: pytest.fail("fenced conversion must not refresh"),
    )
    bells: list[str] = []
    monkeypatch.setattr(
        publication_job,
        "ring_publication_doorbell",
        lambda key, _hint=None: bells.append(key),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert emitted == [request]
    assert list_referenced_by_requests("proj", include_quarantined=False) == ()
    assert summary.referenced_by_drained == 1
    assert bells == []


def test_publisher_keeps_unfenced_referenced_by_refresh_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync import referenced_by_publication
    from sase.agents_sync.referenced_by_outbox import (
        enqueue_referenced_by_request,
        list_referenced_by_requests,
    )
    from sase.sdd._referenced_by_refresh_models import ReferencedByRefreshReport

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    target = publication_target(tmp_path)
    configure_single_project_job(monkeypatch, target)
    request = enqueue_referenced_by_request(_referenced_by_item())
    monkeypatch.setattr(
        referenced_by_publication,
        "legacy_referenced_by_writes_fenced",
        lambda _target: False,
    )
    monkeypatch.setattr(
        referenced_by_publication, "_resolve_store", lambda _target: object()
    )
    refreshes: list[str] = []
    monkeypatch.setattr(
        referenced_by_publication,
        "refresh_referenced_by",
        lambda _store, *, role, requests, write: (
            refreshes.append(role)
            or ReferencedByRefreshReport(
                root=tmp_path,
                role=role,
                write=write,
                scanned=0,
                actions=(),
                issues=(),
                changed_files=(),
                committed=False,
            )
        ),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert refreshes == ["plans"]
    assert list_referenced_by_requests("proj", include_quarantined=False) == ()
    assert summary.referenced_by_drained == 1
    assert request.logical_key not in {
        item.logical_key
        for item in list_referenced_by_requests("proj", include_quarantined=True)
    }


def test_fenced_conversion_failure_quarantines_without_re_ring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync import referenced_by_events, referenced_by_publication
    from sase.agents_sync.referenced_by_outbox import (
        enqueue_referenced_by_request,
        list_referenced_by_requests,
    )

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setenv("SASE_AGENTS_PUBLICATION_MAX_ATTEMPTS", "1")
    target = publication_target(tmp_path)
    configure_single_project_job(monkeypatch, target)
    request = enqueue_referenced_by_request(_referenced_by_item())
    monkeypatch.setattr(
        referenced_by_publication,
        "legacy_referenced_by_writes_fenced",
        lambda _target: True,
    )
    monkeypatch.setattr(
        referenced_by_events,
        "emit_referenced_by_cites_events",
        lambda *_args, **_kwargs: ("event append failed",),
    )
    bells: list[str] = []
    monkeypatch.setattr(
        publication_job,
        "ring_publication_doorbell",
        lambda key, _hint=None: bells.append(key),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert list_referenced_by_requests("proj", include_quarantined=False) == ()
    [quarantined] = list_referenced_by_requests("proj", include_quarantined=True)
    assert quarantined.logical_key == request.logical_key
    assert quarantined.attempts == 1
    assert quarantined.quarantined
    assert summary.errors == 1
    assert bells == []
