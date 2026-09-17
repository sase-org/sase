from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.v2_io import read_hood_snapshot
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.publication_fixtures import (
    _assert_summary_anchors_resolve,
    _identity,
    _inventory,
    _section_titles,
    _snapshot_path,
    _target,
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
    assert first.hoods_published == 1 and first.runs_published == 10
    assert second.hoods_unchanged == 1
    assert before == after
    assert {run.local_name for run in snapshot.runs} == {
        "foo",
        "foo.bar",
        "foo.bar.baz--code",
        "foo.bar.baz--plan",
        "foo.bar.baz.child",
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
    agent = (
        repo / "agents" / "alice.athena.foo.bar.baz--code" / "README.md"
    ).read_text()
    assert _section_titles(agent) == (
        "Summary",
        "Files",
        "Commits",
        "Variables",
        "Neighbors",
    )
    assert _section_titles(family) == (
        "Lineage",
        "Commits",
        "Variables",
        "Neighbors",
    )
    assert (
        family.index("## Lineage")
        < family.index("| Role | Agent | State |")
        < family.index("## Commits")
    )
    assert (
        "| [foo.bar.baz.child](../agents/alice.athena.foo.bar.baz.child/README.md) "
        "| descendant | completed |" in family
    )
    _assert_summary_anchors_resolve(agent)
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
        _assert_summary_anchors_resolve(rendered_text)
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


def test_targeted_publication_accepts_family_container_request(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()

    counts = publish_agent_hood(
        target,
        repo,
        "foo.rootless",
        identity=_identity(),
        inventory=_inventory(AgentOwnerIdentity("alice", "athena")),
    )

    snapshot = read_hood_snapshot(_snapshot_path(repo))
    assert counts.hoods_published == 1
    assert {"foo.rootless--left", "foo.rootless--right"} <= {
        run.local_name for run in snapshot.runs
    }
    assert (repo / "families" / "alice.athena.foo.rootless.md").is_file()
    assert (repo / "agents" / "alice.athena.foo.rootless--left" / "README.md").is_file()
    assert (
        repo / "agents" / "alice.athena.foo.rootless--right" / "README.md"
    ).is_file()


def test_family_lane_and_member_requests_publish_identical_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agent.names.get_reserved_family_names_for_display",
        lambda: frozenset({"foo.rootless"}),
    )
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))

    def _publish(committing_agent: str, name: str) -> dict[str, bytes]:
        root = tmp_path / name
        primary = root / "primary"
        primary.mkdir(parents=True)
        repo = root / "sidecar"
        repo.mkdir()
        target = ProjectTarget(
            "proj",
            "Project",
            primary,
            (primary.resolve(),),
            repo,
            "unused",
        )
        publish_agent_hood(
            target,
            repo,
            committing_agent,
            identity=_identity(),
            inventory=inventory,
        )
        return {
            path.relative_to(repo).as_posix(): path.read_bytes()
            for path in repo.rglob("*")
            if path.is_file()
        }

    assert _publish("foo.rootless--left", "member") == _publish("foo.rootless", "lane")


def test_registered_family_lane_without_runs_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agent.names.get_reserved_family_names_for_display",
        lambda: frozenset({"missing"}),
    )
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()

    with pytest.raises(
        AgentsSyncFormatError,
        match="hood 'missing' has no publishable runs",
    ):
        publish_agent_hood(
            target,
            repo,
            "missing",
            identity=_identity(),
            inventory=ProjectHoodInventory(
                AgentOwnerIdentity("alice", "athena"),
                "proj",
                (),
            ),
        )


def test_targeted_publication_rejects_request_for_empty_hood(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()

    with pytest.raises(AgentsSyncFormatError, match="hood 'missing'"):
        publish_agent_hood(
            target,
            repo,
            "missing",
            identity=_identity(),
            inventory=ProjectHoodInventory(
                AgentOwnerIdentity("alice", "athena"),
                "proj",
                (),
            ),
        )


def test_publication_links_commits_for_github_primary_remote(tmp_path: Path) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = replace(
        _inventory(AgentOwnerIdentity("alice", "athena")),
        primary_remote_url="git@github.com:acme/project.git",
        primary_repo_name="project",
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
    assert "| project | [`aaaaaaa`]" in page
