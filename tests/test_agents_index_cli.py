"""CLI coverage for persistent agent artifact index maintenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agents.cli_index import handle_agents_index
from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.core.agent_scan_wire import (
    AgentArtifactIndexUpdateWire,
    AgentArtifactIndexVerifyWire,
)


def _index_args(subcommand: str) -> argparse.Namespace:
    return argparse.Namespace(
        index_subcommand=subcommand,
        index_path="/tmp/index.sqlite",
        projects_root="/tmp/projects",
        json=True,
    )


def test_index_gc_syncs_dismissed_identities_and_reports_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    dismissed = [
        AgentCleanupIdentityWire(
            agent_type="run",
            cl_name="unknown",
            raw_suffix="20260520101010",
        )
    ]
    with (
        patch(
            "sase.agents.cli_index.verify_agent_artifact_index",
            return_value=AgentArtifactIndexVerifyWire(
                ok=False,
                schema_version=1,
                index_path="/tmp/index.sqlite",
                projects_root="/tmp/projects",
                indexed_rows=2,
                source_rows=3,
                missing_rows=1,
                extra_rows=1,
            ),
        ),
        patch(
            "sase.agents.cli_index.rebuild_agent_artifact_index",
            return_value=AgentArtifactIndexUpdateWire(
                schema_version=1,
                index_path="/tmp/index.sqlite",
                projects_root="/tmp/projects",
                rows_indexed=3,
            ),
        ),
        patch(
            "sase.agents.cli_index._load_dismissed_identities_for_gc",
            return_value=(dismissed, 0),
        ),
        patch(
            "sase.agents.cli_index.replace_agent_artifact_index_dismissed_agents",
            return_value=AgentArtifactIndexUpdateWire(
                schema_version=1,
                index_path="/tmp/index.sqlite",
                projects_root="",
                rows_indexed=1,
            ),
        ) as mock_hide,
    ):
        handle_agents_index(_index_args("gc"))

    mock_hide.assert_called_once_with(Path("/tmp/index.sqlite"), dismissed)
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows_indexed"] == 3
    assert payload["rows_deleted"] == 1
    assert payload["rows_hidden"] == 1
    assert payload["missing_rows_indexed"] == 1


def test_index_unknown_subcommand_prints_maintenance_usage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_agents_index(_index_args("search"))

    assert excinfo.value.code == 1
    assert "Usage: sase agents index {gc,rebuild,verify}" in capsys.readouterr().out
