"""Startup contract tests for the agent-artifact performance epic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._loading_helpers import load_agents_from_disk
from sase.ace.tui.actions.agents._revive import AgentRevivalMixin
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.agent_artifact_startup_fixtures import (
    build_workflow_collision_archive,
    make_agent,
)


class FakeReviveApp(AgentRevivalMixin):
    """Minimal host for revive grouping contract tests."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self.notifications: list[str] = []
        self.restored: list[tuple[tuple[AgentType, str, str | None], str | None]] = []
        self.load_count = 0

    def notify(self, message: str, *, severity: str = "information") -> None:
        del severity
        self.notifications.append(message)

    def _load_agents(self) -> None:
        self.load_count += 1

    def _refresh_agents_display(self, *, list_changed: bool) -> None:
        del list_changed

    def _restore_agent_artifacts(
        self,
        agent: Agent,
        *,
        parent_artifacts_dir: str | None = None,
    ) -> None:
        self.restored.append((agent.identity, parent_artifacts_dir))


def test_load_agents_from_disk_hides_dismissed_identity_without_hiding_running_alias() -> (
    None
):
    """The compact dismissed index hides completed rows but not live aliases."""

    dismissed_done = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature",
        raw_suffix="20250101120000",
        status="DONE",
        workflow="wf",
    )
    running_alias = make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        raw_suffix="20250101120000",
        status="RUNNING",
    )
    visible = make_agent(cl_name="visible", raw_suffix="20250101130000")
    dismissed_ids = {dismissed_done.identity}

    with (
        patch(
            "sase.ace.tui.models.load_all_agents",
            return_value=[dismissed_done, running_alias, visible],
        ),
        patch("sase.ace.agent_tags.load_agent_tags", return_value={}),
        patch(
            "sase.ace.tui.actions.agents._snapshot_cache.AgentSnapshotCache"
            ".dismissed_bundles",
            return_value=[],
        ),
    ):
        all_agents, dismissed_from_loader = load_agents_from_disk(dismissed_ids)

    assert all_agents == [dismissed_done, running_alias, visible]
    assert dismissed_from_loader == [dismissed_done]
    assert running_alias not in dismissed_from_loader


def test_startup_loader_does_not_hydrate_dismissed_archive() -> None:
    """Perf sentinel: Phase 2 should stop touching dismissed bundles here."""

    with (
        patch("sase.ace.tui.models.load_all_agents", return_value=[]),
        patch("sase.ace.agent_tags.load_agent_tags", return_value={}),
        patch(
            "sase.ace.tui.actions.agents._snapshot_cache.AgentSnapshotCache"
            ".dismissed_bundles",
            return_value=[],
        ) as mock_dismissed_bundles,
    ):
        load_agents_from_disk(set())

    mock_dismissed_bundles.assert_not_called()


def test_revive_grouping_restores_children_loaded_from_child_bundle_filenames(
    tmp_path: Path,
) -> None:
    """Revive groups parent and ``__c{idx}`` child bundles by parent timestamp."""

    from sase.ace.dismissed_agents import load_dismissed_bundles

    bundles_dir = tmp_path / "bundles"
    parent, children, _ = build_workflow_collision_archive(bundles_dir)

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        loaded = load_dismissed_bundles({parent.raw_suffix or ""})

    loaded_parent = next(agent for agent in loaded if not agent.is_workflow_child)
    app = FakeReviveApp()
    app._dismissed_agent_objects = loaded
    app._dismissed_agents = {agent.identity for agent in loaded}

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.remove_bundle_by_identity") as mock_remove,
    ):
        app._do_revive_agent(loaded_parent)

    assert {identity for identity, _ in app.restored} == {
        parent.identity,
        *(child.identity for child in children),
    }
    assert mock_remove.call_args.kwargs == {"child_raw_suffixes": {parent.raw_suffix}}
    assert app.load_count == 1


def test_revive_archive_load_repairs_identity_index_on_demand() -> None:
    """Archive open, not startup, recovers bundle identities and prunes orphans."""

    archived = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="archived",
        raw_suffix="20250101140000",
    )
    orphan = (AgentType.WORKFLOW, "missing", "20250101150000")
    app = FakeReviveApp()
    app._dismissed_agents = {orphan}

    with (
        patch(
            "sase.ace.dismissed_agents.load_dismissed_bundles",
            return_value=[archived],
        ),
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
    ):
        loaded = app._load_dismissed_archive()

    assert loaded == [archived]
    assert archived._loaded_from_dismissed_bundle is True
    assert app._dismissed_agents == {archived.identity}
    mock_save.assert_called_once_with(app._dismissed_agents)
