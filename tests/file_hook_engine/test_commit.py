"""Commit-time file-hook engine tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.file_hooks.audit import list_file_hook_audits
from sase.file_hooks.engine import (
    _derive_commit_file_events,
    dispatch_file_hook_events,
)
from sase.sdd._commit_store import _emit_sdd_file_hooks, commit_sdd_files
from sase.vcs_provider import get_vcs_provider
from sase.workflows.commit.checkpoint import CommitCheckpoint
from sase.workflows.commit.workflow import CommitWorkflow

from .helpers import (
    clear_agent_env,
    commit,
    emit_commit,
    emitted_agent_names,
    event,
    git,
    hook,
    init_repo,
    stub_detached_spawn,
)


def test_commit_event_derivation_handles_root_add_modify_delete_and_rename(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    (repo / "old.txt").write_text("one\n", encoding="utf-8")
    root_sha = commit(repo, "root")
    provider = get_vcs_provider(str(repo))

    root_events = _derive_commit_file_events(
        provider,
        repo_root=repo,
        commit_sha=root_sha,
        project="sase",
        repo_kind="primary",
        sidecar_role=None,
    )
    assert [(event.op, event.rel_path) for event in root_events] == [("ADD", "old.txt")]

    git(repo, "mv", "old.txt", "renamed.txt")
    (repo / "added.txt").write_text("added\n", encoding="utf-8")
    rename_sha = commit(repo, "rename and add")
    rename_events = _derive_commit_file_events(
        provider,
        repo_root=repo,
        commit_sha=rename_sha,
        project="sase",
        repo_kind="primary",
        sidecar_role=None,
    )
    assert {(event.op, event.rel_path) for event in rename_events} == {
        ("REMOVE", "old.txt"),
        ("ADD", "renamed.txt"),
        ("ADD", "added.txt"),
    }

    (repo / "renamed.txt").write_text("two\n", encoding="utf-8")
    (repo / "added.txt").unlink()
    changed_sha = commit(repo, "modify and remove")
    changed_events = _derive_commit_file_events(
        provider,
        repo_root=repo,
        commit_sha=changed_sha,
        project="sase",
        repo_kind="primary",
        sidecar_role=None,
    )
    assert [(event.op, event.rel_path) for event in changed_events] == [
        ("REMOVE", "added.txt"),
        ("MODIFY", "renamed.txt"),
    ]


def test_commit_batch_records_the_producing_agent_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    (repo / "report.md").write_text("# report\n", encoding="utf-8")
    (repo / "notes.md").write_text("# notes\n", encoding="utf-8")
    sha = commit(repo, "add reports")
    clear_agent_env(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_NAME", "research.7.final")

    batch_path = emit_commit(monkeypatch, repo, sha, hook("render"))

    assert batch_path is not None
    assert emitted_agent_names(batch_path) == ["research.7.final"] * 2


def test_agent_meta_name_wins_over_the_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    (repo / "report.md").write_text("# report\n", encoding="utf-8")
    sha = commit(repo, "add report")
    artifacts = tmp_path / "agent"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "research.7.cld"}),
        encoding="utf-8",
    )
    clear_agent_env(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_NAME", "research.7")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    batch_path = emit_commit(monkeypatch, repo, sha, hook("render"))

    assert batch_path is not None
    assert emitted_agent_names(batch_path) == ["research.7.cld"]


def test_unattributed_commit_still_runs_negative_only_agent_hooks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    (repo / "report.md").write_text("# report\n", encoding="utf-8")
    sha = commit(repo, "add report")
    clear_agent_env(monkeypatch)

    batch_path = emit_commit(
        monkeypatch,
        repo,
        sha,
        hook("render", agent_name_globs=("!research.*.cld",)),
    )

    assert batch_path is not None
    assert emitted_agent_names(batch_path) == [None]


def test_checkpointed_file_hook_step_never_refires(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    emit = MagicMock()
    monkeypatch.setattr("sase.file_hooks.producer.produce_commit_file_hooks", emit)
    workflow = CommitWorkflow({"message": "chore: done"}, "create_commit")
    checkpoint = CommitCheckpoint(
        method="create_commit",
        payload={"message": "chore: done"},
        cwd=str(tmp_path),
        completed_steps=["dispatch", "file_hooks"],
    )

    workflow._run_file_hooks(checkpoint, MagicMock())

    emit.assert_not_called()
    assert checkpoint.completed_steps.count("file_hooks") == 1


def test_sdd_commit_emits_once_with_its_sidecar_role(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    (repo / "report.md").write_text("# report\n", encoding="utf-8")
    file_hook = hook("render")
    monkeypatch.setattr(
        "sase.config.file_hooks.load_file_hooks",
        lambda: [file_hook],
    )
    stub_detached_spawn(monkeypatch)

    assert commit_sdd_files(
        repo,
        "add report",
        sidecar_role="research",
        record_commit_marker=False,
    )

    hook_audits = list_file_hook_audits()
    assert hook_audits
    assert hook_audits[0].producer == "sdd"
    assert hook_audits[0].sidecar_role == "research"
    assert hook_audits[0].outcome in {"batch_dispatched", "batch_already_present"}
    assert hook_audits[0].commit_sha == git(repo, "rev-parse", "HEAD")


def test_sdd_hook_fast_path_does_not_resolve_head_without_hooks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    head = MagicMock()
    monkeypatch.setattr("sase.config.file_hooks.load_file_hooks", list)
    monkeypatch.setattr("sase.sdd._commit_store._git_head_sha", head)

    _emit_sdd_file_hooks(tmp_path, sidecar_role="research")

    head.assert_not_called()


def test_deterministic_commit_batch_is_reused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    spawned: list[object] = []

    def fake_popen(argv: list[str], **kwargs: object) -> MagicMock:
        spawned.append(argv)
        return MagicMock()

    first = dispatch_file_hook_events(
        [event(repo)],
        hooks=[hook("render")],
        commit_sha="c" * 40,
        popen=fake_popen,
        producer="commit",
    )
    second = dispatch_file_hook_events(
        [event(repo)],
        hooks=[hook("render")],
        commit_sha="c" * 40,
        popen=fake_popen,
        producer="finalizer",
    )

    assert first.outcome == "batch_dispatched"
    assert second.outcome == "batch_already_present"
    assert second.batch_path == first.batch_path
    assert len(spawned) == 1
    assert [item.outcome for item in list_file_hook_audits()] == [
        "batch_already_present",
        "batch_dispatched",
    ]
