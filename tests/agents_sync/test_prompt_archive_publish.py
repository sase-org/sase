from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest
import sase_core_rs

from sase.agents_sync.git import run_git
from sase.agents_sync.models import ProjectTarget, SyncOutcome, TargetSelection
from sase.agents_sync.prompt_archive import publish as archive_publish
from sase.agents_sync.prompt_archive.publish import (
    publish_prompt_archive,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync._prompt_archive_helpers import (
    HostedLinks,
    make_record,
    write_manifest,
)
from tests.agents_sync.commit_publication_fixtures import git, setup_target


def test_publish_prompt_archive_missing_agents_target_is_nonfatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.resolve_publication_project_key",
        lambda *_args, **_kwargs: "proj",
    )
    monkeypatch.setattr(
        archive_publish,
        "resolve_sync_targets",
        lambda _projects: TargetSelection(
            (),
            (SyncOutcome("proj", "Project", skip_reason="agents sidecar disabled"),),
        ),
    )

    outcome = publish_prompt_archive(
        "worker",
        "a" * 40,
        commit_cwd=tmp_path,
    )

    assert not outcome.published
    assert outcome.skip_reason == "agents sidecar disabled"
    assert outcome.error is None


def test_publish_prompt_archive_without_artifacts_is_git_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, remote = setup_target(tmp_path)
    artifacts_dir = tmp_path / "runs/20260801130000"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(target.primary_checkout)})
    )
    (artifacts_dir / "raw_xprompt.md").write_text("Archive this prompt.\n")
    monkeypatch.setattr(
        archive_publish,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        archive_publish,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        archive_publish,
        "_hosted_resolver",
        lambda *_args: HostedLinks(),
    )
    monkeypatch.setattr("sase.file_references.format_with_prettier", lambda text: text)

    first = publish_prompt_archive(
        "worker",
        "a" * 40,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
    )
    second = publish_prompt_archive(
        "worker",
        "a" * 40,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
    )

    assert first.published and first.error is None
    assert not second.published and second.error is None
    verify = tmp_path / "verify-prompt"
    git(tmp_path, "clone", str(remote), str(verify))
    prompt = verify / "prompts/202608/alice.athena.worker.md"
    assert prompt.is_file()
    assert "Archive this prompt." in prompt.read_text()
    assert not (verify / "artifacts/202608").exists()


def _publish_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
) -> tuple[ProjectTarget, Path, Path]:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, remote = setup_target(tmp_path)
    git(target.sidecar_path, "config", "user.name", "Tests")
    git(target.sidecar_path, "config", "user.email", "tests@example.test")
    artifacts_dir = tmp_path / "runs/20260801130000"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(target.primary_checkout)})
    )
    (artifacts_dir / "raw_xprompt.md").write_text(prompt)
    monkeypatch.setattr(
        archive_publish,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        archive_publish,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        archive_publish,
        "_hosted_resolver",
        lambda *_args: HostedLinks(),
    )
    monkeypatch.setattr("sase.file_references.format_with_prettier", lambda text: text)
    return target, remote, artifacts_dir


def _publish_worker(target: ProjectTarget, artifacts_dir: Path):
    return publish_prompt_archive(
        "worker",
        "a" * 40,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
    )


def _stage_pool_artifact(
    target: ProjectTarget,
    artifacts_dir: Path,
    content: bytes,
) -> str:
    digest = hashlib.sha256(content).hexdigest()
    pool_name = sase_core_rs.prompt_artifact_pool_filename(digest, "diagram.png")
    pool = target.primary_checkout / ".sase/artifacts/pool" / pool_name
    pool.parent.mkdir(parents=True)
    pool.write_bytes(content)
    write_manifest(
        target.primary_checkout,
        [
            make_record(
                artifacts_dir=artifacts_dir,
                raw_ref="@~/diagram.png",
                label="diagram.png",
                sha256=digest,
                pool_relpath=f"pool/{pool_name}",
            )
        ],
    )
    return digest


