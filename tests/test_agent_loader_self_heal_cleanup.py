"""Tests for loader self-healing artifact cleanup and dismissed bundles."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents import _loading
from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.models.agent import AgentType
from tests._agent_loader_self_heal_helpers import (
    SOURCE_SCAN_STATE,
    FakeLoadingApp,
    clear_cleaned_artifact_cache,
    make_agent,
)


@pytest.fixture(autouse=True)
def _clear_cleaned_artifact_cache() -> None:
    clear_cleaned_artifact_cache()


def test_self_heal_skips_cleanup_for_missing_artifacts_dir(tmp_path: Path) -> None:
    """Non-existent artifacts dir is cached after first check."""
    app = FakeLoadingApp()
    missing_dir = str(tmp_path / "gone")
    agent = make_agent(artifacts_dir=missing_dir)
    app._dismissed_agents = {agent.identity}

    with patch(
        "sase.ace.tui.actions.agents._killing.delete_agent_artifacts"
    ) as mock_delete:
        app._apply_loaded_agents(
            [], [agent], on_agents_tab=False, selected_identity=None
        )

    assert mock_delete.call_count == 0
    assert missing_dir in _loading._CLEANED_ARTIFACT_DIRS


def test_self_heal_cleans_and_caches_existing_dir(tmp_path: Path) -> None:
    """Existing artifacts dir is cleaned once and then cached."""
    app = FakeLoadingApp()
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    agent = make_agent(artifacts_dir=str(artifacts_dir))
    app._dismissed_agents = {agent.identity}

    with patch(
        "sase.ace.tui.actions.agents._killing.delete_agent_artifacts"
    ) as mock_delete:
        app._apply_loaded_agents(
            [], [agent], on_agents_tab=False, selected_identity=None
        )
        assert mock_delete.call_count == 1

        # Second reload: the cache should short-circuit the cleanup.
        app._apply_loaded_agents(
            [], [agent], on_agents_tab=False, selected_identity=None
        )
        assert mock_delete.call_count == 1

    assert str(artifacts_dir) in _loading._CLEANED_ARTIFACT_DIRS


def test_self_heal_skips_second_reload_even_for_missing_dir(tmp_path: Path) -> None:
    """Regression guard: after caching a missing dir, do not re-check it."""
    app = FakeLoadingApp()
    missing_dir = str(tmp_path / "still_gone")
    agent = make_agent(artifacts_dir=missing_dir)
    app._dismissed_agents = {agent.identity}

    checked_paths: list[str] = []

    def fake_is_dir(path: Path) -> bool:
        checked_paths.append(str(path))
        return False

    with patch.object(Path, "is_dir", autospec=True, side_effect=fake_is_dir):
        app._apply_loaded_agents(
            [], [agent], on_agents_tab=False, selected_identity=None
        )
        first_missing_dir_checks = checked_paths.count(missing_dir)
        app._apply_loaded_agents(
            [], [agent], on_agents_tab=False, selected_identity=None
        )
        # Second reload: no additional is_dir() checks for this artifacts_dir
        # (the orphan-bundle path may still stat the bundles dir).
        assert checked_paths.count(missing_dir) == first_missing_dir_checks


def test_cleanup_does_not_probe_bundles_for_orphaned_identities() -> None:
    """Startup cleanup no longer scans bundles for missing dismissed rows."""
    raw_suffix = "20240101120000"
    identity = (AgentType.WORKFLOW, "archived", raw_suffix)

    with (
        patch("sase.ace.dismissed_agents.has_dismissed_bundle") as mock_has_bundle,
        patch("sase.ace.tui.actions.agents._killing.delete_agent_artifacts"),
    ):
        orphaned, cleaned_dirs = _loading._compute_loader_cleanup({identity}, [])

    assert orphaned == set()
    assert cleaned_dirs == set()
    mock_has_bundle.assert_not_called()


def test_cleanup_defers_busy_database_without_caching_dir(tmp_path: Path) -> None:
    """A busy cleanup target remains eligible for the next self-healing pass."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    agent = make_agent(artifacts_dir=str(artifacts_dir))

    with patch(
        "sase.ace.tui.actions.agents._killing.delete_agent_artifacts",
        side_effect=sqlite3.OperationalError("database is locked"),
    ):
        orphaned, cleaned_dirs = _loading._compute_loader_cleanup(
            {agent.identity}, [agent]
        )

    assert orphaned == set()
    assert cleaned_dirs == set()
    assert str(artifacts_dir) not in _loading._CLEANED_ARTIFACT_DIRS


def test_cleanup_defers_bounded_index_timeout_without_caching_dir(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    agent = make_agent(artifacts_dir=str(artifacts_dir))

    with patch(
        "sase.ace.tui.actions.agents._killing.delete_agent_artifacts",
        return_value=False,
    ):
        _, cleaned_dirs = _loading._compute_loader_cleanup({agent.identity}, [agent])

    assert cleaned_dirs == set()
    assert str(artifacts_dir) not in _loading._CLEANED_ARTIFACT_DIRS


def test_load_agents_from_disk_does_not_include_bundle_only_archive_rows() -> None:
    """Startup revive candidates come from loader rows, not the full archive."""
    bundled = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="bundle_only",
        raw_suffix="20240102120000",
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.load_tiered_agents",
            return_value=([], SOURCE_SCAN_STATE),
        ),
        patch(
            "sase.ace.tui.actions.agents._snapshot_cache.AgentSnapshotCache"
            ".dismissed_bundles",
            return_value=[bundled],
        ) as mock_dismissed_bundles,
    ):
        load_result = load_agents_from_disk_with_state(set())

    assert load_result.all_agents == []
    assert load_result.dismissed_from_loader == []
    mock_dismissed_bundles.assert_not_called()


def test_apply_loaded_agents_repairs_dismissed_index_from_bundle() -> None:
    """Recovered bundle candidates are persisted back into dismissed_agents."""
    app = FakeLoadingApp()
    bundled = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="bundle_only",
        raw_suffix="20240102120000",
    )
    bundled._loaded_from_dismissed_bundle = True

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
        patch("sase.ace.tui.actions.agents._killing.delete_agent_artifacts"),
    ):
        app._apply_loaded_agents(
            [], [bundled], on_agents_tab=False, selected_identity=None
        )

    assert bundled.identity in app._dismissed_agents
    mock_save.assert_called_once_with(app._dismissed_agents)
    assert app._artifact_index_maintenance_pending_request == (
        {bundled.identity},
        {bundled.identity},
        False,
        "apply",
    )
