"""Tests for sase.logs.workspace_claim_ledger."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.logs.workspace_claim_ledger import (
    read_ledger_records,
    record_running_field_mutation,
)


class TestRecordRunningFieldMutation:
    def test_appends_success_record_with_before_after_occupancy(
        self, tmp_path: Path
    ) -> None:
        ledger_file = str(tmp_path / "workspace_claims.jsonl")
        before = "NAME: x\n"
        after = "NAME: x\nRUNNING:\n  #3 | 12345 | crs | feature\n"
        with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
            record_running_field_mutation(
                operation="claim",
                project_file="/tmp/proj.sase",
                workspace_num=3,
                success=True,
                before_content=before,
                after_content=after,
                workflow="crs",
                cl_name="feature",
                artifacts_timestamp="260818_130000",
                claim_pid=12345,
                caller_tag="test-caller",
            )

        lines = Path(ledger_file).read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["operation"] == "claim"
        assert record["workspace_num"] == 3
        assert record["success"] is True
        assert record["caller_tag"] == "test-caller"
        assert record["claim_pid"] == 12345
        assert record["before"] == []
        assert record["after"] == [
            {
                "workspace_num": 3,
                "workflow": "crs",
                "cl_name": "feature",
                "pid": 12345,
                "artifacts_timestamp": None,
                "pinned": False,
            }
        ]
        assert "actor_pid" in record
        assert "actor_ppid" in record
        assert "timestamp" in record

    def test_failure_record_carries_error_and_unchanged_occupancy(
        self, tmp_path: Path
    ) -> None:
        ledger_file = str(tmp_path / "workspace_claims.jsonl")
        content = "NAME: x\nRUNNING:\n  #3 | 999 | crs | other\n"
        with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
            record_running_field_mutation(
                operation="claim",
                project_file="/tmp/proj.sase",
                workspace_num=3,
                success=False,
                before_content=content,
                workflow="crs",
                error="workspace #3 claim rejected by core",
            )

        record = json.loads(Path(ledger_file).read_text().strip())
        assert record["success"] is False
        assert record["error"] == "workspace #3 claim rejected by core"
        assert record["before"] == record["after"]
        assert len(record["before"]) == 1
        assert record["before"][0]["pid"] == 999

    def test_never_raises_on_write_failure(self, tmp_path: Path) -> None:
        with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", str(tmp_path)):
            # LEDGER_FILE points at a directory, so opening it for append
            # raises IsADirectoryError -- the call must swallow it.
            record_running_field_mutation(
                operation="claim",
                project_file="/tmp/proj.sase",
                workspace_num=1,
                success=True,
                before_content="",
            )


class TestReadLedgerRecords:
    def test_reads_records_in_file_order(self, tmp_path: Path) -> None:
        ledger_file = str(tmp_path / "workspace_claims.jsonl")
        with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
            record_running_field_mutation(
                operation="claim",
                project_file="/tmp/a.sase",
                workspace_num=1,
                success=True,
                before_content="",
            )
            record_running_field_mutation(
                operation="release",
                project_file="/tmp/a.sase",
                workspace_num=1,
                success=True,
                before_content="",
            )

            records = read_ledger_records(ledger_file=ledger_file)

        assert [r["operation"] for r in records] == ["claim", "release"]

    def test_filters_by_project_file_and_workspace_num(self, tmp_path: Path) -> None:
        ledger_file = str(tmp_path / "workspace_claims.jsonl")
        with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
            record_running_field_mutation(
                operation="claim",
                project_file="/tmp/a.sase",
                workspace_num=1,
                success=True,
                before_content="",
            )
            record_running_field_mutation(
                operation="claim",
                project_file="/tmp/b.sase",
                workspace_num=2,
                success=True,
                before_content="",
            )

            records = read_ledger_records(
                project_file="/tmp/a.sase", ledger_file=ledger_file
            )

        assert len(records) == 1
        assert records[0]["project_file"] == "/tmp/a.sase"

    def test_returns_empty_list_when_ledger_missing(self, tmp_path: Path) -> None:
        missing = str(tmp_path / "does_not_exist.jsonl")
        assert read_ledger_records(ledger_file=missing) == []

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        ledger_file = tmp_path / "workspace_claims.jsonl"
        ledger_file.write_text("not json\n" + json.dumps({"operation": "claim"}) + "\n")

        records = read_ledger_records(ledger_file=str(ledger_file))

        assert len(records) == 1
        assert records[0]["operation"] == "claim"
