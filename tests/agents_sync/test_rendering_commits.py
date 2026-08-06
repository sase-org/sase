"""Tests for commit tables on rendered agent and family pages."""

from __future__ import annotations

import os
import time

import pytest

from sase._git_remote import github_commit_url
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
