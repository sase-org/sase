"""Integration regression for research-highlights dispatch reliability."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.artifact_cli.create import handle_create
from sase.config.file_hooks import FileHookConfig, FileHookFilters, _load_file_hooks
from sase.config.layers import ConfigLayer
from sase.file_hooks.audit import file_hooks_root, list_file_hook_audits
from sase.file_hooks.engine import dispatch_file_hook_events
from sase.file_hooks.producer import (
    capture_artifact_source,
    produce_artifact_file_hook,
    produce_commit_file_hooks,
    reconcile_commit_file_hooks,
)
from sase.notifications.priority import is_error
from sase.notifications.store import load_notifications
from sase.vcs_provider import get_vcs_provider
from sase.workflows.commit.checkpoint import CommitCheckpoint
from sase.workflows.commit.workflow import CommitWorkflow


_REPORT = (
    "202608/finalizer_integrity_and_capabilities/"
    "finalizer_integrity_and_capabilities.md"
)
_DRAFT = (
    "202608/finalizer_integrity_and_capabilities/"
    "finalizer_integrity_and_capabilities__a.md"
)


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


def _research_highlights_hook(
    command: str = "true",
    *,
    producers: tuple[str, ...] | None = None,
) -> FileHookConfig:
    return FileHookConfig(
        name="research-highlights",
        description="Render new research reports into Highlights PDFs.",
        command=command,
        timeout_seconds=120,
        filters=FileHookFilters(
            projects=("sase",),
            sidecars=("research",),
            path_globs=("20*/**/*.md", "!20*/*/*__*.md"),
            agent_name_globs=("!research.*.cld", "!research.*.cdx"),
            ops=("ADD",),
            producers=producers,  # type: ignore[arg-type]
        ),
        source_layer="user",
    )


def _materialize_research_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "sase_7"
    research = workspace / "sase" / "repos" / "research"
    research.mkdir(parents=True)
    _git(research, "init")
    _git(research, "config", "user.email", "hooks@example.com")
    _git(research, "config", "user.name", "Hook Tests")
    _git(research, "remote", "add", "origin", str(research))
    report = research / _REPORT
    report.parent.mkdir(parents=True)
    report.write_text("# consolidated report\n", encoding="utf-8")
    draft = research / _DRAFT
    draft.write_text("# draft\n", encoding="utf-8")
    return workspace, research


def _configure_research_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    workspace: Path,
) -> Path:
    project_file = tmp_path / "projects" / "sase" / "sase.sase"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("PROJECT_NAME: sase\n", encoding="utf-8")
    artifacts = tmp_path / "agent"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "research.0v.final", "workspace_dir": str(workspace)}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "research.0v.final")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(project_file))
    monkeypatch.setenv("SASE_PROJECT_DIR", str(workspace))
    return artifacts


def _install_hook(
    monkeypatch: pytest.MonkeyPatch,
    hook: FileHookConfig,
) -> None:
    monkeypatch.setattr(
        "sase.config.file_hooks.load_file_hooks",
        lambda: [hook],
    )
    monkeypatch.setattr(
        "sase.file_hooks.producer.load_file_hooks",
        lambda: [hook],
    )
    monkeypatch.setattr(
        "sase.file_hooks.engine.get_all_file_hooks",
        lambda: [hook],
    )


def _install_research_highlights_use(
    monkeypatch: pytest.MonkeyPatch,
    *,
    command: str,
) -> list[FileHookConfig]:
    layers = [
        ConfigLayer(
            name="user",
            path=None,
            exists=True,
            list_strategy="replace",
            data={
                "file_hooks": [
                    {
                        "use": "sase-research-artifacts@research-highlights",
                        "command": command,
                    }
                ]
            },
        )
    ]
    monkeypatch.setattr(
        "sase.config.file_hooks.current_config_token",
        lambda: ("research-highlights-e2e",),
    )
    monkeypatch.setattr("sase.config.file_hooks.load_config_layers", lambda: layers)
    monkeypatch.setattr("sase.xprompt.loader.detect_project", lambda: "sase")
    return _load_file_hooks()


def _bob_dry_run(md_file: Path, bob_dir: Path) -> str:
    bob_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "bob",
            "highlights",
            "create",
            "--include-id",
            "--dry-run",
            "--bob-dir",
            str(bob_dir),
            str(md_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _dry_run_field(output: str, key: str) -> str:
    prefix = f"{key}: "
    for line in output.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix)
    raise AssertionError(f"bob dry-run output missing {key!r}:\n{output}")


def _stub_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[list[str], dict[str, Any]]]:
    spawned: list[tuple[list[str], dict[str, Any]]] = []
    original = dispatch_file_hook_events

    def fake_popen(argv: list[str], **kwargs: Any) -> MagicMock:
        spawned.append((argv, kwargs))
        return MagicMock()

    def wrapped(events: Any, **kwargs: Any) -> Any:
        if kwargs.get("popen") is None:
            kwargs["popen"] = fake_popen
        return original(events, **kwargs)

    monkeypatch.setattr(
        "sase.file_hooks.engine.dispatch_file_hook_events",
        wrapped,
    )
    return spawned


def test_committed_only_hook_skips_artifact_and_reuses_commit_batch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, research = _materialize_research_workspace(tmp_path)
    _configure_research_agent(monkeypatch, tmp_path, workspace)
    hook = _research_highlights_hook(producers=("commit", "sdd", "finalizer"))
    _install_hook(monkeypatch, hook)
    spawned = _stub_spawn(monkeypatch)
    source = research / _REPORT
    stored = tmp_path / "finalizer_integrity_and_capabilities-ad048d84997e.md"
    stored.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    captured = capture_artifact_source(source)
    assert captured is not None

    artifact = produce_artifact_file_hook(captured, stored)
    assert artifact.outcome == "no_match"
    assert artifact.producer == "artifact"
    assert artifact.batch_path is None
    assert artifact.matched_hook_names == ()
    assert spawned == []
    assert list((file_hooks_root() / "batches").glob("*.json")) == []

    (research / _DRAFT).unlink()
    sha = _commit(research, "add consolidated report")
    commit = produce_commit_file_hooks(
        repo_root=research,
        commit_sha=sha,
        sidecar_role="research",
        agent_name="research.0v.final",
        workspace_dir=workspace,
        producer="commit",
        hooks=[hook],
    )
    assert commit.outcome == "batch_dispatched"
    assert commit.matched_hook_names == ("research-highlights",)
    assert len(spawned) == 1
    payload = json.loads(Path(commit.batch_path or "").read_text(encoding="utf-8"))
    assert [run["rel_path"] for run in payload["runs"]] == [_REPORT]
    assert [run["abs_path"] for run in payload["runs"]] == [str(source)]

    reused = reconcile_commit_file_hooks(
        repo_root=research,
        commit_sha=sha,
        workspace_dir=workspace,
        sidecar_role="research",
        agent_name="research.0v.final",
    )
    assert reused.outcome == "batch_already_present"
    assert reused.producer == "finalizer"
    assert reused.batch_path == commit.batch_path
    assert len(spawned) == 1


def test_artifact_create_dispatches_consolidated_research_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, research = _materialize_research_workspace(tmp_path)
    _configure_research_agent(monkeypatch, tmp_path, workspace)
    hook = _research_highlights_hook()
    _install_hook(monkeypatch, hook)
    spawned = _stub_spawn(monkeypatch)
    source = research / _REPORT
    stored = tmp_path / "stored-report.md"
    stored.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    from sase.core.artifact_file_types import ArtifactFile

    monkeypatch.setattr(
        "sase.artifact_cli.create.store_explicit_artifact_file",
        lambda *args, **kwargs: ArtifactFile(
            id="explicit:research",
            label="finalizer_integrity_and_capabilities.md",
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
    assert audits[0].outcome == "batch_dispatched"
    assert audits[0].producer == "artifact"
    assert audits[0].matched_hook_names == ("research-highlights",)
    assert audits[0].agent_name == "research.0v.final"
    assert audits[0].sidecar_role == "research"
    assert audits[0].events[0]["rel_path"] == _REPORT
    assert Path(audits[0].events[0]["abs_path"]) == stored
    assert spawned


def test_commit_workflow_dispatches_research_sidecar_add(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, research = _materialize_research_workspace(tmp_path)
    _configure_research_agent(monkeypatch, tmp_path, workspace)
    hook = _research_highlights_hook()
    _install_hook(monkeypatch, hook)
    spawned = _stub_spawn(monkeypatch)
    (research / _DRAFT).unlink()
    sha = _commit(research, "add consolidated report")
    workflow = CommitWorkflow({"message": "docs: report"}, "create_commit")
    checkpoint = CommitCheckpoint(
        method="create_commit",
        payload={"message": "docs: report"},
        cwd=str(research),
        project_file=str(tmp_path / "projects" / "sase" / "sase.sase"),
    )
    provider = get_vcs_provider(str(research))

    workflow._run_file_hooks(checkpoint, provider)

    audits = list_file_hook_audits()
    assert audits[0].outcome == "batch_dispatched"
    assert audits[0].producer == "commit"
    assert audits[0].commit_sha == sha
    assert audits[0].matched_hook_names == ("research-highlights",)
    assert audits[0].agent_name == "research.0v.final"
    assert {event["rel_path"] for event in audits[0].events} == {_REPORT}
    payload = json.loads(Path(audits[0].batch_path or "").read_text(encoding="utf-8"))
    assert [run["rel_path"] for run in payload["runs"]] == [_REPORT]
    assert spawned
    assert "file_hooks" in checkpoint.completed_steps


def test_finalizer_reconciliation_reuses_and_repairs_commit_batches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, research = _materialize_research_workspace(tmp_path)
    _configure_research_agent(monkeypatch, tmp_path, workspace)
    hook = _research_highlights_hook()
    _install_hook(monkeypatch, hook)
    spawned = _stub_spawn(monkeypatch)
    (research / _DRAFT).unlink()
    sha = _commit(research, "add consolidated report")

    first = produce_commit_file_hooks(
        repo_root=research,
        commit_sha=sha,
        sidecar_role="research",
        agent_name="research.0v.final",
        workspace_dir=workspace,
        producer="commit",
        hooks=[hook],
    )
    reused = reconcile_commit_file_hooks(
        repo_root=research,
        commit_sha=sha,
        workspace_dir=workspace,
        sidecar_role="research",
        agent_name="research.0v.final",
    )
    assert first.outcome == "batch_dispatched"
    assert reused.outcome == "batch_already_present"
    assert reused.batch_path == first.batch_path
    assert len(spawned) == 1

    Path(first.batch_path or "").unlink()
    repaired = reconcile_commit_file_hooks(
        repo_root=research,
        commit_sha=sha,
        workspace_dir=workspace,
        sidecar_role="research",
        agent_name="research.0v.final",
    )
    assert repaired.outcome == "batch_dispatched"
    assert repaired.batch_path is not None
    assert Path(repaired.batch_path).is_file()
    assert len(spawned) == 2


def test_draft_reports_are_recorded_filter_misses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, research = _materialize_research_workspace(tmp_path)
    _configure_research_agent(monkeypatch, tmp_path, workspace)
    hook = _research_highlights_hook()
    _install_hook(monkeypatch, hook)
    spawned = _stub_spawn(monkeypatch)
    captured = capture_artifact_source(research / _DRAFT)
    assert captured is not None

    result = dispatch_file_hook_events(
        [captured],
        hooks=[hook],
        producer="artifact",
    )

    assert result.outcome == "no_match"
    assert result.batch_path is None
    assert result.events[0]["rel_path"] == _DRAFT
    assert spawned == []
    notifications = [
        notification
        for notification in load_notifications()
        if notification.sender == "file-hooks"
    ]
    assert notifications == []


def test_injected_persistence_failure_notifies_without_gating_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, research = _materialize_research_workspace(tmp_path)
    _configure_research_agent(monkeypatch, tmp_path, workspace)
    hook = _research_highlights_hook()
    _install_hook(monkeypatch, hook)
    _stub_spawn(monkeypatch)
    (research / _DRAFT).unlink()
    sha = _commit(research, "add consolidated report")
    monkeypatch.setattr(
        "sase.file_hooks.engine._atomic_create_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    result = produce_commit_file_hooks(
        repo_root=research,
        commit_sha=sha,
        sidecar_role="research",
        agent_name="research.0v.final",
        workspace_dir=workspace,
        producer="commit",
        hooks=[hook],
    )

    assert result.outcome == "producer_error"
    assert result.error is not None
    assert "OSError" in result.error
    notifications = [
        notification
        for notification in load_notifications()
        if notification.sender == "file-hooks"
    ]
    assert notifications and is_error(notifications[0])


def test_installed_provider_skips_artifact_and_reuses_commit_batch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: Any,
) -> None:
    pytest.importorskip("sase_research_artifacts")
    workspace, research = _materialize_research_workspace(tmp_path)
    _configure_research_agent(monkeypatch, tmp_path, workspace)
    hooks = _install_research_highlights_use(monkeypatch, command="true")
    if not hooks:
        pytest.skip("research-highlights provider did not resolve")
    hook = hooks[0]
    if hook.filters.producers != ("commit", "sdd", "finalizer"):
        pytest.skip("installed plugin does not restrict producers")
    assert hook.name == "research-highlights"
    assert hook.command == "true"
    assert hook.filters.sidecars == ("research",)
    assert hook.filters.ops == ("ADD",)
    spawned = _stub_spawn(monkeypatch)
    source = research / _REPORT

    args = argparse.Namespace(
        path=str(source),
        label=None,
        kind=None,
        move=False,
        bead=None,
    )
    assert handle_create(args) == 0
    created = capsys.readouterr().out
    stored_line = next(
        line for line in created.splitlines() if line.startswith("path: ")
    )
    stored = Path(stored_line.removeprefix("path: "))
    assert stored.is_file()
    assert stored.name.startswith(f"{source.stem}-")
    assert stored.suffix == ".md"
    digest = stored.stem.removeprefix(f"{source.stem}-")
    assert len(digest) == 12
    assert digest.isalnum()
    audits = list_file_hook_audits()
    assert audits[0].outcome == "no_match"
    assert audits[0].producer == "artifact"
    assert audits[0].matched_hook_names == ()
    assert audits[0].batch_path is None
    assert spawned == []
    assert list((file_hooks_root() / "batches").glob("*.json")) == []

    (research / _DRAFT).unlink()
    sha = _commit(research, "add consolidated report")
    commit = produce_commit_file_hooks(
        repo_root=research,
        commit_sha=sha,
        sidecar_role="research",
        agent_name="research.0v.final",
        workspace_dir=workspace,
        producer="commit",
    )
    assert commit.outcome == "batch_dispatched"
    assert commit.matched_hook_names == ("research-highlights",)
    assert len(spawned) == 1
    payload = json.loads(Path(commit.batch_path or "").read_text(encoding="utf-8"))
    assert [run["rel_path"] for run in payload["runs"]] == [_REPORT]
    assert [run["abs_path"] for run in payload["runs"]] == [str(source)]
    assert source.name == Path(payload["runs"][0]["abs_path"]).name

    reused = reconcile_commit_file_hooks(
        repo_root=research,
        commit_sha=sha,
        workspace_dir=workspace,
        sidecar_role="research",
        agent_name="research.0v.final",
    )
    assert reused.outcome == "batch_already_present"
    assert reused.producer == "finalizer"
    assert reused.batch_path == commit.batch_path
    assert len(spawned) == 1


@pytest.mark.skipif(shutil.which("bob") is None, reason="bob CLI not installed")
def test_bob_dry_run_canonical_report_has_no_digest_suffix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bob_dir = tmp_path / "bob"
    monkeypatch.setenv("BOB_DIR", str(bob_dir))
    report = tmp_path / "canonical_highlights_probe.md"
    report.write_text("# Canonical Highlights probe\n", encoding="utf-8")
    digest_copy = tmp_path / "canonical_highlights_probe-ad048d84997e.md"
    digest_copy.write_text(report.read_text(encoding="utf-8"), encoding="utf-8")

    canonical = _bob_dry_run(report, bob_dir)
    assert _dry_run_field(canonical, "pdf").endswith("canonical_highlights_probe.pdf")
    assert _dry_run_field(canonical, "id") == "canonical_highlights_probe"
    assert "writes: none" in canonical

    suffixed = _bob_dry_run(digest_copy, bob_dir)
    assert _dry_run_field(suffixed, "pdf").endswith(
        "canonical_highlights_probe-ad048d84997e.pdf"
    )
    assert _dry_run_field(suffixed, "id") == "canonical_highlights_probe-ad048d84997e"
    assert "writes: none" in suffixed
    assert list(bob_dir.rglob("*.pdf")) == []
