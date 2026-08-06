from __future__ import annotations

import os
from pathlib import Path
import posixpath
import re
import time

import pytest

from sase._git_remote import github_commit_url
from sase.agents_sync.bead_links import BeadPageLink
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.rendering import render_browsing_payload
from sase.agents_sync.v2_models import (
    V2ContainerRecord,
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2RunRecord,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity


def test_renderer_escapes_markdown_tables_and_contains_no_volatile_text() -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project | <unsafe>")
    run = V2RunRecord(
        "run-1",
        "foo",
        "alice.athena.foo",
        "active",
        metadata=(("model", "gpt|<preview>"),),
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        ("alice.athena.foo",),
        (run,),
    )
    manifest = V2OwnerManifest(
        owner,
        project,
        (("foo", V2OwnerHoodEntry("a" * 64, (), 1, 0)),),
    )

    payload = render_browsing_payload(
        (manifest,),
        {("alice", "athena", "foo"): snapshot},
    )
    root = payload["README.md"].decode()
    user = payload["users/alice/README.md"].decode()
    machine = payload["users/alice/machines/athena/README.md"].decode()
    hood = payload["users/alice/machines/athena/hoods/foo/README.md"].decode()

    image_markdown = (
        "![Project-scoped agent hoods pass through explicit privacy consent "
        "into an owner-sharded agents sidecar, where deterministic sync "
        "publishes prompts, chats, commits, states, and browsable owner, "
        "machine, hood, family, and agent pages.]"
        "(assets/agents-directory-map.png)"
    )
    assert image_markdown in root
    assert "agents-directory-map.png" not in user
    assert "agents-directory-map.png" not in machine
    assert "agents-directory-map.png" not in hood
    assert "Project \\| \\<unsafe\\>" in machine
    assert "gpt\\|\\<preview\\>" in hood
    assert "generated at" not in "\n".join(
        value.decode().lower() for value in payload.values()
    )


def test_agent_and_family_pages_render_relative_breadcrumbs() -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    family_run = V2RunRecord(
        "run-family",
        "foo.bar--code",
        "alice.athena.foo.bar--code",
        "active",
    )
    solo_run = V2RunRecord(
        "run-solo",
        "foo.solo",
        "alice.athena.foo.solo",
        "completed",
    )
    family = V2ContainerRecord(
        "family",
        "alice.athena.foo.bar",
        ("run-family",),
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(family_run, solo_run),
        containers=(family,),
    )
    manifest = V2OwnerManifest(
        owner,
        project,
        (("foo", V2OwnerHoodEntry("a" * 64, (), 2, 1)),),
    )

    payload = render_browsing_payload(
        (manifest,),
        {("alice", "athena", "foo"): snapshot},
    )
    family_agent_page = payload["agents/alice.athena.foo.bar--code/README.md"].decode()
    solo_agent_page = payload["agents/alice.athena.foo.solo/README.md"].decode()
    family_page = payload["families/alice.athena.foo.bar.md"].decode()

    agent_ancestors = (
        "[Agent Hoods](../../README.md) / "
        "[alice](../../users/alice/README.md) / "
        "[athena](../../users/alice/machines/athena/README.md) / "
        "[foo](../../users/alice/machines/athena/hoods/foo/README.md)"
    )
    assert (
        agent_ancestors
        + " / [foo.bar](../../families/alice.athena.foo.bar.md) / foo.bar--code"
        in family_agent_page
    )
    assert agent_ancestors + " / foo.solo" in solo_agent_page
    assert "- Variables:" not in solo_agent_page
    assert "represented in its family lineage" not in family_agent_page
    assert (
        "[Agent Hoods](../README.md) / "
        "[alice](../users/alice/README.md) / "
        "[athena](../users/alice/machines/athena/README.md) / "
        "[foo](../users/alice/machines/athena/hoods/foo/README.md) / foo.bar"
        in family_page
    )


def test_commit_tables_link_escape_and_format_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not hasattr(time, "tzset"):
        pytest.skip("platform does not support changing the process timezone")
    original_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        owner = AgentOwnerIdentity("alice", "athena")
        project = V2ProjectIdentity("proj", "Project")
        sha = "a" * 40
        run = V2RunRecord(
            "run-family",
            "foo.bar--code",
            "alice.athena.foo.bar--code",
            "completed",
            commits=(CommitRecord(sha, "unsafe | `tick` <tag>", 1),),
        )
        family = V2ContainerRecord(
            "family",
            "alice.athena.foo.bar",
            ("run-family",),
        )
        snapshot = V2HoodSnapshot(
            owner,
            project,
            "foo",
            "alice.athena.foo",
            runs=(run,),
            containers=(family,),
        )
        manifest = V2OwnerManifest(
            owner,
            project,
            (("foo", V2OwnerHoodEntry("a" * 64, (), 1, 1)),),
        )
        commit_url = github_commit_url(
            "git@github.com:acme/project.git",
            provider="github",
            sha=sha,
        )
        assert commit_url is not None
        commit_url_base = commit_url.removesuffix(f"/{sha}")

        payload = render_browsing_payload(
            (manifest,),
            {("alice", "athena", "foo"): snapshot},
            commit_url_base=commit_url_base,
            commit_repo_name="project",
        )
        agent_page = payload["agents/alice.athena.foo.bar--code/README.md"].decode()
        family_page = payload["families/alice.athena.foo.bar.md"].decode()

        expected_commit = (
            "[`aaaaaaa`](https://github.com/acme/project/commit/" + sha + ")"
        )
        assert "- Commits: [1](#commits)" in agent_page
        assert "| Repo | Commit | Subject | Committed |" in agent_page
        assert "| project | " + expected_commit in agent_page
        assert expected_commit in agent_page
        assert "unsafe \\| \\`tick\\` \\<tag\\>" in agent_page
        assert "1969-12-31 19:00:01 EST" in agent_page
        assert "| Role | Repo | Commit | Subject | Committed |" in family_page
        assert "| code | project | " + expected_commit in family_page
        assert (
            "[1](../agents/alice.athena.foo.bar--code/README.md#commits)" in family_page
        )
    finally:
        if original_tz is None:
            monkeypatch.delenv("TZ")
        else:
            monkeypatch.setenv("TZ", original_tz)
        time.tzset()


def test_family_page_unions_lane_commits_with_member_attribution_winning() -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    member_commit = CommitRecord("a" * 40, "member subject", 2)
    lane_commit = CommitRecord("b" * 40, "lane subject", 1)
    run = V2RunRecord(
        "run-family",
        "foo.bar--code",
        "alice.athena.foo.bar--code",
        "completed",
        commits=(member_commit,),
    )
    family = V2ContainerRecord(
        "family",
        "alice.athena.foo.bar",
        ("run-family",),
        (
            lane_commit,
            CommitRecord(member_commit.sha, "lane duplicate", 3),
        ),
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(run,),
        containers=(family,),
    )
    manifest = V2OwnerManifest(
        owner,
        project,
        (("foo", V2OwnerHoodEntry("a" * 64, (), 1, 1)),),
    )

    family_page = render_browsing_payload(
        (manifest,),
        {("alice", "athena", "foo"): snapshot},
        commit_repo_name="project",
    )["families/alice.athena.foo.bar.md"].decode()

    assert "| — | project | `bbbbbbb` | lane subject |" in family_page
    assert "| code | project | `aaaaaaa` | member subject |" in family_page
    assert "lane duplicate" not in family_page
    assert family_page.count("`aaaaaaa`") == 1
    assert family_page.index("lane subject") < family_page.index("member subject")


@pytest.mark.parametrize(
    ("remote_url", "provider"),
    (
        ("ssh://git@example.invalid/x/y.git", None),
        ("ssh://git@example.invalid/x/y.git", "gitlab"),
    ),
)
def test_unrecognized_remote_keeps_commits_unlinked(
    remote_url: str,
    provider: str | None,
) -> None:
    sha = "b" * 40
    assert github_commit_url(remote_url, provider=provider, sha=sha) is None

    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    run = V2RunRecord(
        "run-1",
        "foo",
        "alice.athena.foo",
        "completed",
        commits=(CommitRecord(sha, "subject", 1),),
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(run,),
    )
    manifest = V2OwnerManifest(
        owner,
        project,
        (("foo", V2OwnerHoodEntry("a" * 64, (), 1, 0)),),
    )

    page = render_browsing_payload(
        (manifest,),
        {("alice", "athena", "foo"): snapshot},
        commit_url_base=None,
        commit_repo_name=None,
    )["agents/alice.athena.foo/README.md"].decode()

    assert "| Repo | Commit | Subject | Committed |" in page
    assert "| — | `bbbbbbb` | subject | 1969-12-31 19:00:01 EST |" in page
    assert "https://" not in page


def test_commit_rendering_is_bounded_and_validates_link_shas() -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    commits = tuple(
        CommitRecord(f"{index:040x}", f"subject {index}", index) for index in range(51)
    )
    run = V2RunRecord(
        "run-1",
        "foo",
        "alice.athena.foo",
        "completed",
        commits=commits,
    )
    family = V2ContainerRecord(
        "family",
        "alice.athena.foo",
        ("run-1",),
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(run,),
        containers=(family,),
    )
    manifest = V2OwnerManifest(
        owner,
        project,
        (("foo", V2OwnerHoodEntry("a" * 64, (), 1, 0)),),
    )

    page = render_browsing_payload(
        (manifest,),
        {("alice", "athena", "foo"): snapshot},
        commit_url_base=None,
        commit_repo_name="project",
    )["agents/alice.athena.foo/README.md"].decode()

    assert "… and 1 more commits" in page
    assert "subject 49" in page
    assert "subject 50" not in page
    family_page = render_browsing_payload(
        (manifest,),
        {("alice", "athena", "foo"): snapshot},
        commit_url_base=None,
        commit_repo_name="project",
    )["families/alice.athena.foo.md"].decode()
    assert "… and 1 more commits" in family_page
    assert (
        github_commit_url(
            "git@github.com:acme/project.git",
            provider=None,
            sha="ABCDEF0",
        )
        is None
    )
    assert (
        github_commit_url(
            "git@example.corp:acme/project.git",
            provider="github",
            sha="abcdef0",
        )
        == "https://example.corp/acme/project/commit/abcdef0"
    )


def test_agent_and_family_neighbor_links_resolve_inside_payload() -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    family_run = V2RunRecord(
        "run-family",
        "foo.bar--code",
        "alice.athena.foo.bar--code",
        "completed",
    )
    sibling_run = V2RunRecord(
        "run-sibling",
        "foo.sibling",
        "alice.athena.foo.sibling",
        "failed",
    )
    family = V2ContainerRecord(
        "family",
        "alice.athena.foo.bar",
        ("run-family",),
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(family_run, sibling_run),
        containers=(family,),
    )
    manifest = V2OwnerManifest(
        owner,
        project,
        (("foo", V2OwnerHoodEntry("a" * 64, (), 2, 1)),),
    )

    payload = render_browsing_payload(
        (manifest,),
        {("alice", "athena", "foo"): snapshot},
    )
    family_agent_path = "agents/alice.athena.foo.bar--code/README.md"
    family_path = "families/alice.athena.foo.bar.md"
    sibling_path = "agents/alice.athena.foo.sibling/README.md"

    family_agent_page = payload[family_agent_path].decode()
    family_page = payload[family_path].decode()
    sibling_page = payload[sibling_path].decode()
    assert "## Neighbors" in family_agent_page
    assert "## Neighbors" in family_page
    assert "[foo.sibling](../alice.athena.foo.sibling/README.md)" in family_agent_page
    assert "[foo.sibling](../agents/alice.athena.foo.sibling/README.md)" in family_page
    assert (
        "[foo.bar](../../families/alice.athena.foo.bar.md) (family · 1)" in sibling_page
    )

    for source_path in (family_agent_path, family_path, sibling_path):
        page = payload[source_path].decode()
        section = page.partition("## Neighbors")[2]
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", section):
            resolved = posixpath.normpath(
                posixpath.join(posixpath.dirname(source_path), target)
            )
            assert resolved in payload


def test_agent_and_family_pages_render_sorted_escaped_and_truncated_variables() -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    code = V2RunRecord(
        "run-code",
        "foo.bar--code",
        "alice.athena.foo.bar--code",
        "completed",
        metadata=(
            (
                "output_variables",
                {
                    "z_notes": "line | one\nline two",
                    "a_long": "x" * 201,
                },
            ),
        ),
    )
    plan = V2RunRecord(
        "run-plan",
        "foo.bar--plan",
        "alice.athena.foo.bar--plan",
        "completed",
        metadata=(("output_variables", {"plan_file": "plans/foo.md"}),),
    )
    family = V2ContainerRecord(
        "family",
        "alice.athena.foo.bar",
        ("run-code", "run-plan"),
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(code, plan),
        containers=(family,),
    )
    manifest = V2OwnerManifest(
        owner,
        project,
        (("foo", V2OwnerHoodEntry("a" * 64, (), 2, 1)),),
    )

    payload = render_browsing_payload(
        (manifest,),
        {("alice", "athena", "foo"): snapshot},
    )
    agent_page = payload["agents/alice.athena.foo.bar--code/README.md"].decode()
    family_page = payload["families/alice.athena.foo.bar.md"].decode()

    assert "- Variables: [2](#variables)" in agent_page
    assert agent_page.index("| `a_long` |") < agent_page.index("| `z_notes` |")
    assert f"| `a_long` | {'x' * 199}… |" in agent_page
    assert r'| `z_notes` | "line \| one\\nline two" |' in agent_page
    assert (
        "Values are truncated for display; see [meta.json](meta.json) "
        "for the full values." in agent_page
    )
    assert "| code | `a_long` |" in family_page
    assert "| code | `z_notes` |" in family_page
    assert "| plan | `plan_file` | plans/foo.md |" in family_page
    assert (
        family_page.index("| code | `a_long` |")
        < family_page.index("| code | `z_notes` |")
        < family_page.index("| plan | `plan_file` |")
    )


def test_agent_page_renders_bead_then_epic_bullets_above_model() -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    run = V2RunRecord(
        "run-1",
        "sase-ar.6--code",
        "alice.athena.sase-ar.6--code",
        "completed",
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(run,),
    )
    manifest = V2OwnerManifest(
        owner,
        project,
        (("foo", V2OwnerHoodEntry("a" * 64, (), 1, 0)),),
    )
    bead_links = {
        run.global_name: BeadPageLink(
            "sase-ar.6",
            "https://example/beads/sase-ar.6",
            "sase-ar",
            "https://example/beads/sase-ar",
        )
    }

    page = render_browsing_payload(
        (manifest,),
        {("alice", "athena", "foo"): snapshot},
        bead_links=bead_links,
    )["agents/alice.athena.sase-ar.6--code/README.md"].decode()

    summary = page.split("## Summary\n\n", 1)[1]
    bead_index = summary.index("- Bead: [sase-ar.6](https://example/beads/sase-ar.6)")
    epic_index = summary.index("- Epic: [sase-ar](https://example/beads/sase-ar)")
    model_index = summary.index("- Model:")
    assert bead_index < epic_index < model_index


def test_agent_page_unlinked_bead_renders_plain_escaped_text() -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    run = V2RunRecord(
        "run-1",
        "foo",
        "alice.athena.foo",
        "completed",
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(run,),
    )
    manifest = V2OwnerManifest(
        owner,
        project,
        (("foo", V2OwnerHoodEntry("a" * 64, (), 1, 0)),),
    )
    bead_links = {run.global_name: BeadPageLink("sase-ar.6")}

    page = render_browsing_payload(
        (manifest,),
        {("alice", "athena", "foo"): snapshot},
        bead_links=bead_links,
    )["agents/alice.athena.foo/README.md"].decode()

    assert "- Bead: sase-ar.6" in page
    assert "[sase-ar.6]" not in page


def test_run_absent_from_bead_links_mapping_renders_unchanged() -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    run = V2RunRecord(
        "run-1",
        "foo",
        "alice.athena.foo",
        "completed",
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(run,),
    )
    manifest = V2OwnerManifest(
        owner,
        project,
        (("foo", V2OwnerHoodEntry("a" * 64, (), 1, 0)),),
    )
    snapshots = {("alice", "athena", "foo"): snapshot}

    without_bead_links = render_browsing_payload((manifest,), snapshots)
    with_empty_bead_links = render_browsing_payload(
        (manifest,), snapshots, bead_links={}
    )
    with_unrelated_bead_links = render_browsing_payload(
        (manifest,),
        snapshots,
        bead_links={"someone.else.other": BeadPageLink("sase-zz.1")},
    )

    assert without_bead_links == with_empty_bead_links == with_unrelated_bead_links


def test_family_page_header_renders_single_distinct_bead() -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    left = V2RunRecord(
        "run-left", "foo.bar--left", "alice.athena.foo.bar--left", "completed"
    )
    right = V2RunRecord(
        "run-right", "foo.bar--right", "alice.athena.foo.bar--right", "completed"
    )
    family = V2ContainerRecord(
        "family",
        "alice.athena.foo.bar",
        ("run-left", "run-right"),
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(left, right),
        containers=(family,),
    )
    manifest = V2OwnerManifest(
        owner,
        project,
        (("foo", V2OwnerHoodEntry("a" * 64, (), 2, 1)),),
    )
    bead_links = {
        left.global_name: BeadPageLink("sase-ar.6", "https://example/beads/sase-ar.6"),
        right.global_name: BeadPageLink("sase-ar.6", "https://example/beads/sase-ar.6"),
    }

    family_page = render_browsing_payload(
        (manifest,),
        {("alice", "athena", "foo"): snapshot},
        bead_links=bead_links,
    )["families/alice.athena.foo.bar.md"].decode()

    assert "Bead: [sase-ar.6](https://example/beads/sase-ar.6)" in family_page
    assert "Beads:" not in family_page


def test_family_page_header_caps_distinct_beads_and_reports_remainder() -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    letters = "abcdef"
    members = tuple(
        V2RunRecord(
            f"run-{letter}",
            f"foo.bar--{letter}",
            f"alice.athena.foo.bar--{letter}",
            "completed",
        )
        for letter in letters
    )
    family = V2ContainerRecord(
        "family",
        "alice.athena.foo.bar",
        tuple(run.source_run_id for run in members),
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=members,
        containers=(family,),
    )
    manifest = V2OwnerManifest(
        owner,
        project,
        (("foo", V2OwnerHoodEntry("a" * 64, (), len(members), 1)),),
    )
    bead_links = {
        run.global_name: BeadPageLink(f"sase-{letter}")
        for run, letter in zip(members, letters, strict=True)
    }

    family_page = render_browsing_payload(
        (manifest,),
        {("alice", "athena", "foo"): snapshot},
        bead_links=bead_links,
    )["families/alice.athena.foo.bar.md"].decode()

    assert "Beads: sase-a, sase-b, sase-c, sase-d, sase-e, … +1 more" in family_page
    assert "sase-f" not in family_page


def test_bead_linked_agent_page_golden(request: pytest.FixtureRequest) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    run = V2RunRecord(
        "run-1",
        "sase-ar.6",
        "alice.athena.sase-ar.6",
        "completed",
        started_at="2026-07-29T15:00:38+00:00",
        finished_at="2026-07-29T15:31:02+00:00",
        metadata=(("model", "opus"), ("llm_provider", "claude")),
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(run,),
    )
    manifest = V2OwnerManifest(
        owner,
        project,
        (("foo", V2OwnerHoodEntry("a" * 64, (), 1, 0)),),
    )
    bead_links = {
        run.global_name: BeadPageLink(
            "sase-ar.6",
            "https://github.com/sase-org/sase--beads/blob/main/pages/sase-ar/sase-ar.6.md",
            "sase-ar",
            "https://github.com/sase-org/sase--beads/blob/main/pages/sase-ar/README.md",
        )
    }

    page = render_browsing_payload(
        (manifest,),
        {("alice", "athena", "foo"): snapshot},
        bead_links=bead_links,
    )["agents/alice.athena.sase-ar.6/README.md"].decode()

    golden_path = Path(__file__).with_name("goldens") / "bead-linked-agent.md"
    if request.config.getoption("--sase-update-agents-goldens"):
        if page != golden_path.read_text():
            golden_path.write_text(page)
            pytest.fail(
                "Updated agents-sync golden; rerun without the refresh flag: "
                "bead-linked-agent.md"
            )
    assert page == golden_path.read_text()
