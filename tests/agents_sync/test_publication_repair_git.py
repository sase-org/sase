from __future__ import annotations

from pathlib import Path

from sase.agents_sync.git import run_git
from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.publication_repair import _repair_project_hood_digests
from sase.agents_sync.publication_validation import load_validated_publication
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity

from tests.agents_sync.git_sync_fixtures import git, setup_repo, target


def _run(owner: AgentOwnerIdentity) -> InventoryRun:
    return InventoryRun(
        "run-01",
        "foo",
        f"{owner.username}.{owner.machine_name}.foo",
        "completed",
        "2026-07-23T12:00:00+00:00",
        "2026-07-23T12:01:00+00:00",
        None,
        (("model", "gpt"),),
        (),
        b"prompt for foo\n",
        b"chat for foo\n",
        None,
        None,
        (),
        "20260723120001",
    )


def test_repair_commits_and_pushes_a_resigned_snapshot(
    tmp_path: Path,
) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    owner = AgentOwnerIdentity("local", "athena")
    sync_target = target(tmp_path, remote, sidecar)

    publish_agent_hood(
        sync_target,
        sidecar,
        "foo",
        identity=AgentIdentitySnapshot(owner),
        inventory=ProjectHoodInventory(owner, "proj", (_run(owner),)),
    )
    git(sidecar, "add", "-A")
    git(sidecar, "commit", "-m", "seed a published hood")
    git(sidecar, "push", "origin", "HEAD")

    chat_path = sidecar / "agents" / "local.athena.foo" / "chat.md"
    chat_path.write_bytes(b"rewritten out of band\n")
    git(sidecar, "add", "-A")
    git(sidecar, "commit", "-m", "simulate an out-of-band sidecar rewrite")
    git(sidecar, "push", "origin", "HEAD")

    outcome = _repair_project_hood_digests(sync_target, owner, git_runner=run_git)

    assert outcome.error is None
    assert outcome.committed and outcome.pushed
    assert any("chat.md" in diagnostic for diagnostic in outcome.diagnostics)

    verify = tmp_path / "verify"
    git(tmp_path, "clone", str(remote), str(verify))
    assert (verify / "agents" / "local.athena.foo" / "chat.md").read_bytes() == (
        b"rewritten out of band\n"
    )
    load_validated_publication(verify)


def test_repair_is_a_noop_when_nothing_has_drifted(tmp_path: Path) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    owner = AgentOwnerIdentity("local", "athena")
    sync_target = target(tmp_path, remote, sidecar)

    publish_agent_hood(
        sync_target,
        sidecar,
        "foo",
        identity=AgentIdentitySnapshot(owner),
        inventory=ProjectHoodInventory(owner, "proj", (_run(owner),)),
    )
    git(sidecar, "add", "-A")
    git(sidecar, "commit", "-m", "seed a published hood")
    git(sidecar, "push", "origin", "HEAD")
    before_head = git(sidecar, "rev-parse", "HEAD").stdout.strip()

    outcome = _repair_project_hood_digests(sync_target, owner, git_runner=run_git)

    assert outcome.error is None
    assert not outcome.committed
    assert not outcome.pushed
    assert git(sidecar, "rev-parse", "HEAD").stdout.strip() == before_head
