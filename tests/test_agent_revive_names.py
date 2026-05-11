"""Tests that revive preserves agent names (Phase 4 behavior)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tests._agent_revive_helpers import FakeReviveApp, make_agent, patch_home


def test_revive_preserves_dismissal_prefixed_name(tmp_path: Path) -> None:
    """Reviving ``260428.foo`` does not rename it in memory."""
    app = FakeReviveApp()
    agent = make_agent(
        cl_name="feature_a",
        raw_suffix="20260428100000",
        agent_name="260428.foo",
    )
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    with (
        patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(agent)

    assert agent.agent_name == "260428.foo"


def test_revive_preserves_active_agent_waiting_for(tmp_path: Path) -> None:
    """Revive does not rewrite active wait references."""
    app = FakeReviveApp()
    revived = make_agent(
        cl_name="feature_a",
        raw_suffix="20260428100000",
        agent_name="260428.foo",
    )
    dependent = make_agent(
        cl_name="feature_b",
        raw_suffix="20260428110000",
        status="WAITING",
        waiting_for=["260428.foo"],
    )
    app._dismissed_agent_objects = [revived]
    app._dismissed_agents = {revived.identity}
    app._agents_with_children = [dependent]

    with (
        patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(revived)

    assert dependent.waiting_for == ["260428.foo"]


def test_revive_preserves_artifact_wait_for_on_disk(tmp_path: Path) -> None:
    """Revive leaves dependent ``agent_meta.json`` wait_for untouched."""
    artifact_dir = (
        tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / "20260428"
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"wait_for": ["260428.foo"]})
    )
    (artifact_dir / "raw_xprompt.md").write_text("%w:260428.foo run it")

    app = FakeReviveApp()
    revived = make_agent(
        cl_name="feature_a",
        raw_suffix="20260428100000",
        agent_name="260428.foo",
    )
    app._dismissed_agent_objects = [revived]
    app._dismissed_agents = {revived.identity}

    with (
        patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(revived)

    assert json.loads((artifact_dir / "agent_meta.json").read_text())["wait_for"] == [
        "260428.foo"
    ]
    assert (artifact_dir / "raw_xprompt.md").read_text() == "%w:260428.foo run it"


def test_revive_legacy_bundle_without_prefix_keeps_name(tmp_path: Path) -> None:
    """Pre-prefix bundles (no ``YYmmdd.``) revive under their current name."""
    app = FakeReviveApp()
    agent = make_agent(
        cl_name="feature_a",
        raw_suffix="20260428100000",
        agent_name="foo",
    )
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    with (
        patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(agent)

    assert agent.agent_name == "foo"
    # No fallback-name notification was emitted.
    assert not any(sev == "warning" for _, sev in app.notifications)


def test_revive_with_taken_name_keeps_stored_name(tmp_path: Path) -> None:
    """Revive does not rename when another live agent has the same name."""
    # Plant an active agent named "foo" so the revival sees the slot taken.
    active_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260501090000"
    )
    active_dir.mkdir(parents=True)
    (active_dir / "agent_meta.json").write_text(
        json.dumps({"name": "foo", "pid": 123456789})
    )
    (active_dir / "done.json").write_text(json.dumps({"outcome": "completed"}))

    app = FakeReviveApp()
    agent = make_agent(
        cl_name="feature_a",
        raw_suffix="20260428100000",
        agent_name="260428.foo",
    )
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    with (
        patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(agent)

    assert agent.agent_name == "260428.foo"
    assert not any(sev == "warning" for _, sev in app.notifications)


def test_revive_workflow_parent_preserves_children_prefix(tmp_path: Path) -> None:
    """A workflow parent + children keep their stored names together."""
    app = FakeReviveApp()
    parent = make_agent(
        cl_name="feature",
        raw_suffix="20260428100000",
        agent_name="260428.a",
    )
    child = make_agent(
        cl_name="child_step",
        raw_suffix="child_suffix_1",
        parent_workflow="wf",
        parent_timestamp="20260428100000",
        agent_name="260428.a.1",
    )
    app._dismissed_agent_objects = [parent, child]
    app._dismissed_agents = {parent.identity, child.identity}

    with (
        patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agent(parent)

    assert parent.agent_name == "260428.a"
    assert child.agent_name == "260428.a.1"


def test_batch_revive_preserves_names_for_all_agents(tmp_path: Path) -> None:
    """Batch revive does not rename any revival_group member."""
    app = FakeReviveApp()
    parent_one = make_agent(
        cl_name="f1",
        raw_suffix="20260428100000",
        agent_name="260428.foo",
    )
    parent_two = make_agent(
        cl_name="f2",
        raw_suffix="20260428110000",
        workflow="wf_two",
        agent_name="260428.bar",
    )
    app._dismissed_agent_objects = [parent_one, parent_two]
    app._dismissed_agents = {parent_one.identity, parent_two.identity}

    with (
        patch_home(tmp_path),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity"),
    ):
        app._do_revive_agents([parent_one, parent_two])

    assert parent_one.agent_name == "260428.foo"
    assert parent_two.agent_name == "260428.bar"
