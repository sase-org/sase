"""Shared builders for deferred prompt-archive tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync import git_sync
from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.agents_sync.prompt_archive import publish as archive_publish
from sase.agents_sync.publication_outbox import list_agent_publications
from sase.agents_sync.v2_models import V2PublicationCounts
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.git_sync_fixtures import plant_fulfilled_publication

AGENT = "worker"
GLOBAL_AGENT = "alice.athena.worker"
REVISION = "a" * 40
OWNER = AgentOwnerIdentity("alice", "athena")


class HostedLinks:
    def agent_url(self, name: str) -> str:
        return f"https://example.test/agents/{name}"

    def plan_url(self, plan_ref: str) -> str:
        return f"https://example.test/plans/{plan_ref}"

    def blob_url_for_repository(self, _root: Path, revision: str, path: str) -> str:
        return f"https://example.test/blob/{revision}/{path}"

    def commit_url_for_repository(self, _root: Path, sha: str) -> str:
        return f"https://example.test/commit/{sha}"


def stub_inventory(artifacts_dir: Path) -> SimpleNamespace:
    """One local run matching the queued request's lane and revision."""

    return SimpleNamespace(
        runs=(
            SimpleNamespace(
                local_name=AGENT,
                global_name=GLOBAL_AGENT,
                commits=(SimpleNamespace(sha=REVISION),),
                source_label=str(artifacts_dir),
            ),
        ),
    )


def stub_full_sync(
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
    monkeypatch.setattr(git_sync, "require_agent_owner_identity", lambda: OWNER)
    monkeypatch.setattr(
        git_sync,
        "build_project_hood_inventory",
        lambda *_args, **_kwargs: stub_inventory(artifacts_dir),
    )

    def reconcile(_target: ProjectTarget, repo: Path, **_kwargs: object):
        pending = list_agent_publications(_target.project_key)
        for item in pending:
            plant_fulfilled_publication(
                repo,
                local_agent=item.local_agent,
                global_agent=item.global_agent,
                revision=item.primary_revision,
                local_hood=item.local_hood,
                has_prompt_file=True,
            )
        # The rest of the payload path set has to exist for staging to run.
        (repo / "README.md").write_text("# Agents\n", encoding="utf-8")
        (repo / "schema.json").write_text("{}\n", encoding="utf-8")
        for directory in ("users", "families", "sessions"):
            (repo / directory).mkdir(exist_ok=True)
            (repo / directory / ".gitkeep").write_text("", encoding="utf-8")
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(git_sync, "reconcile_agent_hoods", reconcile)
    monkeypatch.setattr(
        archive_publish,
        "_hosted_resolver",
        lambda *_args: HostedLinks(),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )
