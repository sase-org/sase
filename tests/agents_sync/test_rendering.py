"""Tests for browsing-payload page structure: escaping, breadcrumbs, neighbors."""

from __future__ import annotations

import posixpath
import re

from sase.agents_sync.rendering import render_browsing_payload
from sase.agents_sync.rendering_markdown import relative_page_url
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
        "machine, hood, session, and agent pages.]"
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


def test_relative_page_url_normalized_paths_match_posixpath_without_abspath(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    sources = (
        "README.md",
        "a/README.md",
        "a/b/README.md",
        "users/alice/machines/athena/README.md",
    )
    targets = (
        "README.md",
        "index.md",
        "a/README.md",
        "a/b/page.md",
        "users/alice/README.md",
        "users/alice/machines/athena/hoods/foo/README.md",
    )
    expected = {
        (source, target): posixpath.relpath(target, posixpath.dirname(source))
        for source in sources
        for target in targets
    }

    def unexpected_abspath(_path: str) -> str:
        raise AssertionError("normalized repository paths must not call abspath")

    monkeypatch.setattr(posixpath, "abspath", unexpected_abspath)
    for (source, target), relative in expected.items():
        assert relative_page_url(source, target) == relative


def test_relative_page_url_normalized_edges_and_anchors() -> None:
    assert relative_page_url("README.md", "README.md") == "README.md"
    assert relative_page_url("a/README.md", "a/other.md") == "other.md"
    assert relative_page_url("a/README.md", "a") == "."
    assert relative_page_url("a/README.md", "b/page.md#heading here") == (
        "../b/page.md#heading%20here"
    )


def test_relative_page_url_falls_back_for_non_normalized_paths() -> None:
    for source, target in (
        ("a/../source.md", "b/target.md"),
        ("a//source.md", "./b/target.md"),
        ("/root/source.md", "/target.md"),
        ("a/source.md", "../target.md"),
    ):
        path, marker, anchor = target.partition("#")
        expected = posixpath.relpath(path, posixpath.dirname(source))
        if marker:
            expected += f"#{anchor}"
        assert relative_page_url(source, target).split("#", 1)[0] == expected


def test_agent_and_session_pages_render_relative_breadcrumbs() -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    session_run = V2RunRecord(
        "run-session",
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
    agent_session = V2ContainerRecord(
        "session",
        "alice.athena.foo.bar",
        ("run-session",),
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(session_run, solo_run),
        containers=(agent_session,),
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
    session_agent_page = payload["agents/alice.athena.foo.bar--code/README.md"].decode()
    solo_agent_page = payload["agents/alice.athena.foo.solo/README.md"].decode()
    session_page = payload["sessions/alice.athena.foo.bar.md"].decode()
    redirect = payload["families/alice.athena.foo.bar.md"].decode()
    assert "`sessions/alice.athena.foo.bar.md`" in redirect
    assert "../sessions/alice.athena.foo.bar.md" in redirect

    agent_ancestors = (
        "[Agent Hoods](../../README.md) / "
        "[alice](../../users/alice/README.md) / "
        "[athena](../../users/alice/machines/athena/README.md) / "
        "[foo](../../users/alice/machines/athena/hoods/foo/README.md)"
    )
    assert (
        agent_ancestors
        + " / [foo.bar](../../sessions/alice.athena.foo.bar.md) / foo.bar--code"
        in session_agent_page
    )
    assert agent_ancestors + " / foo.solo" in solo_agent_page
    assert "- Variables:" not in solo_agent_page
    assert "represented in its" not in session_agent_page
    assert (
        "[Agent Hoods](../README.md) / "
        "[alice](../users/alice/README.md) / "
        "[athena](../users/alice/machines/athena/README.md) / "
        "[foo](../users/alice/machines/athena/hoods/foo/README.md) / foo.bar"
        in session_page
    )


def test_agent_and_session_neighbor_links_resolve_inside_payload() -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    session_run = V2RunRecord(
        "run-session",
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
    agent_session = V2ContainerRecord(
        "session",
        "alice.athena.foo.bar",
        ("run-session",),
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(session_run, sibling_run),
        containers=(agent_session,),
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
    session_agent_path = "agents/alice.athena.foo.bar--code/README.md"
    session_path = "sessions/alice.athena.foo.bar.md"
    sibling_path = "agents/alice.athena.foo.sibling/README.md"

    session_agent_page = payload[session_agent_path].decode()
    session_page = payload[session_path].decode()
    sibling_page = payload[sibling_path].decode()
    assert "## Neighbors" in session_agent_page
    assert "## Neighbors" in session_page
    assert "[foo.sibling](../alice.athena.foo.sibling/README.md)" in session_agent_page
    assert "[foo.sibling](../agents/alice.athena.foo.sibling/README.md)" in session_page
    assert (
        "[foo.bar](../../sessions/alice.athena.foo.bar.md) (session · 1)"
        in sibling_page
    )

    for source_path in (session_agent_path, session_path, sibling_path):
        page = payload[source_path].decode()
        section = page.partition("## Neighbors")[2]
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", section):
            resolved = posixpath.normpath(
                posixpath.join(posixpath.dirname(source_path), target)
            )
            assert resolved in payload


def test_agent_and_session_pages_render_sorted_escaped_and_truncated_variables() -> (
    None
):
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
    agent_session = V2ContainerRecord(
        "session",
        "alice.athena.foo.bar",
        ("run-code", "run-plan"),
    )
    snapshot = V2HoodSnapshot(
        owner,
        project,
        "foo",
        "alice.athena.foo",
        runs=(code, plan),
        containers=(agent_session,),
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
    session_page = payload["sessions/alice.athena.foo.bar.md"].decode()

    assert "- Variables: [2](#variables)" in agent_page
    assert agent_page.index("| `a_long` |") < agent_page.index("| `z_notes` |")
    assert f"| `a_long` | {'x' * 199}… |" in agent_page
    assert r'| `z_notes` | "line \| one\\nline two" |' in agent_page
    assert (
        "Values are truncated for display; see [meta.json](meta.json) "
        "for the full values." in agent_page
    )
    assert "| code | `a_long` |" in session_page
    assert "| code | `z_notes` |" in session_page
    assert "| plan | `plan_file` | plans/foo.md |" in session_page
    assert (
        session_page.index("| code | `a_long` |")
        < session_page.index("| code | `z_notes` |")
        < session_page.index("| plan | `plan_file` |")
    )
