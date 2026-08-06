"""Tests for browsing-payload page structure: escaping, breadcrumbs, neighbors."""

from __future__ import annotations

import posixpath
import re

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
