from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.agents_sync.inventory import (
    InventoryRun,
    ProjectHoodInventory,
    _InventoryRelationship,
)
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.agents_sync.publication import publish_agent_hood, reconcile_agent_hoods
from sase.agents_sync.v2_io import read_hood_snapshot
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity


def _target(tmp_path: Path) -> ProjectTarget:
    primary = tmp_path / "primary"
    primary.mkdir()
    return ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        tmp_path / "sidecar",
        "unused",
    )


def _run(
    name: str,
    suffix: str,
    *,
    state: str = "completed",
    commit: bool = False,
    family: str | None = None,
    chat: bytes | None = b"chat\n",
    relationships: tuple[_InventoryRelationship, ...] = (),
) -> InventoryRun:
    owner = AgentOwnerIdentity("alice", "athena")
    metadata = (("model", "gpt"),)
    if family is not None:
        metadata += (("agent_family", family),)
    commits = (CommitRecord("a" * 39 + suffix[-1], name, 1),) if commit else ()
    finished_at = (
        None if state in {"active", "waiting"} else "2026-07-23T12:01:00+00:00"
    )
    return InventoryRun(
        f"run-{suffix}",
        name,
        f"{owner.username}.{owner.machine_name}.{name}",
        state,
        "2026-07-23T12:00:00+00:00",
        finished_at,
        finished_at if state == "dismissed" else None,
        tuple(sorted(metadata)),
        commits,
        f"prompt for {name}\n".encode(),
        chat,
        family,
        None,
        relationships,
        f"20260723120{suffix[-2:]}",
    )


def _inventory(owner: AgentOwnerIdentity) -> ProjectHoodInventory:
    runs = (
        _run("foo", "01"),
        _run("foo.bar", "02"),
        _run(
            "foo.bar.baz--code",
            "03",
            state="active",
            commit=True,
            family="foo.bar.baz",
            chat=None,
            relationships=(_InventoryRelationship("parent", "foo.bar", "name"),),
        ),
        _run(
            "foo.bar.baz--plan",
            "04",
            family="foo.bar.baz",
            relationships=(_InventoryRelationship("parent", "foo.bar", "name"),),
        ),
        _run("foo.boom", "05", state="waiting"),
        _run("foo.bar.kazam", "06", state="failed"),
        _run("foo.rootless--left", "07", family="foo.rootless"),
        _run("foo.rootless--right", "08", family="foo.rootless"),
        _run("foo.archive", "11", state="dismissed"),
        _run("zap.solo", "09"),
        _run("work.committer", "10", commit=True),
    )
    return ProjectHoodInventory(owner, "proj", runs)


def _identity() -> AgentIdentitySnapshot:
    return AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"))


def _snapshot_path(root: Path) -> Path:
    return (
        root
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "foo"
        / "snapshot.json"
    )


def test_targeted_publication_captures_complete_hood_and_is_byte_stable(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))

    first = publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    before = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file()
    }
    second = publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    after = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file()
    }

    snapshot = read_hood_snapshot(_snapshot_path(repo))
    assert first.hoods_published == 1 and first.runs_published == 9
    assert second.hoods_unchanged == 1
    assert before == after
    assert {run.local_name for run in snapshot.runs} == {
        "foo",
        "foo.bar",
        "foo.bar.baz--code",
        "foo.bar.baz--plan",
        "foo.boom",
        "foo.bar.kazam",
        "foo.rootless--left",
        "foo.rootless--right",
        "foo.archive",
    }
    assert "alice.athena.foo.bar" in snapshot.structural_ancestors
    assert "alice.athena.foo.bar.baz" in snapshot.structural_ancestors
    assert (repo / "families" / "alice.athena.foo.bar.baz.md").is_file()
    family = (repo / "families" / "alice.athena.foo.bar.baz.md").read_text()
    assert '<a id="member-code"></a>' in family
    assert "```mermaid" in family
    assert not (repo / "agents" / "alice.athena.foo.bar.baz--code" / "chat.md").exists()

    golden_root = Path(__file__).with_name("goldens")
    rendered = {
        "solo.md": repo / "agents" / "alice.athena.foo" / "README.md",
        "rootless-family.md": repo / "families" / "alice.athena.foo.rootless.md",
        "deep-family.md": repo / "families" / "alice.athena.foo.bar.baz.md",
        "active-no-chat.md": (
            repo / "agents" / "alice.athena.foo.bar.baz--code" / "README.md"
        ),
        "mixed-state-hood.md": (
            repo
            / "users"
            / "alice"
            / "machines"
            / "athena"
            / "hoods"
            / "foo"
            / "README.md"
        ),
    }
    updated_goldens: list[str] = []
    update_goldens = request.config.getoption("--sase-update-agents-goldens")
    for golden_name, rendered_path in rendered.items():
        rendered_text = rendered_path.read_text()
        golden_path = golden_root / golden_name
        if update_goldens and rendered_text != golden_path.read_text():
            # Refresh with --sase-update-agents-goldens, then rerun without it.
            golden_path.write_text(rendered_text)
            updated_goldens.append(golden_name)
            continue
        assert rendered_text == golden_path.read_text()
    if updated_goldens:
        pytest.fail(
            "Updated agents-sync goldens; rerun without the refresh flag: "
            + ", ".join(updated_goldens)
        )


