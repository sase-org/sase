"""Tests for immutable artifact-link event publication."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.sdd._artifact_link_event_canonical import (
    ArtifactLinkEventCorruptionError,
    canonical_artifact_link_event_object,
)
from sase.sdd.artifact_link_event_publisher import (
    observation_or_put_event_from_row,
    publish_artifact_link_events,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row, allow_machine_sidecar_writes


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _init_repo(repo: Path, document: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _git(repo, "config", "user.name", "SASE Test")
    _git(repo, "config", "user.email", "sase-test@example.invalid")
    path = repo / document
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Document\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")


def _commit_count(repo: Path) -> int:
    return int(_git(repo, "rev-list", "--count", "HEAD").strip())


def _status(repo: Path) -> str:
    return _git(repo, "status", "--porcelain", "--untracked-files=all")


def test_publish_event_writes_dual_document_roots_and_replays_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    _init_repo(plans, "202609/a.md")
    _init_repo(research, "202609/b.md")
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )
    event = observation_or_put_event_from_row(
        _row(
            source="plan:202609/a.md",
            relation="related",
            target="research:202609/b.md",
            origin="manual",
        ),
        project_key=store.project_key,
        operation_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    event_object = canonical_artifact_link_event_object(event)

    report = publish_artifact_link_events(
        store,
        (event,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert report.published_operation_ids == ("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",)
    assert report.published == 1
    assert {path.parents[3] for path in report.event_paths} == {
        plans,
        research,
    }
    assert (plans / event_object.relative_path).read_bytes() == event_object.payload
    assert (research / event_object.relative_path).read_bytes() == event_object.payload
    assert not list(plans.glob("links/**/*"))
    assert not list(research.glob("links/**/*"))
    assert _commit_count(plans) == 2
    assert _commit_count(research) == 2
    assert _status(plans) == ""
    assert _status(research) == ""
    [row] = store.load_aggregate()["rows"]
    assert row["source_ref"] == "plan:202609/a.md"
    assert row["target_ref"] == "research:202609/b.md"

    replay = publish_artifact_link_events(
        store,
        (event,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert replay.published == 1
    assert replay.committed is False
    assert _commit_count(plans) == 2
    assert _commit_count(research) == 2
    assert _status(plans) == ""
    assert _status(research) == ""


def test_publish_event_rejects_same_path_with_different_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = tmp_path / "plans"
    _init_repo(plans, "202609/a.md")
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    event = observation_or_put_event_from_row(
        _row(source="plan:202609/a.md", target="agent:reader", origin="manual"),
        project_key=store.project_key,
        operation_id="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    event_object = canonical_artifact_link_event_object(event)
    path = plans / event_object.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ArtifactLinkEventCorruptionError):
        publish_artifact_link_events(
            store,
            (event,),
            push_after_commit=False,
            mutation_origin="machine",
        )

    assert _commit_count(plans) == 1
