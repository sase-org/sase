from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.sdd.artifact_link_backfill import reconcile_and_repair_artifact_links
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    plans.mkdir()
    research.mkdir()
    return ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )


def test_reconciles_and_repairs_with_the_doctor_candidate_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    reconcile_calls: list[object] = []
    monkeypatch.setattr(store, "reconcile_aggregate", lambda: reconcile_calls.append(1))
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.dangling_and_orphaned_artifact_link_refs",
        lambda _store: ("plan:202608/dangling.md",),
    )
    repair_calls: list[object] = []

    def _fake_repair(_store: object, refs: object) -> SimpleNamespace:
        repair_calls.append(refs)
        return SimpleNamespace(renames=(), changed_paths=())

    monkeypatch.setattr(
        "sase.sdd._artifact_link_renames.repair_historical_artifact_renames",
        _fake_repair,
    )

    report = reconcile_and_repair_artifact_links(store)

    assert reconcile_calls == [1]
    assert repair_calls == [("plan:202608/dangling.md",)]
    assert report.repaired_renames == 0


def test_commits_changed_paths_from_a_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "reconcile_aggregate", lambda: None)
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.dangling_and_orphaned_artifact_link_refs",
        lambda _store: (),
    )
    changed = (tmp_path / "plans" / "links" / "202608" / "renamed.md.json",)
    monkeypatch.setattr(
        "sase.sdd._artifact_link_renames.repair_historical_artifact_renames",
        lambda _store, _refs: SimpleNamespace(renames=("one",), changed_paths=changed),
    )
    commit_calls: list[object] = []
    monkeypatch.setattr(
        "sase.sdd._artifact_link_commit.commit_artifact_link_indexes",
        lambda paths, **kwargs: commit_calls.append((paths, kwargs)),
    )

    report = reconcile_and_repair_artifact_links(store)

    assert report.repaired_renames == 1
    assert len(commit_calls) == 1
    paths, kwargs = commit_calls[0]
    assert paths == changed
    assert kwargs["push_after_commit"] == "async"


def test_no_changed_paths_does_not_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "reconcile_aggregate", lambda: None)
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.dangling_and_orphaned_artifact_link_refs",
        lambda _store: (),
    )
    monkeypatch.setattr(
        "sase.sdd._artifact_link_renames.repair_historical_artifact_renames",
        lambda _store, _refs: SimpleNamespace(renames=(), changed_paths=()),
    )
    commit_calls: list[object] = []
    monkeypatch.setattr(
        "sase.sdd._artifact_link_commit.commit_artifact_link_indexes",
        lambda paths, **kwargs: commit_calls.append((paths, kwargs)),
    )

    reconcile_and_repair_artifact_links(store)

    assert commit_calls == []
