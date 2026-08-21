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
from sase.config.file_hooks import FileHookConfig, FileHookFilters
from sase.core.artifact_file_types import ArtifactFile
from sase.file_hooks.audit import list_file_hook_audits, safe_file_hook_error_diagnostic
from sase.file_hooks.engine import (
    CapturedFileEvent,
    _derive_commit_file_events,
    capture_artifact_file_event,
    dispatch_file_hook_events,
    emit_artifact_file_hook_event,
    emit_commit_file_hook_events,
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
    agent_name_globs: tuple[str, ...] | None = None,
    causes: tuple[str, ...] | None = None,
) -> FileHookConfig:
    return FileHookConfig(
        name=name,
        description=None,
        command=command,
        timeout_seconds=timeout_seconds,
        filters=FileHookFilters(agent_name_globs=agent_name_globs, causes=causes),
    )


def _event(
    repo: Path,
    path: str = "report.md",
    *,
    agent_name: str | None = None,
    cause: str = "user",
) -> CapturedFileEvent:
    return CapturedFileEvent(
        abs_path=str(repo / path),
        repo_root=str(repo),
        project="sase",
        repo_kind="sidecar:research",
        sidecar_role="research",
        rel_path=path,
        op="ADD",
        cause=cause,
        agent_name=agent_name,
    )


def _clear_agent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)


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
    assert payload["runs"][0]["cause"] == "user"


