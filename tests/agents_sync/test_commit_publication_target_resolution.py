from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import commit_publication, targets
from sase.agents_sync.commit_publication import (
    resolve_publication_project_key,
)
from sase.agents_sync.models import SyncOutcome, TargetSelection
from sase.repo_inventory import (
    RepoCloneRecord,
    RepoInventory,
    RepoKind,
    RepoRecord,
)
from tests.agents_sync.commit_publication_fixtures import (
    publish_committed_agent_hood,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _repo_record(
    path: Path,
    *,
    kind: RepoKind,
    project_key: str,
    clones: tuple[RepoCloneRecord, ...] = (),
    name: str | None = None,
    slug: str | None = None,
    remote_url: str | None = None,
) -> RepoRecord:
    return RepoRecord(
        name=name or path.name,
        kind=kind,
        project=project_key.removeprefix("key-"),
        project_key=project_key,
        path=str(path),
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        slug=slug,
        remote_url=remote_url,
        clones=clones,
    )


def test_resolves_known_repository_kinds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = []
    for kind in ("primary", "sidecar", "linked"):
        root = tmp_path / kind
        root.mkdir()
        _git(root, "init")
        (root / "nested").mkdir()
        records.append(_repo_record(root, kind=kind, project_key=f"key-{kind}"))
    monkeypatch.setattr(
        commit_publication,
        "collect_repo_inventory",
        lambda: RepoInventory(tuple(records)),
    )

    for record in records:
        assert (
            resolve_publication_project_key(Path(record.path) / "nested")
            == record.project_key
        )


def test_sync_targets_use_primary_slug_or_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[RepoRecord] = []
    for suffix, primary_name, primary_slug in (
        ("slugged", "inventory-name", "hosted-name"),
        ("named", "plain-name", None),
    ):
        project_key = f"key-{suffix}"
        primary = tmp_path / f"{suffix}-primary"
        agents = tmp_path / f"{suffix}-agents"
        primary.mkdir()
        agents.mkdir()
        records.extend(
            (
                _repo_record(
                    primary,
                    kind="primary",
                    project_key=project_key,
                    name=primary_name,
                    slug=primary_slug,
                ),
                _repo_record(
                    agents,
                    kind="sidecar",
                    project_key=project_key,
                    name="agents",
                    remote_url=f"git@example.test:{project_key}-agents.git",
                ),
            )
        )
    monkeypatch.setattr(targets, "list_project_records", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        targets,
        "collect_repo_inventory",
        lambda *_args, **_kwargs: RepoInventory(tuple(records)),
    )

    selection = targets.resolve_sync_targets(projects_root=tmp_path)

    assert selection.outcomes == ()
    assert {
        target.project_key: target.primary_repo_name for target in selection.targets
    } == {
        "key-named": "plain-name",
        "key-slugged": "hosted-name",
    }


def test_resolves_numbered_sidecar_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_path = tmp_path / "workspace-sidecar"
    workspace_path.mkdir()
    _git(workspace_path, "init")
    (workspace_path / "nested").mkdir()
    record = _repo_record(
        tmp_path / "machine-sidecar",
        kind="sidecar",
        project_key="host-project",
        clones=(RepoCloneRecord(12, str(workspace_path), True),),
    )
    monkeypatch.setattr(
        commit_publication,
        "collect_repo_inventory",
        lambda: RepoInventory((record,)),
    )

    assert resolve_publication_project_key(workspace_path / "nested") == "host-project"


def test_prefers_primary_on_path_tie(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init")
    records = (
        _repo_record(root, kind="linked", project_key="linked-host"),
        _repo_record(root, kind="primary", project_key="primary-host"),
    )
    monkeypatch.setattr(
        commit_publication,
        "collect_repo_inventory",
        lambda: RepoInventory(records),
    )

    assert resolve_publication_project_key(root) == "primary-host"


def test_unregistered_repository_without_name_fallback_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "unregistered"
    root.mkdir()
    _git(root, "init")
    monkeypatch.setattr(
        commit_publication,
        "collect_repo_inventory",
        lambda: RepoInventory(()),
    )
    monkeypatch.setattr(commit_publication, "_current_project", lambda: None)

    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        commit_cwd=root,
    )

    assert outcome.error is None
    assert outcome.skip_reason is not None
    assert str(root) in outcome.skip_reason


def test_project_without_agents_target_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        commit_publication,
        "resolve_sync_targets",
        lambda _projects: TargetSelection(
            (),
            (
                SyncOutcome(
                    "proj",
                    "Project",
                    error="agents target is unavailable",
                ),
            ),
        ),
    )

    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="proj",
    )

    assert outcome.error is None
    assert outcome.skip_reason == (
        "project 'proj' has no usable publication target: agents target is unavailable"
    )
