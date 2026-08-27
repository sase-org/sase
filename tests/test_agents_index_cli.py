"""CLI coverage for persistent agent artifact index maintenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agents.cli_index import handle_agents_index
from sase.agents.index_repair import _ImportedStateRepairPlan
from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.core.agent_scan_wire import (
    AgentArtifactIndexStatusWire,
    AgentArtifactIndexUpdateWire,
    AgentArtifactIndexVacuumWire,
    AgentArtifactIndexVerifyWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)


def _index_args(subcommand: str) -> argparse.Namespace:
    return argparse.Namespace(
        index_subcommand=subcommand,
        index_path="/tmp/index.sqlite",
        projects_root="/tmp/projects",
        json=True,
        apply=False,
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
        patch(
            "sase.agents.cli_index.prune_hidden_terminal_agent_artifact_index_rows",
            return_value=AgentArtifactIndexUpdateWire(
                schema_version=1,
                index_path="/tmp/index.sqlite",
                projects_root="",
                hidden_terminal_rows_retained=4096,
                hidden_terminal_rows_pruned=4,
            ),
        ) as mock_prune,
    ):
        handle_agents_index(_index_args("gc"))

    mock_hide.assert_called_once_with(Path("/tmp/index.sqlite"), dismissed)
    mock_prune.assert_called_once_with(Path("/tmp/index.sqlite"))
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows_indexed"] == 3
    assert payload["rows_deleted"] == 1
    assert payload["rows_hidden"] == 1
    assert payload["missing_rows_indexed"] == 1
    assert payload["hidden_terminal_rows_pruned"] == 4


def test_index_gc_rebuilds_after_corrupt_preflight_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch(
            "sase.agents.cli_index.verify_agent_artifact_index",
            return_value=AgentArtifactIndexVerifyWire(
                ok=False,
                schema_version=0,
                index_path="/tmp/index.sqlite",
                projects_root="/tmp/projects",
                indexed_rows=0,
                source_rows=2,
                missing_rows=2,
                corrupt_rows=1,
            ),
        ),
        patch(
            "sase.agents.cli_index.rebuild_agent_artifact_index",
            return_value=AgentArtifactIndexUpdateWire(
                schema_version=1,
                index_path="/tmp/index.sqlite",
                projects_root="/tmp/projects",
                rows_indexed=2,
            ),
        ) as mock_rebuild,
        patch(
            "sase.agents.cli_index._load_dismissed_identities_for_gc",
            return_value=([], 0),
        ),
        patch(
            "sase.agents.cli_index.replace_agent_artifact_index_dismissed_agents",
            return_value=AgentArtifactIndexUpdateWire(
                schema_version=1,
                index_path="/tmp/index.sqlite",
                projects_root="",
            ),
        ),
        patch(
            "sase.agents.cli_index.prune_hidden_terminal_agent_artifact_index_rows",
            return_value=AgentArtifactIndexUpdateWire(
                schema_version=1,
                index_path="/tmp/index.sqlite",
                projects_root="",
            ),
        ),
    ):
        handle_agents_index(_index_args("gc"))

    mock_rebuild.assert_called_once_with(
        Path("/tmp/index.sqlite"), Path("/tmp/projects")
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["corrupt_rows"] == 1
    assert payload["rows_indexed"] == 2


def test_index_status_missing_index_recommends_repair(
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle_agents_index(_index_args("status"))

    payload = json.loads(capsys.readouterr().out)
    assert payload["complete_visible_inbox"] is False
    assert payload["repair_recommended"] is True
    assert payload["repair_reason"] == "artifact_index_missing"
    assert payload["repair_command"] == "sase agent index gc"


def test_index_status_json_reports_visible_inbox_without_verify_scan(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    index_path = tmp_path / "index.sqlite"
    index_path.touch()

    args = _index_args("status")
    args.index_path = str(index_path)
    with (
        patch(
            "sase.agents.cli_index.agent_artifact_index_status",
            return_value=AgentArtifactIndexStatusWire(
                schema_version=3,
                index_path=str(index_path),
                agent_artifacts_rows=5,
                dismissed_agents_rows=1,
            ),
        ) as mock_status,
        patch(
            "sase.agents.cli_index.query_agent_artifact_index",
            return_value=AgentArtifactScanWire(
                schema_version=1,
                projects_root="/tmp/projects",
                options=AgentArtifactScanOptionsWire(),
                stats=AgentArtifactScanStatsWire(),
                records=[],
            ),
        ) as mock_query,
    ):
        handle_agents_index(args)

    mock_status.assert_called_once_with(index_path)
    mock_query.assert_called_once()
    payload = json.loads(capsys.readouterr().out)
    assert payload["complete_visible_inbox"] is True
    assert payload["complete_history"] is False
    assert payload["dismissed_projection_rows"] == 1
    assert payload["indexed_rows"] == 5
    assert payload["normal_refresh"] == "visible-inbox artifact-index query"
    assert payload["repair_recommended"] is False


def test_index_vacuum_dry_run_reports_freelist_without_applying(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    index_path = tmp_path / "index.sqlite"
    index_path.touch()

    args = _index_args("vacuum")
    args.index_path = str(index_path)
    with (
        patch(
            "sase.agents.cli_index.agent_artifact_index_status",
            return_value=AgentArtifactIndexStatusWire(
                schema_version=3,
                index_path=str(index_path),
                dismissed_agents_rows=38243,
                freelist_pages=4838,
                freelist_bytes=19_820_544,
                file_size_bytes=194_700_000,
            ),
        ) as mock_status,
        patch("sase.agents.cli_index.vacuum_agent_artifact_index") as mock_vacuum,
    ):
        handle_agents_index(args)

    mock_status.assert_called_once_with(index_path)
    mock_vacuum.assert_not_called()
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is False
    assert payload["freelist_pages"] == 4838
    assert payload["dismissed_agents_rows"] == 38243


def test_index_vacuum_apply_runs_vacuum(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    index_path = tmp_path / "index.sqlite"
    index_path.touch()

    args = _index_args("vacuum")
    args.index_path = str(index_path)
    args.apply = True
    with (
        patch("sase.agents.cli_index.agent_artifact_index_status") as mock_status,
        patch(
            "sase.agents.cli_index.vacuum_agent_artifact_index",
            return_value=AgentArtifactIndexVacuumWire(
                index_path=str(index_path),
                freelist_pages_before=4838,
                freelist_pages_after=0,
                file_size_bytes_before=194_700_000,
                file_size_bytes_after=174_879_456,
                bytes_reclaimed=19_820_544,
            ),
        ) as mock_vacuum,
    ):
        handle_agents_index(args)

    mock_status.assert_not_called()
    mock_vacuum.assert_called_once_with(index_path)
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert payload["bytes_reclaimed"] == 19_820_544
    assert payload["freelist_pages_after"] == 0


def test_index_unknown_subcommand_prints_maintenance_usage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_agents_index(_index_args("search"))

    assert excinfo.value.code == 1
    assert (
        "Usage: sase agent index {gc,rebuild,repair,status,vacuum,verify}"
        in capsys.readouterr().out
    )


def test_index_repair_is_dry_run_by_default(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _ImportedStateRepairPlan(
        artifacts=(Path("/tmp/projects/proj/artifacts/ace-run/20990102030405"),),
        bundles=(Path("/tmp/dismissed_bundles/209901/20990102030405.json"),),
        dismissed_identities=frozenset(),
        journals=(),
        registry_names=("ghost",),
        transaction_keys=frozenset(),
    )
    with (
        patch(
            "sase.agents.index_repair.plan_imported_state_repair",
            return_value=plan,
        ),
        patch("sase.agents.index_repair.apply_imported_state_repair") as apply_repair,
    ):
        handle_agents_index(_index_args("repair"))

    apply_repair.assert_not_called()
    assert json.loads(capsys.readouterr().out) == {
        "applied": False,
        "artifacts": 1,
        "bundles": 1,
        "index_rows": 1,
        "journals": 0,
        "registry_entries": 1,
    }
