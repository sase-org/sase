"""Tests for bead and epic links on rendered agent and family pages."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync.bead_links import BeadPageLink
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
