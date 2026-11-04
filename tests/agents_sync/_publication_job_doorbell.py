"""Doorbell, hint, and drain tests for the publication job."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync import _commit_publication_queue as publication_queue
from sase.agents_sync import publication_doorbell, publication_job
from sase.agents_sync._commit_publication_types import CommitPublicationOutcome
from tests._conftest_environment import redirect_sase_home
from tests.agents_sync._publication_job_helpers import (
    configure_single_project_job,
    publication_hint,
    publication_item,
    publication_target,
)


def test_doorbell_hint_claim_recovers_after_interrupted_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    first = publication_doorbell.ring_publication_doorbell(
        "proj", publication_hint("alice.athena.worker", "a" * 40)
    )
    first_claim = publication_doorbell.claim_publication_hints("proj")
    assert first.is_file()
    assert len(first_claim.hints) == 1
    assert first_claim.hints[0]["global_agent"] == "alice.athena.worker"
    assert first_claim.paths and first_claim.paths[0].is_file()

    # Simulate a crash: leave the claim untouched and append a new hint.
    publication_doorbell.ring_publication_doorbell(
        "proj", publication_hint("alice.athena.other", "b" * 40)
    )
    recovered = publication_doorbell.claim_publication_hints("proj")
    assert {hint["global_agent"] for hint in recovered.hints} == {
        "alice.athena.worker",
        "alice.athena.other",
    }
    publication_doorbell.finish_hint_claim(recovered)
    claimed_dir = tmp_path / ".sase" / "projects" / "proj" / "agent_publication"
    assert not tuple(claimed_dir.glob("hints.claimed.*"))


def test_publication_hint_can_be_persisted_without_ringing_doorbell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")

    hints = publication_doorbell.append_publication_hint(
        "proj", publication_hint("alice.athena.worker", "a" * 40)
    )
    directory = tmp_path / ".sase" / "projects" / "proj" / "agent_publication"

    assert hints.is_file()
    assert not (directory / "doorbell").exists()
    [claim] = publication_doorbell.claim_publication_hints("proj").hints
    assert claim["global_agent"] == "alice.athena.worker"


def test_heartbeat_round_trip_and_liveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    now = time.time()
    path = publication_doorbell.write_publication_heartbeat(
        {
            "proj": {
                "active_count": 2,
                "oldest_active_age_seconds": 8.5,
                "last_outcome": "drained",
            }
        },
        now=now,
    )
    payload = publication_doorbell._read_publication_heartbeat()
    assert path.is_file()
    assert payload is not None
    assert payload["projects"]["proj"]["active_count"] == 2
    assert publication_doorbell.publisher_is_live(60)

    publication_doorbell.write_publication_heartbeat({}, now=now - 61)
    assert not publication_doorbell.publisher_is_live(60)


def test_hinted_hood_requests_are_drained_before_the_oldest_backlog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    queue = [
        publication_item("alice.athena.backlog", "a" * 40, created_at=1),
        publication_item("alice.athena.hinted", "b" * 40, created_at=2),
    ]
    monkeypatch.setattr(
        publication_job, "active_agent_publications", lambda _key: tuple(queue)
    )
    monkeypatch.setattr(
        publication_job, "list_referenced_by_requests", lambda *_args, **_kwargs: ()
    )
    calls: list[tuple[tuple[str, str], ...]] = []
    hinted_key = ("alice.athena.hinted", "b" * 40)

    def drain_selected(_key: str, selected: tuple[tuple[str, str], ...], **_kwargs):
        calls.append(selected)
        selected_set = set(selected)
        queue[:] = [item for item in queue if item.logical_key not in selected_set]
        return CommitPublicationOutcome(drained=len(selected), published=True)

    monkeypatch.setattr(
        publication_queue, "drain_selected_agent_publications", drain_selected
    )
    publication_doorbell.ring_publication_doorbell(
        "proj", publication_hint("alice.athena.hinted", "b" * 40)
    )

    outcome = publication_job._drain_project(
        publication_target(tmp_path),
        deadline=time.monotonic() + 10,
        git_runner=lambda *_a, **_k: None,  # type: ignore[arg-type]
    )

    assert calls == [(hinted_key, ("alice.athena.backlog", "a" * 40))]
    assert outcome.hood_drained == 2
    assert queue == []


def test_item_error_does_not_starve_unhinted_ready_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(publication_job, "_HOOD_BATCH_LIMIT", 1)
    hinted = publication_item("alice.athena.hinted", "b" * 40, created_at=2)
    oldest = publication_item("alice.athena.oldest", "a" * 40, created_at=1)
    newer = publication_item("alice.athena.newer", "c" * 40, created_at=3)
    queue = [newer, hinted, oldest]
    monkeypatch.setattr(
        publication_job, "active_agent_publications", lambda _key: tuple(queue)
    )
    monkeypatch.setattr(
        publication_job,
        "list_referenced_by_requests",
        lambda *_args, **_kwargs: (),
    )
    calls: list[tuple[str, str]] = []
    hinted_key = hinted.logical_key

    def drain_selected(_key: str, selected: tuple[tuple[str, str], ...], **_kwargs):
        calls.extend(selected)
        if hinted_key in selected:
            return CommitPublicationOutcome(error="withheld row failed")
        selected_set = set(selected)
        queue[:] = [item for item in queue if item.logical_key not in selected_set]
        return CommitPublicationOutcome(drained=len(selected), published=True)

    monkeypatch.setattr(
        publication_queue, "drain_selected_agent_publications", drain_selected
    )
    publication_doorbell.ring_publication_doorbell(
        "proj", publication_hint("alice.athena.hinted", "b" * 40)
    )

    outcome = publication_job._drain_project(
        publication_target(tmp_path),
        deadline=time.monotonic() + 10,
        git_runner=lambda *_a, **_k: None,  # type: ignore[arg-type]
    )

    assert calls == [hinted.logical_key, oldest.logical_key, newer.logical_key]
    assert queue == [hinted]
    assert outcome.hood_drained == 2
    assert "withheld row failed" in (outcome.error or "")


def test_repository_failure_stops_and_retains_only_unattempted_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(publication_job, "_HOOD_BATCH_LIMIT", 1)
    first = publication_item("alice.athena.first", "a" * 40, created_at=1)
    second = publication_item("alice.athena.second", "b" * 40, created_at=2)
    queue = [first, second]
    monkeypatch.setattr(
        publication_job, "active_agent_publications", lambda _key: tuple(queue)
    )
    monkeypatch.setattr(
        publication_job,
        "list_referenced_by_requests",
        lambda *_args, **_kwargs: (),
    )
    calls: list[tuple[str, str]] = []

    def repository_failure(_key: str, selected: tuple[tuple[str, str], ...], **_kwargs):
        calls.extend(selected)
        return CommitPublicationOutcome(
            error="git push failed", failure_scope="repository"
        )

    monkeypatch.setattr(
        publication_queue, "drain_selected_agent_publications", repository_failure
    )
    publication_doorbell.ring_publication_doorbell(
        "proj", publication_hint("alice.athena.first", "a" * 40)
    )
    publication_doorbell.ring_publication_doorbell(
        "proj", publication_hint("alice.athena.second", "b" * 40)
    )

    outcome = publication_job._drain_project(
        publication_target(tmp_path),
        deadline=time.monotonic() + 10,
        git_runner=lambda *_a, **_k: None,  # type: ignore[arg-type]
    )

    directory = tmp_path / ".sase" / "projects" / "proj" / "agent_publication"
    claims = tuple(directory.glob("hints.claimed.*.jsonl"))
    assert calls == [first.logical_key]
    assert outcome.outcome == "repository_error"
    assert len(claims) == 1
    assert [
        hint["global_agent"] for hint in publication_doorbell._read_hints(claims[0])
    ] == ["alice.athena.second"]


def test_hint_claim_compacts_multiple_files_into_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    publication_doorbell.ring_publication_doorbell(
        "proj", publication_hint("alice.athena.first", "a" * 40)
    )
    publication_doorbell.claim_publication_hints("proj")
    publication_doorbell.ring_publication_doorbell(
        "proj", publication_hint("alice.athena.second", "b" * 40)
    )
    claim = publication_doorbell.claim_publication_hints("proj")

    assert len(claim.paths) == 2
    publication_doorbell.finish_hint_claim(claim, retain=(*claim.hints, *claim.hints))

    directory = tmp_path / ".sase" / "projects" / "proj" / "agent_publication"
    claims = tuple(directory.glob("hints.claimed.*.jsonl"))
    assert len(claims) == 1
    assert {
        hint["global_agent"] for hint in publication_doorbell._read_hints(claims[0])
    } == {"alice.athena.first", "alice.athena.second"}


def test_deadline_retains_unattempted_hinted_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(publication_job, "_HOOD_BATCH_LIMIT", 1)
    first = publication_item("alice.athena.first", "a" * 40, created_at=1)
    second = publication_item("alice.athena.second", "b" * 40, created_at=2)
    queue = [first, second]
    monkeypatch.setattr(
        publication_job, "active_agent_publications", lambda _key: tuple(queue)
    )
    monkeypatch.setattr(
        publication_job,
        "list_referenced_by_requests",
        lambda *_args, **_kwargs: (),
    )
    now = [0.0]
    monkeypatch.setattr(publication_job.time, "monotonic", lambda: now[0])
    calls: list[tuple[str, str]] = []

    def drain_one(_key: str, selected: tuple[tuple[str, str], ...], **_kwargs):
        calls.extend(selected)
        queue[:] = [item for item in queue if item.logical_key not in set(selected)]
        now[0] = 5.0
        return CommitPublicationOutcome(drained=len(selected), published=True)

    monkeypatch.setattr(
        publication_queue, "drain_selected_agent_publications", drain_one
    )
    publication_doorbell.ring_publication_doorbell(
        "proj", publication_hint("alice.athena.first", "a" * 40)
    )
    publication_doorbell.ring_publication_doorbell(
        "proj", publication_hint("alice.athena.second", "b" * 40)
    )

    outcome = publication_job._drain_project(
        publication_target(tmp_path),
        deadline=5.0,
        git_runner=lambda *_a, **_k: None,  # type: ignore[arg-type]
    )

    directory = tmp_path / ".sase" / "projects" / "proj" / "agent_publication"
    claims = tuple(directory.glob("hints.claimed.*.jsonl"))
    assert calls == [first.logical_key]
    assert outcome.deferred
    assert len(claims) == 1
    assert [
        hint["global_agent"] for hint in publication_doorbell._read_hints(claims[0])
    ] == ["alice.athena.second"]


def test_retained_link_rows_finish_the_hint_without_ringing_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    target = publication_target(tmp_path)
    configure_single_project_job(monkeypatch, target)
    monkeypatch.setattr(publication_job, "active_agent_publications", lambda _key: ())
    monkeypatch.setattr(
        publication_job,
        "list_referenced_by_requests",
        lambda *_args, **_kwargs: (),
    )
    link_agent = "alice.athena.worker"
    hint = publication_hint(link_agent, "a" * 40)
    hint["link_outbox_agent_name"] = link_agent
    publication_doorbell.ring_publication_doorbell("proj", hint)
    monkeypatch.setattr(
        publication_job,
        "ring_publication_doorbell",
        lambda *_args, **_kwargs: pytest.fail("retained link rows must not re-ring"),
    )
    monkeypatch.setattr(
        publication_job,
        "resolve_machine_artifact_link_store",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        publication_job,
        "drain_artifact_link_outbox",
        lambda **_kwargs: SimpleNamespace(
            drained=1,
            selected_retained=1,
            deferred=False,
        ),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    directory = tmp_path / ".sase" / "projects" / "proj" / "agent_publication"
    assert not tuple(directory.glob("hints.claimed.*"))
    assert "1 artifact-link rows retained for backfill" in str(
        summary.project_stats["proj"]["last_outcome"]
    )


@pytest.mark.parametrize("failure", ["deferred", "raised"])
def test_deferred_or_raised_link_drain_keeps_hint_and_rings_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    target = publication_target(tmp_path)
    configure_single_project_job(monkeypatch, target)
    monkeypatch.setattr(publication_job, "active_agent_publications", lambda _key: ())
    monkeypatch.setattr(
        publication_job,
        "list_referenced_by_requests",
        lambda *_args, **_kwargs: (),
    )
    link_agent = "alice.athena.worker"
    hint = publication_hint(link_agent, "a" * 40)
    hint["link_outbox_agent_name"] = link_agent
    publication_doorbell.ring_publication_doorbell("proj", hint)
    bells: list[str] = []
    monkeypatch.setattr(
        publication_job,
        "ring_publication_doorbell",
        lambda key, _hint=None: bells.append(key),
    )
    monkeypatch.setattr(
        publication_job,
        "resolve_machine_artifact_link_store",
        lambda *_args, **_kwargs: object(),
    )

    def drain_links(**_kwargs: object) -> SimpleNamespace:
        if failure == "raised":
            raise RuntimeError("link store unavailable")
        return SimpleNamespace(drained=0, selected_retained=0, deferred=True)

    monkeypatch.setattr(publication_job, "drain_artifact_link_outbox", drain_links)

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    directory = tmp_path / ".sase" / "projects" / "proj" / "agent_publication"
    assert bells == ["proj"]
    assert tuple(directory.glob("hints.claimed.*"))
    assert summary.project_stats["proj"]["last_outcome"] in {
        "deferred_budget",
        "link_error",
    }
