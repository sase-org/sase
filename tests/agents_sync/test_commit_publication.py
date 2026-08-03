from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import commit_publication
from sase.agents_sync.git import run_git
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.models import (
    IntegrationCounts,
    ProjectTarget,
    TargetSelection,
)
from sase.agents_sync.publication_outbox import list_agent_publications
from sase.agents_sync.v2_io import (
    owner_manifest_path,
    v2_json_bytes,
)
from sase.agents_sync.v2_models import (
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2PublicationCounts,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.commit_publication_fixtures import (
    git,
    publish_committed_agent_hood,
    setup_target,
)


def test_push_failure_is_queued_and_next_commit_drains_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, remote = setup_target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.require_agent_owner_identity",
        lambda: owner,
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.integrate_agent_imports_with_receipts",
        lambda *_args, **_kwargs: IntegrationCounts(),
    )

    def publish(_target, repo, _agent, **_kwargs):
        (repo / "README.md").write_text("# Published hood\n")
        (repo / "schema.json").write_text("{}\n")
        (repo / "families").mkdir(exist_ok=True)
        (repo / "families" / ".gitkeep").write_text("")
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            (
                (
                    "foo",
                    V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1),
                ),
            ),
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.publish_agent_hood",
        publish,
    )

    def rejecting_runner(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        if args == ["push"]:
            return subprocess.CompletedProcess(args, 1, "", "permission denied")
        return run_git(cwd, args, network=network, op=op)

    first = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=rejecting_runner,
    )

    assert first.queued and first.error
    queued = list_agent_publications("proj")
    assert len(queued) == 1
    assert queued[0].hood_digest == "d" * 64
    assert queued[0].attempts == 1

    second = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )

    assert second.published and not second.error
    assert list_agent_publications("proj") == ()
    verify = tmp_path / "verify"
    git(tmp_path, "clone", str(remote), str(verify))
    assert (verify / "README.md").read_text() == "# Published hood\n"


@pytest.mark.parametrize(
    ("committing_agent", "lane"),
    [
        ("foo--code", "foo"),
        ("foo.bar--plan", "foo.bar"),
        ("foo.solo", "foo.solo"),
    ],
)
def test_publication_request_records_the_committing_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    committing_agent: str,
    lane: str,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = setup_target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    monkeypatch.setattr(
        commit_publication,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        commit_publication,
        "require_agent_owner_identity",
        lambda: owner,
    )
    monkeypatch.setattr(
        commit_publication,
        "integrate_agent_imports_with_receipts",
        lambda *_args, **_kwargs: IntegrationCounts(),
    )
    monkeypatch.setattr(
        commit_publication,
        "build_project_hood_inventory",
        lambda *_args, **_kwargs: ProjectHoodInventory(owner, "proj", ()),
    )
    published_agents: list[str] = []

    def publish(
        _target: ProjectTarget,
        _repo: Path,
        agent: str,
        **_kwargs: object,
    ) -> V2PublicationCounts:
        published_agents.append(agent)
        raise RuntimeError("stop before pushing")

    monkeypatch.setattr(commit_publication, "publish_agent_hood", publish)

    publish_committed_agent_hood(
        committing_agent,
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )

    [pending] = list_agent_publications("proj")
    assert pending.local_agent == lane
    assert pending.global_agent == f"alice.athena.{lane}"
    assert pending.local_hood == "foo"
    assert published_agents == [lane]
