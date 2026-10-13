"""Summary query tests for dismissed bundle indexing.

Split from ``tests.test_dismissed_bundle_index``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import (
    load_dismissed_bundle_summaries,
    load_dismissed_bundles,
    rebuild_dismissed_bundle_index,
    save_dismissed_bundle,
)
from sase.ace.dismissed_bundle_index import rebuild_index
from sase.ace.tui.models.agent import AgentType
from tests._dismissed_agents_helpers import make_agent

__all__ = [
    "test_dismissed_bundle_index_query_summaries_supports_offset",
    "test_dismissed_bundle_index_summary_fields",
    "test_load_dismissed_bundles_by_suffix_uses_legacy_index",
    "test_summary_does_not_treat_stop_time_as_dismissed_at",
]


def test_dismissed_bundle_index_query_summaries_supports_offset(
    tmp_path: Path,
) -> None:
    """Offset paging returns disjoint newest-first summary pages."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        for suffix in (
            "20250615100000",
            "20250615110000",
            "20250615120000",
        ):
            agent = make_agent(cl_name="indexed_cl", raw_suffix=suffix)
            agent.start_time = datetime.strptime(suffix, "%Y%m%d%H%M%S")
            save_dismissed_bundle(agent)
        assert rebuild_dismissed_bundle_index() == (3, 0)

        first_page = load_dismissed_bundle_summaries(
            cl_name="indexed_cl",
            limit=2,
            offset=0,
        )
        second_page = load_dismissed_bundle_summaries(
            cl_name="indexed_cl",
            limit=2,
            offset=2,
        )

    assert [summary.raw_suffix for summary in first_page] == [
        "20250615120000",
        "20250615110000",
    ]
    assert [summary.raw_suffix for summary in second_page] == ["20250615100000"]


def test_dismissed_bundle_index_summary_fields(tmp_path: Path) -> None:
    """Summary rows expose storage, provenance, and capability fields."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent(
            cl_name="indexed_cl",
            raw_suffix="20250615100000",
            status="FAILED",
        )
        agent.agent_name = "indexed_agent"
        agent.model = "gpt-test"
        agent.llm_provider = "codex"
        agent.agent_session = "session-1"
        agent.agent_session_role = "code"
        agent.agent_clan = "clan-1"
        agent.agent_clan_generation = "generation-2"
        agent.agent_tab = "review"
        agent.tribe = "backend"
        agent.clan_tribe = "research"
        bundle = agent.to_bundle_dict()
        shard = bundles_dir / "202506"
        shard.mkdir(parents=True)
        (shard / "20250615100000.json").write_text(json.dumps(bundle))

        assert rebuild_dismissed_bundle_index() == (1, 0)
        [summary] = load_dismissed_bundle_summaries(cl_name="indexed_cl")

    assert summary.raw_suffix == "20250615100000"
    assert summary.bundle_path.endswith("20250615100000.json")
    assert summary.shard == "202506"
    assert summary.filename == "20250615100000.json"
    assert summary.agent_type == AgentType.RUNNING.value
    assert summary.cl_name == "indexed_cl"
    assert summary.agent_name == "indexed_agent"
    assert summary.status == "FAILED"
    assert summary.model == "gpt-test"
    assert summary.llm_provider == "codex"
    assert summary.agent_session == "session-1"
    assert summary.agent_session_role == "code"
    assert summary.agent_clan == "clan-1"
    assert summary.agent_clan_generation == "generation-2"
    assert summary.agent_tab == "review"
    assert summary.tribe == "backend"
    assert summary.clan_tribe == "research"
    assert set(summary.__dataclass_fields__) == {
        "agent_id",
        "agent_clan",
        "agent_clan_generation",
        "agent_session",
        "agent_session_role",
        "agent_tab",
        "agent_name",
        "agent_type",
        "bundle_path",
        "cl_name",
        "clan_tribe",
        "filename",
        "archive_payload_sha256",
        "archive_visibility",
        "dismissed_at",
        "durably_revivable",
        "historically_viewable",
        "is_workflow_child",
        "llm_provider",
        "missing_requirements",
        "meta_changespec",
        "model",
        "parent_timestamp",
        "project_file",
        "project_name",
        "raw_suffix",
        "restartable",
        "revived_at",
        "retried_as_timestamp",
        "retry_attempt",
        "retry_chain_root_timestamp",
        "retry_of_timestamp",
        "runtime",
        "shard",
        "source_machine",
        "source_run_id",
        "source_username",
        "start_time",
        "status",
        "step_index",
        "step_name",
        "step_type",
        "stop_time",
        "times_revived",
        "tribe",
        "vcs_provider",
        "workflow",
    }


def test_summary_does_not_treat_stop_time_as_dismissed_at(tmp_path: Path) -> None:
    """Legacy bundle summaries keep end time and dismissal time distinct."""
    bundles_dir = tmp_path / "bundles"
    shard = bundles_dir / "202506"
    shard.mkdir(parents=True)
    (shard / "20250615100000.json").write_text(
        json.dumps(
            {
                "raw_suffix": "20250615100000",
                "agent_type": "run",
                "cl_name": "timestamps",
                "status": "DONE",
                "stop_time": "2025-06-15T11:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        assert rebuild_index(bundles_dir).indexed_rows == 1
        [summary] = load_dismissed_bundle_summaries(cl_name="timestamps")

    assert summary.stop_time == "2025-06-15T11:00:00+00:00"
    assert summary.dismissed_at is None


def test_load_dismissed_bundles_by_suffix_uses_legacy_index(tmp_path: Path) -> None:
    """Indexed suffix loads return parent and child legacy bundle files."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        parent = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="indexed_cl",
            raw_suffix="20250615100000",
            workflow="wf",
        )
        child = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="indexed_cl",
            raw_suffix="20250615100000",
            parent_workflow="wf",
            parent_timestamp="20250615100000",
            step_index=0,
        )
        save_dismissed_bundle(parent)
        save_dismissed_bundle(child)
        assert rebuild_dismissed_bundle_index() == (2, 0)

        loaded = load_dismissed_bundles({"20250615100000"})

    assert len(loaded) == 2
    assert sorted(
        agent.step_index for agent in loaded if agent.step_index is not None
    ) == [0]
