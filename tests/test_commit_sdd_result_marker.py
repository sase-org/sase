"""Tests for record_sdd_commit_result_marker's results-list-only bookkeeping."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.workflows.commit.commit_tracking import record_sdd_commit_result_marker


class TestRecordSddCommitResultMarker:
    """Verify SDD commits accumulate without touching the primary marker."""

    def test_records_sdd_commit_in_results_list_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "sase.workflows.commit.commit_tracking."
                "update_agent_artifact_index_for_marker_mutation"
            ) as update_index:
                record_sdd_commit_result_marker(
                    artifacts_dir=tmpdir,
                    cwd="/workspace/sase/.sase/sdd",
                    result="abc123",
                    message="Archive approved plan demo\n\nSASE_TYPE=sdd",
                    repo_name="sase-org/sase--sdd",
                )
                record_sdd_commit_result_marker(
                    artifacts_dir=tmpdir,
                    cwd="/workspace/sase/.sase/sdd",
                    result="abc123",
                    message="Archive approved plan demo updated\n\nSASE_TYPE=sdd",
                    repo_name="sase-org/sase--sdd",
                )

            assert not (Path(tmpdir) / "commit_result.json").exists()
            results = json.loads((Path(tmpdir) / "commit_results.json").read_text())
            assert results == [
                {
                    "method": "sdd_commit",
                    "run_id": Path(tmpdir).name,
                    "cwd": "/workspace/sase/.sase/sdd",
                    "result": "abc123",
                    "commit_result": "abc123",
                    "message": "Archive approved plan demo updated\n\nSASE_TYPE=sdd",
                    "repo_name": "sase-org/sase--sdd",
                    "diff_path": None,
                    "commit_diff_path": None,
                }
            ]
            assert update_index.call_count == 2
            update_index.assert_called_with(tmpdir)

    def test_sdd_commit_records_committed_at_when_resolver_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "sase.workflows.commit.commit_tracking._resolve_commit_created_at",
                return_value=1_700_000_000,
            ):
                record_sdd_commit_result_marker(
                    artifacts_dir=tmpdir,
                    cwd="/workspace/sase/.sase/sdd",
                    result="abc123",
                    message="Archive approved plan demo\n\nSASE_TYPE=sdd",
                    repo_name="sase-org/sase--sdd",
                )

            results = json.loads((Path(tmpdir) / "commit_results.json").read_text())
            assert results[0]["committed_at"] == 1_700_000_000

    def test_sdd_commit_without_repo_name_uses_store_directory_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            record_sdd_commit_result_marker(
                artifacts_dir=tmpdir,
                cwd="/workspace/sase/sase/repos/beads",
                result="abc123",
                message="chore(beads): update state",
            )

            results = json.loads((Path(tmpdir) / "commit_results.json").read_text())
            assert results[0]["repo_name"] == "beads"
