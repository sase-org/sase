"""Execution-engine tests for commit- and artifact-time file hooks."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.artifact_cli.create import handle_create
from sase.config.file_hooks import FileHookConfig
from sase.core.artifact_file_types import ArtifactFile
from sase.file_hooks.engine import (
    CapturedFileEvent,
    _derive_commit_file_events,
    capture_artifact_file_event,
    emit_file_hook_events,
)
from sase.file_hooks.runner import _prune_file_hook_state, execute_batch
from sase.notifications.priority import is_error
from sase.notifications.store import load_notifications
from sase.vcs_provider import get_vcs_provider
from sase.sdd._commit_store import _emit_sdd_file_hooks, commit_sdd_files
from sase.workflows.commit.checkpoint import CommitCheckpoint
from sase.workflows.commit.workflow import CommitWorkflow


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "hooks@example.com")
    _git(repo, "config", "user.name", "Hook Tests")
    _git(repo, "remote", "add", "origin", str(repo))
    return repo


def _hook(
    name: str,
    command: str = "true",
    *,
    timeout_seconds: float = 120,
) -> FileHookConfig:
    return FileHookConfig(
        name=name,
        description=None,
        command=command,
        projects=None,
        sidecars=None,
        globs=None,
        ops=None,
        timeout_seconds=timeout_seconds,
    )


def _event(repo: Path, path: str = "report.md") -> CapturedFileEvent:
    return CapturedFileEvent(
        abs_path=str(repo / path),
        repo_root=str(repo),
        project="sase",
        repo_kind="sidecar:research",
        sidecar_role="research",
        rel_path=path,
        op="ADD",
    )


def test_commit_event_derivation_handles_root_add_modify_delete_and_rename(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    (repo / "old.txt").write_text("one\n", encoding="utf-8")
    root_sha = _commit(repo, "root")
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

    _git(repo, "mv", "old.txt", "renamed.txt")
    (repo / "added.txt").write_text("added\n", encoding="utf-8")
    rename_sha = _commit(repo, "rename and add")
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
    changed_sha = _commit(repo, "modify and remove")
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


def test_emit_persists_versioned_batch_and_detaches_once_per_commit(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    spawned: list[tuple[list[str], dict[str, Any]]] = []

    def fake_popen(argv: list[str], **kwargs: Any) -> MagicMock:
        spawned.append((argv, kwargs))
        return MagicMock()

    first = emit_file_hook_events(
        [_event(repo)],
        hooks=[_hook("render")],
        commit_sha="a" * 40,
        popen=fake_popen,
    )
    second = emit_file_hook_events(
        [_event(repo)],
        hooks=[_hook("render")],
        commit_sha="a" * 40,
        popen=fake_popen,
    )

    assert first is not None
    assert second == first
    assert len(spawned) == 1
    argv, kwargs = spawned[0]
    assert argv[-3:] == ["file-hook", "exec-batch", str(first)]
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] is subprocess.DEVNULL
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["commit_sha"] == "a" * 40
    assert payload["runs"][0]["command"] == "true"
    assert payload["runs"][0]["abs_path"] == str(repo / "report.md")


def test_detached_spawn_failure_is_non_gating_and_leaves_no_pending_batch(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)

    result = emit_file_hook_events(
        [_event(repo)],
        hooks=[_hook("render")],
        popen=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no spawn")),
    )

    assert result is None
    batches = Path(os.environ["SASE_HOME"]).expanduser() / "file_hooks" / "batches"
    assert list(batches.glob("*.json")) == []


def test_runner_reports_success_failure_and_timeout_and_is_idempotent(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    target = repo / "report.md"
    target.write_text("# report\n", encoding="utf-8")
    python = shlex.quote(sys.executable)
    success_code = shlex.quote("import sys; print(sys.argv[-1])")
    failure_code = shlex.quote("print('bad'); raise SystemExit(3)")
    timeout_code = shlex.quote("import time; time.sleep(1)")
    hooks = [
        _hook("success", f"{python} -c {success_code}"),
        _hook("failure", f"{python} -c {failure_code}"),
        _hook(
            "timeout",
            f"{python} -c {timeout_code}",
            timeout_seconds=0.01,
        ),
    ]
    batch_path = emit_file_hook_events(
        [_event(repo)],
        hooks=hooks,
        popen=lambda *args, **kwargs: MagicMock(),
    )
    assert batch_path is not None

    assert execute_batch(batch_path) == 0
    assert execute_batch(batch_path) == 0

    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    assert payload["status"] == "finished"
    assert [run["status"] for run in payload["runs"]] == ["finished"] * 3
    assert payload["runs"][0]["exit_code"] == 0
    assert payload["runs"][1]["exit_code"] == 3
    assert "timeout" in payload["runs"][2]["failure"]

    notifications = [
        notification
        for notification in load_notifications()
        if notification.sender == "file-hooks"
    ]
    assert len(notifications) == 3
    success = next(n for n in notifications if "success" in n.tags)
    failure = next(n for n in notifications if "failure" in n.tags)
    timeout = next(n for n in notifications if "timeout" in n.tags)
    assert success.notes[0] == "✅ success: report.md"
    assert Path(success.files[0]).read_text(encoding="utf-8").endswith(f"{target}\n")
    assert is_error(failure)
    assert failure.action_data["error_report_path"] == failure.files[0]
    assert is_error(timeout)


def test_runner_timeout_kills_hook_descendants(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    target = repo / "report.md"
    target.write_text("# report\n", encoding="utf-8")
    late_write = repo / "late-write.txt"
    child_code = (
        "import pathlib,time; time.sleep(0.25); "
        f"pathlib.Path({str(late_write)!r}).write_text('too late')"
    )
    parent_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(5)"
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(parent_code)}"
    batch_path = emit_file_hook_events(
        [_event(repo)],
        hooks=[_hook("timeout-tree", command, timeout_seconds=0.05)],
        popen=lambda *args, **kwargs: MagicMock(),
    )
    assert batch_path is not None

    assert execute_batch(batch_path) == 0
    time.sleep(0.4)

    assert not late_write.exists()


def test_pruning_removes_only_expired_audit_files(tmp_path: Path) -> None:
    root = Path(os.environ["SASE_HOME"]).expanduser() / "file_hooks"
    old = root / "runs" / "old.log"
    recent = root / "logs" / "recent.log"
    old.parent.mkdir(parents=True)
    recent.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    recent.write_text("recent", encoding="utf-8")
    now = time.time()
    os.utime(old, (now - 100, now - 100))

    removed = _prune_file_hook_state(now=now, retention_seconds=50)

    assert removed == [old]
    assert not old.exists()
    assert recent.exists()


def test_checkpointed_file_hook_step_never_refires(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    emit = MagicMock()
    monkeypatch.setattr("sase.file_hooks.emit_commit_file_hook_events", emit)
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
    repo = _init_repo(tmp_path)
    (repo / "report.md").write_text("# report\n", encoding="utf-8")
    hook = _hook("render")
    emit = MagicMock()
    monkeypatch.setattr(
        "sase.config.file_hooks.get_all_file_hooks",
        lambda: [hook],
    )
    monkeypatch.setattr("sase.file_hooks.emit_commit_file_hook_events", emit)

    assert commit_sdd_files(
        repo,
        "add report",
        sidecar_role="research",
        record_commit_marker=False,
    )

    emit.assert_called_once_with(
        repo_root=repo,
        commit_sha=_git(repo, "rev-parse", "HEAD"),
        sidecar_role="research",
        hooks=[hook],
    )


def test_sdd_hook_fast_path_does_not_resolve_head_without_hooks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    head = MagicMock()
    monkeypatch.setattr("sase.config.file_hooks.get_all_file_hooks", list)
    monkeypatch.setattr("sase.sdd._commit_store._git_head_sha", head)

    _emit_sdd_file_hooks(tmp_path, sidecar_role="research")

    head.assert_not_called()


def test_artifact_capture_outside_a_repo_matches_just_the_basename(
    tmp_path: Path,
) -> None:
    source = tmp_path / "outside.md"
    source.write_text("# outside\n", encoding="utf-8")

    event = capture_artifact_file_event(source)

    assert event.abs_path == str(source)
    assert event.repo_root == str(tmp_path)
    assert event.rel_path == "outside.md"
    assert event.repo_kind == "external:untracked"
    assert event.sidecar_role is None
    assert event.op == "ADD"


def test_artifact_create_emits_stored_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("# source\n", encoding="utf-8")
    stored = tmp_path / "stored.md"
    captured = _event(tmp_path, "source.md")
    emitted: list[tuple[CapturedFileEvent, str]] = []
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "agent"))
    monkeypatch.setattr(
        "sase.config.file_hooks.get_all_file_hooks",
        lambda: [_hook("artifact")],
    )
    monkeypatch.setattr(
        "sase.file_hooks.capture_artifact_file_event",
        lambda path: captured,
    )
    monkeypatch.setattr(
        "sase.file_hooks.emit_artifact_file_hook_event",
        lambda event, path: emitted.append((event, str(path))),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.create.store_explicit_artifact_file",
        lambda *args, **kwargs: ArtifactFile(
            id="explicit:test",
            label="source.md",
            kind="markdown",
            path=str(stored),
        ),
    )
    args = argparse.Namespace(
        path=str(source),
        label=None,
        kind=None,
        move=False,
        bead=None,
    )

    assert handle_create(args) == 0
    assert emitted == [(captured, str(stored))]
