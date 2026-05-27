"""Tests for commit diff-path metadata enrichment."""

import json
from pathlib import Path

from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.core.agent_scan_wire import AgentMetaWire
from tests._enrich_agent_helpers import make_agent


def test_commit_diff_path_populates_diff_path_from_filesystem_meta(
    tmp_path: Path,
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"commit_diff_path": "/tmp/commit.diff"}),
        encoding="utf-8",
    )

    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.diff_path == "/tmp/commit.diff"


def test_commit_diff_path_does_not_override_existing_diff_path(
    tmp_path: Path,
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"commit_diff_path": "/tmp/commit.diff"}),
        encoding="utf-8",
    )

    agent = make_agent(status="DONE")
    agent.diff_path = "/tmp/done.diff"
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.diff_path == "/tmp/done.diff"


def test_commit_diff_path_populates_diff_path_from_wire_meta() -> None:
    agent = make_agent(status="RUNNING")

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(commit_diff_path="/tmp/commit.diff"),
        None,
        None,
    )

    assert agent.diff_path == "/tmp/commit.diff"