def test_refresh_adds_optional_chat_and_preserves_temporarily_absent_run(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    refreshed_runs = tuple(
        (
            replace(
                run,
                chat_bytes=b"late chat\n",
                state="completed",
                finished_at="2026-07-23T12:02:00+00:00",
            )
            if run.local_name == "foo.bar.baz--code"
            else run
        )
        for run in inventory.runs
        if run.local_name != "foo.boom"
    )
    refreshed = ProjectHoodInventory(inventory.owner, "proj", refreshed_runs)

    counts = publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=refreshed,
    )

    snapshot = read_hood_snapshot(_snapshot_path(repo))
    assert counts.hoods_refreshed == 1
    assert "foo.boom" in {run.local_name for run in snapshot.runs}
    assert (
        repo / "agents" / "alice.athena.foo.bar.baz--code" / "chat.md"
    ).read_bytes() == b"late chat\n"


def test_full_reconciliation_discovers_only_commit_eligible_hoods(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()

    counts = reconcile_agent_hoods(
        target,
        repo,
        identity=_identity(),
        inventory=_inventory(AgentOwnerIdentity("alice", "athena")),
    )

    machine = repo / "users" / "alice" / "machines" / "athena"
    assert counts.hoods_published == 2
    assert (machine / "hoods" / "foo" / "snapshot.json").is_file()
    assert (machine / "hoods" / "work" / "snapshot.json").is_file()
    assert not (machine / "hoods" / "zap").exists()


def test_publication_links_commits_for_github_primary_remote(tmp_path: Path) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = replace(
        _inventory(AgentOwnerIdentity("alice", "athena")),
        primary_remote_url="git@github.com:acme/project.git",
    )

    publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )

    page = (
        repo / "agents" / "alice.athena.foo.bar.baz--code" / "README.md"
    ).read_text()
    assert (
        "[`aaaaaaa`](https://github.com/acme/project/commit/" + "a" * 39 + "3)" in page
    )


def test_two_owner_manifests_coexist_and_indexes_converge(tmp_path: Path) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    alice = _inventory(AgentOwnerIdentity("alice", "athena"))
    reconcile_agent_hoods(
        target,
        repo,
        identity=_identity(),
        inventory=alice,
    )
    bob_owner = AgentOwnerIdentity("bob", "zeus")
    bob_run = InventoryRun(
        "run-bob",
        "other",
        "bob.zeus.other",
        "completed",
        None,
        None,
        None,
        (),
        (CommitRecord("b" * 40, "other", 2),),
        b"other\n",
        b"chat\n",
        None,
        None,
        (),
        "20260723130000",
    )
    reconcile_agent_hoods(
        target,
        repo,
        identity=AgentIdentitySnapshot(bob_owner),
        inventory=ProjectHoodInventory(bob_owner, "proj", (bob_run,)),
    )

    assert (
        repo / "users" / "alice" / "machines" / "athena" / "manifest.json"
    ).is_file()
    assert (repo / "users" / "bob" / "machines" / "zeus" / "manifest.json").is_file()
    root = (repo / "README.md").read_text(encoding="utf-8")
    assert "alice" in root and "bob" in root
