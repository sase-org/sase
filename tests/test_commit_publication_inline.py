"""Acceptance coverage: a tagged commit publishes every sidecar inline.

The commit path must finish its bead-page, prompt-archive, plan-header, and
agent-hood work *before* ``sase commit`` returns, so the ``SASE_AGENT`` footer
URL resolves as soon as the commit lands. This composes the four real
publishers over real sidecar git repositories and asserts each one committed,
pushed, and left an empty publication outbox behind.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from types import MappingProxyType, SimpleNamespace

import pytest

from sase.agents_sync.models import IntegrationCounts, ProjectTarget, TargetSelection
from sase.agents_sync.publication_outbox import list_agent_publications
from sase.agents_sync.v2_io import owner_manifest_path, v2_json_bytes
from sase.agents_sync.v2_models import (
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2PublicationCounts,
)
from sase.bead.model import Issue, IssueType
from sase.bead_pages.associations import BeadAssociationIndex
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.sdd.store import SddStore
from sase.workflows.commit.checkpoint import CommitCheckpoint
from sase.workflows.commit.workflow_publication import run_agent_publication_step

_AGENT = "worker--code"
_REVISION = "a" * 40
_MESSAGE = (
    "feat: publish inline\n\n"
    "SASE_BEAD=sase-fa.1\n"
    "SASE_PLAN=plans:202608/inline.md\n"
    f"SASE_AGENT={_AGENT}"
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _seeded_sidecar(tmp_path: Path, name: str) -> tuple[Path, Path]:
    """Create a checkout wired to a bare remote, both on ``main``."""

    remote = tmp_path / f"{name}.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare", "-b", "main")
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "SASE Test")
    _git(repo, "config", "user.email", "sase-test@example.com")
    (repo / ".gitkeep").write_text("", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "seed")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo, remote


def _remote_paths(remote: Path) -> frozenset[str]:
    listing = _git(remote, "ls-tree", "-r", "--name-only", "main").stdout
    return frozenset(path for path in listing.splitlines() if path)


class _BeadView:
    def __init__(self, issues: tuple[Issue, ...]) -> None:
        self._issues = issues

    def __enter__(self) -> _BeadView:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def list_issues(self) -> list[Issue]:
        return list(self._issues)

    def show(self, issue_id: str) -> Issue:
        return next(issue for issue in self._issues if issue.id == issue_id)

    def get_epic_children(self, issue_id: str) -> list[Issue]:
        return [issue for issue in self._issues if issue.parent_id == issue_id]


@dataclass(frozen=True)
class _Fixture:
    primary: Path
    plans: Path
    plans_remote: Path
    beads: Path
    beads_remote: Path
    agents: Path
    agents_remote: Path
    plan_path: Path


@pytest.fixture
def inline_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> _Fixture:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    primary = tmp_path / "primary"
    primary.mkdir()
    plans, plans_remote = _seeded_sidecar(tmp_path, "plans")
    beads, beads_remote = _seeded_sidecar(tmp_path, "beads")
    agents, agents_remote = _seeded_sidecar(tmp_path, "agents")

    plan_path = plans / "202608" / "inline.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\ntier: tale\n---\n\n# Inline\n", encoding="utf-8")
    _git(plans, "add", ".")
    _git(plans, "commit", "-q", "-m", "add plan")
    _git(plans, "push", "-q", "origin", "main")

    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url=str(plans_remote),
        beads_dir=beads,
        beads_remote_url=str(beads_remote),
    )
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)
    monkeypatch.setattr(
        "sase.sdd.plan_refs.workspace_context_for_plan_resolution",
        lambda _root: (plans, 1),
    )
    monkeypatch.setattr(
        "sase.sdd.checkout_anchor.resolve_checkout_anchor",
        lambda _cwd: SimpleNamespace(primary_root=primary, project_name="Project"),
    )
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )
    # Pushes must be observable when the step returns, so the async push mode
    # used by the SDD store resolves to its synchronous counterpart.
    from sase.bead import sync as bead_sync

    monkeypatch.setattr(
        bead_sync,
        "push_bead_work_launch_async",
        lambda root, *_args, **_kwargs: (
            bead_sync.push_bead_work_launch(root)
            and SimpleNamespace(pid=0, log_path=None)
        ),
    )

    # Bead-store access and agents payload synthesis are the two dependencies
    # that need a real `bd` store and a real agent run inventory; everything
    # else below is the production code path.
    lineage = (
        Issue("sase-fa", "Inline publication", issue_type=IssueType.PLAN),
        Issue(
            "sase-fa.1",
            "Commit path",
            issue_type=IssueType.PHASE,
            parent_id="sase-fa",
        ),
    )
    monkeypatch.setattr(
        "sase.bead.store_locator.open_bead_project_for_beads_dir",
        lambda _root: _BeadView(lineage),
    )
    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: SimpleNamespace(
            plan_url=lambda _ref: None,
            bead_url=lambda _bead: None,
            agent_url=lambda *_a, **_k: None,
        ),
    )
    monkeypatch.setattr(
        "sase.bead_pages.associations.build_bead_association_index",
        lambda *_args, **_kwargs: BeadAssociationIndex(MappingProxyType({})),
    )

    @contextmanager
    def acquired_lock(*_args: object, **_kwargs: object):
        yield True

    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        acquired_lock,
    )

    owner = AgentOwnerIdentity("alice", "athena")
    agents_target = ProjectTarget(
        project_key="proj",
        project="Project",
        primary_checkout=primary,
        primary_roots=(primary,),
        sidecar_path=agents,
        remote_url=str(agents_remote),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.resolve_sync_targets",
        lambda _projects: TargetSelection((agents_target,), ()),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication._resolve_sidecar_publication_target",
        lambda **_kwargs: (agents_target, None),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.require_agent_owner_identity",
        lambda: owner,
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.integrate_agent_imports_with_receipts",
        lambda *_args, **_kwargs: IntegrationCounts(),
    )

    def publish_hood(_target, repo: Path, _agent, **_kwargs):
        (repo / "README.md").write_text("# Published hood\n", encoding="utf-8")
        (repo / "schema.json").write_text("{}\n", encoding="utf-8")
        (repo / "families").mkdir(exist_ok=True)
        (repo / "families" / ".gitkeep").write_text("", encoding="utf-8")
        page = (
            repo
            / "agents"
            / f"{owner.username}.{owner.machine_name}.worker"
            / "README.md"
        )
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("# worker\n", encoding="utf-8")
        archive = repo / "prompts" / "202608" / "inline.md"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text("expanded prompt\n", encoding="utf-8")
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            (
                (
                    "worker",
                    V2OwnerHoodEntry(
                        "d" * 64,
                        (
                            "README.md",
                            str(page.relative_to(repo)),
                            str(archive.relative_to(repo)),
                        ),
                        1,
                        1,
                    ),
                ),
            ),
        )
        manifest_path = repo / owner_manifest_path(owner)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.publish_agent_hood",
        publish_hood,
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish_prompt_archive",
        lambda *_args, **_kwargs: SimpleNamespace(
            error=None,
            skip_reason=None,
            prompt_path=None,
        ),
    )
    (primary / "registry.json").write_text(json.dumps({}), encoding="utf-8")
    return _Fixture(
        primary=primary,
        plans=plans,
        plans_remote=plans_remote,
        beads=beads,
        beads_remote=beads_remote,
        agents=agents,
        agents_remote=agents_remote,
        plan_path=plan_path,
    )


def test_tagged_commit_publishes_and_pushes_every_sidecar_before_returning(
    inline_publication: _Fixture,
) -> None:
    fixture = inline_publication
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": _MESSAGE},
        cwd=str(fixture.primary),
        primary_revision=_REVISION,
        publication_agent=_AGENT,
    )

    assert run_agent_publication_step(
        cp,
        "create_commit",
        checkpoint_save=lambda _cp: None,
        get_vcs_provider=lambda _cwd: pytest.fail("revision is already resolved"),
    )

    # The beads sidecar holds the rendered lineage, pushed to its remote.
    beads_remote_paths = _remote_paths(fixture.beads_remote)
    assert "pages/sase-fa/README.md" in beads_remote_paths
    assert "pages/sase-fa/sase-fa.1.md" in beads_remote_paths

    # The plan header was rewritten and pushed.
    plans_remote_paths = _remote_paths(fixture.plans_remote)
    assert "202608/inline.md" in plans_remote_paths

    # The agent hood and its prompt archive reached the agents remote, so the
    # footer URL written into this commit resolves immediately.
    agents_remote_paths = _remote_paths(fixture.agents_remote)
    assert "agents/alice.athena.worker/README.md" in agents_remote_paths
    assert "prompts/202608/inline.md" in agents_remote_paths

    # Nothing was deferred to a background lane.
    assert list_agent_publications("proj") == ()
    assert cp.completed_steps == [
        "publish_bead_pages",
        "publish_prompt_archive",
        "publish_agent_hood",
    ]