def test_emit_records_non_user_cause_in_batch_payload(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    batch_path = emit_file_hook_events(
        [_event(repo, cause="referenced_by")],
        hooks=[_hook("render", causes=("referenced_by",))],
        commit_sha="b" * 40,
        popen=lambda *args, **kwargs: MagicMock(),
    )

    assert batch_path is not None
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    assert payload["runs"][0]["cause"] == "referenced_by"


def _emitted_agent_names(batch_path: Path) -> list[str | None]:
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    return [run["agent_name"] for run in payload["runs"]]


def _stub_detached_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real batch payload while never spawning a runner process."""
    original = dispatch_file_hook_events

    def wrapped(
        events: Any,
        **kwargs: Any,
    ) -> Any:
        if kwargs.get("popen") is None:
            kwargs["popen"] = lambda *args, **spawn_kwargs: MagicMock()
        return original(events, **kwargs)

    monkeypatch.setattr(
        "sase.file_hooks.engine.dispatch_file_hook_events",
        wrapped,
    )


def _audits() -> list[str]:
    return [item.outcome for item in list_file_hook_audits()]


def _emit_commit(
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    sha: str,
    hook: FileHookConfig,
) -> Path | None:
    _stub_detached_spawn(monkeypatch)
    return emit_commit_file_hook_events(repo_root=repo, commit_sha=sha, hooks=[hook])


def test_commit_batch_records_the_producing_agent_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    (repo / "report.md").write_text("# report\n", encoding="utf-8")
    (repo / "notes.md").write_text("# notes\n", encoding="utf-8")
    sha = _commit(repo, "add reports")
    _clear_agent_env(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_NAME", "research.7.final")

    batch_path = _emit_commit(monkeypatch, repo, sha, _hook("render"))

    assert batch_path is not None
    assert _emitted_agent_names(batch_path) == ["research.7.final"] * 2


def test_agent_meta_name_wins_over_the_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    (repo / "report.md").write_text("# report\n", encoding="utf-8")
    sha = _commit(repo, "add report")
    artifacts = tmp_path / "agent"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "research.7.cld"}),
        encoding="utf-8",
    )
    _clear_agent_env(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_NAME", "research.7")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    batch_path = _emit_commit(monkeypatch, repo, sha, _hook("render"))

    assert batch_path is not None
    assert _emitted_agent_names(batch_path) == ["research.7.cld"]


def test_unattributed_commit_still_runs_negative_only_agent_hooks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    (repo / "report.md").write_text("# report\n", encoding="utf-8")
    sha = _commit(repo, "add report")
    _clear_agent_env(monkeypatch)

    batch_path = _emit_commit(
        monkeypatch,
        repo,
        sha,
        _hook("render", agent_name_globs=("!research.*.cld",)),
    )

    assert batch_path is not None
    assert _emitted_agent_names(batch_path) == [None]


def test_excluded_agent_produces_no_batch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _clear_agent_env(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_NAME", "research.7.cld")

    result = dispatch_file_hook_events(
        [_event(repo, agent_name="research.7.cld")],
        hooks=[_hook("render", agent_name_globs=("!research.*.cld",))],
        popen=lambda *args, **kwargs: MagicMock(),
        producer="commit",
    )

    assert result.outcome == "no_match"
    assert result.batch_path is None
    assert result.audit_path is not None
    assert "no_match" in _audits()


def test_artifact_capture_and_emit_preserve_the_agent_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    source = repo / "report.md"
    source.write_text("# report\n", encoding="utf-8")
    stored = tmp_path / "stored.md"
    stored.write_text("# report\n", encoding="utf-8")
    _clear_agent_env(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_NAME", "research.7.final")
    monkeypatch.setattr(
        "sase.file_hooks.engine.get_all_file_hooks",
        lambda: [_hook("render")],
    )
    _stub_detached_spawn(monkeypatch)

    captured = capture_artifact_file_event(source)
    assert captured.agent_name == "research.7.final"

    batch_path = emit_artifact_file_hook_event(captured, stored)

    assert batch_path is not None
    assert _emitted_agent_names(batch_path) == ["research.7.final"]


def test_detached_spawn_failure_is_non_gating_and_leaves_no_pending_batch(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)

    result = dispatch_file_hook_events(
        [_event(repo)],
        hooks=[_hook("render")],
        popen=lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("no spawn token=super-secret")
        ),
        producer="commit",
    )

    assert result.outcome == "producer_error"
    assert result.batch_path is None
    assert result.error is not None
    assert "OSError" in result.error
    assert "super-secret" not in result.error
    assert "token=<redacted>" in result.error
    batches = Path(os.environ["SASE_HOME"]).expanduser() / "file_hooks" / "batches"
    assert list(batches.glob("*.json")) == []
    notifications = [
        notification
        for notification in load_notifications()
        if notification.sender == "file-hooks"
    ]
    assert len(notifications) == 1
    assert is_error(notifications[0])
    assert notifications[0].files[0] == result.audit_path


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


def test_pruning_removes_only_expired_audit_files(tmp_path: Path) -> None:
    root = Path(os.environ["SASE_HOME"]).expanduser() / "file_hooks"
    old = root / "runs" / "old.log"
    recent = root / "logs" / "recent.log"
    old_audit = root / "audit" / "old.json"
    old.parent.mkdir(parents=True)
    recent.parent.mkdir(parents=True)
    old_audit.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    recent.write_text("recent", encoding="utf-8")
    old_audit.write_text("{}\n", encoding="utf-8")
    now = time.time()
    os.utime(old, (now - 100, now - 100))
    os.utime(old_audit, (now - 100, now - 100))

    removed = _prune_file_hook_state(now=now, retention_seconds=50)

    assert set(removed) == {old, old_audit}
    assert not old.exists()
    assert not old_audit.exists()
    assert recent.exists()


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
    repo = _init_repo(tmp_path)
    (repo / "report.md").write_text("# report\n", encoding="utf-8")
    hook = _hook("render")
    monkeypatch.setattr(
        "sase.config.file_hooks.load_file_hooks",
        lambda: [hook],
    )
    _stub_detached_spawn(monkeypatch)

    assert commit_sdd_files(
        repo,
        "add report",
        sidecar_role="research",
        record_commit_marker=False,
    )

    audits = list_file_hook_audits()
    assert audits
    assert audits[0].producer == "sdd"
    assert audits[0].sidecar_role == "research"
    assert audits[0].outcome in {"batch_dispatched", "batch_already_present"}
    assert audits[0].commit_sha == _git(repo, "rev-parse", "HEAD")


def test_sdd_hook_fast_path_does_not_resolve_head_without_hooks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    head = MagicMock()
    monkeypatch.setattr("sase.config.file_hooks.load_file_hooks", list)
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
    stored.write_text("# source\n", encoding="utf-8")
    captured = _event(tmp_path, "source.md")
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "agent"))
    monkeypatch.setattr(
        "sase.file_hooks.producer.load_file_hooks",
        lambda: [_hook("artifact")],
    )
    monkeypatch.setattr(
        "sase.file_hooks.producer.capture_artifact_file_event",
        lambda path: captured,
    )
    _stub_detached_spawn(monkeypatch)
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
    audits = list_file_hook_audits()
    assert audits
    assert audits[0].outcome == "batch_dispatched"
    assert audits[0].producer == "artifact"
    assert Path(audits[0].events[0]["abs_path"]) == stored
    assert audits[0].batch_path is not None
    payload = json.loads(Path(audits[0].batch_path).read_text(encoding="utf-8"))
    assert payload["runs"][0]["abs_path"] == str(stored)


def test_dispatch_records_no_hooks_without_a_batch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    result = dispatch_file_hook_events([_event(repo)], hooks=[])

    assert result.outcome == "no_hooks"
    assert result.batch_path is None
    assert result.audit_path is not None
    assert list_file_hook_audits()[0].outcome == "no_hooks"
    notifications = [
        notification
        for notification in load_notifications()
        if notification.sender == "file-hooks"
    ]
    assert notifications == []


def test_deterministic_commit_batch_is_reused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    spawned: list[object] = []

    def fake_popen(argv: list[str], **kwargs: object) -> MagicMock:
        spawned.append(argv)
        return MagicMock()

    first = dispatch_file_hook_events(
        [_event(repo)],
        hooks=[_hook("render")],
        commit_sha="c" * 40,
        popen=fake_popen,
        producer="commit",
    )
    second = dispatch_file_hook_events(
        [_event(repo)],
        hooks=[_hook("render")],
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


def test_safe_error_diagnostic_redacts_secrets_and_truncates() -> None:
    class TokenError(RuntimeError):
        pass

    short = safe_file_hook_error_diagnostic(TokenError("api_key=abcd1234 leftover"))
    assert "api_key=<redacted>" in short
    assert "abcd1234" not in short
    long = safe_file_hook_error_diagnostic(RuntimeError("x" * 800))
    assert long.endswith("...")
    assert len(long) == 500


def test_notification_failure_does_not_hide_producer_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    monkeypatch.setattr(
        "sase.notifications.store.append_notification",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("notify boom")),
    )

    result = dispatch_file_hook_events(
        [_event(repo)],
        hooks=[_hook("render")],
        popen=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no spawn")),
        producer="artifact",
    )

    assert result.outcome == "producer_error"
    assert result.audit_path is not None
    assert Path(result.audit_path).is_file()


def test_artifact_create_survives_producer_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("# source\n", encoding="utf-8")
    stored = tmp_path / "stored.md"
    stored.write_text("# source\n", encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "agent"))
    monkeypatch.setattr(
        "sase.file_hooks.producer.load_file_hooks",
        lambda: (_ for _ in ()).throw(RuntimeError("config exploded")),
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
    audits = list_file_hook_audits()
    assert audits[0].outcome == "producer_error"
    notifications = [
        notification
        for notification in load_notifications()
        if notification.sender == "file-hooks"
    ]
    assert notifications and is_error(notifications[0])
