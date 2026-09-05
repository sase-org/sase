"""A prompt archive deferred by lock contention still reaches the sidecar.

``publish_prompt_archive`` is best-effort: when the agents sync lock is busy it
returns without writing anything. The durable agent-hood publication request it
enqueued is what carries the prompt forward, so the next full ``sase agent
sync`` has to rebuild the archive before it acknowledges that request.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync import git_sync
from sase.agents_sync.models import (
    ProjectTarget,
    TargetSelection,
)
from sase.agents_sync.prompt_archive import publish as archive_publish
from sase.agents_sync.prompt_archive.publish import publish_prompt_archive
from sase.agents_sync.publication_outbox import list_agent_publications
from sase.agents_sync.v2_models import V2PublicationCounts
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.commit_publication_fixtures import git, setup_target

_AGENT = "worker"
_GLOBAL_AGENT = "alice.athena.worker"
_REVISION = "a" * 40
_OWNER = AgentOwnerIdentity("alice", "athena")


class _HostedLinks:
    def agent_url(self, name: str) -> str:
        return f"https://example.test/agents/{name}"

    def plan_url(self, plan_ref: str) -> str:
        return f"https://example.test/plans/{plan_ref}"

    def blob_url_for_repository(self, _root: Path, revision: str, path: str) -> str:
        return f"https://example.test/blob/{revision}/{path}"

    def commit_url_for_repository(self, _root: Path, sha: str) -> str:
        return f"https://example.test/commit/{sha}"


def _artifacts_dir(tmp_path: Path, target: ProjectTarget) -> Path:
    artifacts_dir = tmp_path / "runs/20260801130000"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(target.primary_checkout)}),
        encoding="utf-8",
    )
    (artifacts_dir / "raw_xprompt.md").write_text(
        "Archive this prompt.\n",
        encoding="utf-8",
    )
    return artifacts_dir


def _stub_inventory(artifacts_dir: Path) -> SimpleNamespace:
    """One local run matching the queued request's lane and revision."""

    return SimpleNamespace(
        runs=(
            SimpleNamespace(
                local_name=_AGENT,
                global_name=_GLOBAL_AGENT,
                commits=(SimpleNamespace(sha=_REVISION),),
                source_label=str(artifacts_dir),
            ),
        ),
    )


@pytest.fixture
def deferred_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ProjectTarget, Path, Path]:
    """Defer one prompt archive on a busy lock, leaving its request queued."""

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, remote = setup_target(tmp_path)
    artifacts_dir = _artifacts_dir(tmp_path, target)
    monkeypatch.setattr(
        archive_publish,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        archive_publish,
        "require_agent_owner_identity",
        lambda: _OWNER,
    )
    monkeypatch.setattr(
        archive_publish,
        "_hosted_resolver",
        lambda *_args: _HostedLinks(),
    )
    monkeypatch.setattr("sase.file_references.format_with_prettier", lambda text: text)

    real_lock = git_sync.bounded_agents_lock
    contended = [True]

    @contextmanager
    def busy_once(path: Path, timeout_seconds: float):
        """Contend only the deferred publication, not the sync that follows."""

        if contended[0]:
            contended[0] = False
            yield False
            return
        with real_lock(path, timeout_seconds) as acquired:
            yield acquired

    monkeypatch.setattr(git_sync, "bounded_agents_lock", busy_once)
    outcome = publish_prompt_archive(
        _AGENT,
        _REVISION,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
    )

    assert not outcome.published
    assert outcome.queued
    assert outcome.error == "agents sync lock is busy"
    [queued] = list_agent_publications(target.project_key)
    assert queued.logical_key == (_GLOBAL_AGENT, _REVISION)
    verify = tmp_path / "verify-deferred"
    git(tmp_path, "clone", str(remote), str(verify))
    assert not (verify / "prompts").exists()
    return target, remote, artifacts_dir


def _stub_full_sync(
    monkeypatch: pytest.MonkeyPatch,
    target: ProjectTarget,
    artifacts_dir: Path,
) -> None:
    """Run the real sync transaction over stubbed hood publication."""

    monkeypatch.setattr(
        git_sync,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(git_sync, "require_agent_owner_identity", lambda: _OWNER)
    monkeypatch.setattr(
        git_sync,
        "build_project_hood_inventory",
        lambda *_args, **_kwargs: _stub_inventory(artifacts_dir),
    )

    def reconcile(_target: ProjectTarget, repo: Path, **_kwargs: object):
        page = repo / "agents" / _GLOBAL_AGENT / "README.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("# worker\n", encoding="utf-8")
        # The rest of the payload path set has to exist for staging to run.
        (repo / "README.md").write_text("# Agents\n", encoding="utf-8")
        (repo / "schema.json").write_text("{}\n", encoding="utf-8")
        for directory in ("users", "families"):
            (repo / directory).mkdir(exist_ok=True)
            (repo / directory / ".gitkeep").write_text("", encoding="utf-8")
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(git_sync, "reconcile_agent_hoods", reconcile)
    monkeypatch.setattr(
        archive_publish,
        "_hosted_resolver",
        lambda *_args: _HostedLinks(),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )


def test_full_sync_publishes_the_prompt_archive_a_busy_lock_deferred(
    deferred_publication: tuple[ProjectTarget, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target, remote, artifacts_dir = deferred_publication
    _stub_full_sync(monkeypatch, target, artifacts_dir)

    [outcome] = git_sync.sync_agents(("proj",))

    assert outcome.error is None
    assert outcome.pushed
    verify = tmp_path / "verify-synced"
    git(tmp_path, "clone", str(remote), str(verify))
    prompt = verify / "prompts/202608" / f"{_GLOBAL_AGENT}.md"
    assert prompt.is_file()
    assert "Archive this prompt." in prompt.read_text(encoding="utf-8")
    # The request is only acknowledged once both halves reached the sidecar.
    assert list_agent_publications("proj") == ()


def test_full_sync_keeps_the_request_queued_when_the_archive_cannot_be_rebuilt(
    deferred_publication: tuple[ProjectTarget, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target, remote, artifacts_dir = deferred_publication
    _stub_full_sync(monkeypatch, target, artifacts_dir)

    def explode(**_kwargs: object) -> None:
        raise RuntimeError("prompt pool is unreadable")

    monkeypatch.setattr(archive_publish, "prepare_prompt_archive", explode)

    [outcome] = git_sync.sync_agents(("proj",))

    assert outcome.error is None
    assert any("prompt pool is unreadable" in line for line in outcome.diagnostics)
    verify = tmp_path / "verify-failed"
    git(tmp_path, "clone", str(remote), str(verify))
    assert not (verify / "prompts").exists()
    # The agent page materialized, but the prompt did not, so the request stays
    # retryable instead of being acknowledged or retired.
    [remaining] = list_agent_publications("proj")
    assert remaining.attempts == 1
    assert not remaining.terminal
    assert "prompt pool is unreadable" in str(remaining.last_error)
