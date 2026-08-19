"""Tests for durable ledgering of RUNNING field claim mutations."""

from pathlib import Path
from unittest.mock import patch

from sase.logs.workspace_claim_ledger import read_ledger_records
from sase.running_field import (
    WorkspaceClaim,
    claim_workspace,
    release_workspace,
)
from tests._running_field_helpers import create_project_file_with_running


class TestWorkspaceClaimLedger:
    """Every claim/hold/transfer/release mutation is durably ledgered."""

    def test_claim_then_release_round_trip_produces_two_records(
        self, tmp_path: Path
    ) -> None:
        project_file = create_project_file_with_running(tmp_path)
        ledger_file = str(tmp_path / "workspace_claims.jsonl")
        try:
            with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
                claim_result = claim_workspace(
                    project_file,
                    5,
                    "crs",
                    12345,
                    "my_feature",
                    caller_tag="test-claim",
                )
                assert claim_result.success is True

                release_result = release_workspace(
                    project_file, 5, "crs", "my_feature", caller_tag="test-release"
                )
                assert release_result.success is True

                records = read_ledger_records(ledger_file=ledger_file)

            assert [r["operation"] for r in records] == ["claim", "release"]

            claim_record = records[0]
            assert claim_record["success"] is True
            assert claim_record["caller_tag"] == "test-claim"
            assert claim_record["before"] == []
            assert claim_record["after"] == [
                {
                    "workspace_num": 5,
                    "workflow": "crs",
                    "cl_name": "my_feature",
                    "pid": 12345,
                    "artifacts_timestamp": None,
                    "pinned": False,
                }
            ]

            release_record = records[1]
            assert release_record["success"] is True
            assert release_record["caller_tag"] == "test-release"
            assert release_record["claim_pid"] == 12345
            assert release_record["before"] == claim_record["after"]
            assert release_record["after"] == []
        finally:
            Path(project_file).unlink()

    def test_claim_rejection_is_ledgered_with_unchanged_occupancy(
        self, tmp_path: Path
    ) -> None:
        project_file = create_project_file_with_running(
            tmp_path, running_claims=[WorkspaceClaim(1, "crs", "existing", pid=11111)]
        )
        ledger_file = str(tmp_path / "workspace_claims.jsonl")
        try:
            with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
                result = claim_workspace(project_file, 1, "run", 22222, "other")
                assert result.success is False

                records = read_ledger_records(ledger_file=ledger_file)

            assert len(records) == 1
            record = records[0]
            assert record["success"] is False
            assert record["error"]
            assert record["before"] == record["after"]
            assert record["before"][0]["pid"] == 11111
        finally:
            Path(project_file).unlink()