def test_publish_prompt_archive_commits_pool_staged_object_with_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, remote, artifacts_dir = _publish_environment(
        tmp_path, monkeypatch, "Use @~/diagram.png.\n"
    )
    content = b"diagram bytes"
    digest = _stage_pool_artifact(target, artifacts_dir, content)
    object_relpath = sase_core_rs.artifact_object_relpath(digest)

    outcome = _publish_worker(target, artifacts_dir)

    assert outcome.published and outcome.error is None
    sidecar = target.sidecar_path
    assert (sidecar / object_relpath).read_bytes() == content
    assert git(sidecar, "status", "--porcelain", "-uall").stdout == ""
    assert git(sidecar, "ls-files", "--", object_relpath).stdout.strip() == (
        object_relpath
    )
    assert git(sidecar, "rev-list", "--count", "@{upstream}..HEAD").stdout == "0\n"
    verify = tmp_path / "verify-object"
    git(tmp_path, "clone", str(remote), str(verify))
    assert (verify / object_relpath).read_bytes() == content
    assert (
        "../../files/objects/"
        in (verify / "prompts/202608/alice.athena.worker.md").read_text()
    )


def test_publish_prompt_archive_publishes_incident_shape_orphans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, remote, artifacts_dir = _publish_environment(
        tmp_path, monkeypatch, "Archive this prompt.\n"
    )
    sidecar = target.sidecar_path
    orphans = {}
    for index in range(3):
        content = f"tale plan snapshot {index}\n".encode()
        digest = hashlib.sha256(content).hexdigest()
        relpath = sase_core_rs.artifact_object_relpath(digest)
        (sidecar / relpath).parent.mkdir(parents=True, exist_ok=True)
        (sidecar / relpath).write_bytes(content)
        orphans[relpath] = content
    assert git(sidecar, "status", "--porcelain", "-uall").stdout.count("??") == 3

    outcome = _publish_worker(target, artifacts_dir)

    assert outcome.published and outcome.error is None
    assert git(sidecar, "status", "--porcelain", "-uall").stdout == ""
    verify = tmp_path / "verify-orphans"
    git(tmp_path, "clone", str(remote), str(verify))
    for relpath, content in orphans.items():
        assert (verify / relpath).read_bytes() == content
    assert git(verify, "log", "--format=%s").stdout.splitlines()[:2] == [
        "chore(agents): archive prompt for alice.athena.worker",
        "chore(agents): publish pending prompt-archive objects",
    ]


def test_publish_prompt_archive_logs_warning_when_final_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A cleanup failure after a failed stage is warned, not silently dropped.

    Regression for the incident where the ``finally`` cleanup's return value
    was discarded, so a failed publication attempt's half-written scratch
    (orphaned by a concurrent ``index.lock`` collision) left no trace.
    """
    target, _remote, artifacts_dir = _publish_environment(
        tmp_path, monkeypatch, "Archive this prompt.\n"
    )
    reset_calls = {"count": 0}

    def lock_failure(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["git", "-C", str(cwd), *args],
            128,
            "",
            f"error: unable to create '{cwd}/.git/index.lock': File exists.",
        )

    def flaky_runner(
        cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        if op == "agents_sync.prompt_archive_stage":
            return lock_failure(cwd, args)
        if op == "agents_sync.prompt_archive_reset":
            reset_calls["count"] += 1
            if reset_calls["count"] > 1:
                return lock_failure(cwd, args)
        return run_git(cwd, args, network=network, op=op)

    caplog.set_level("WARNING")

    outcome = publish_prompt_archive(
        "worker",
        "a" * 40,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
        git_runner=flaky_runner,
    )

    assert outcome.queued is True
    assert outcome.error is not None
    assert "could not stage prompt archive" in outcome.error
    assert any(
        "Could not clean prompt archive worktree" in record.getMessage()
        for record in caplog.records
    )
