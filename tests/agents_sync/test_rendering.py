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
    machine = payload["users/alice/machines/athena/README.md"].decode()
    hood = payload["users/alice/machines/athena/hoods/foo/README.md"].decode()

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
