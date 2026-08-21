"""Tests for write_result_marker payloads and the accumulated results list."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.workflows.commit.commit_tracking import write_result_marker


class TestWriteResultMarker:
    """Verify write_result_marker writes correct marker file."""

    def test_writes_marker_with_all_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "fix: bug", "name": "feat-x"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                write_result_marker(
                    "create_commit", payload, None, "abc123", "proj_feat_1"
                )

            marker_path = Path(tmpdir) / "commit_result.json"
            assert marker_path.exists()
            data = json.loads(marker_path.read_text())
            assert data == {
                "method": "create_commit",
                "run_id": Path(tmpdir).name,
                "cwd": os.getcwd(),
                "result": "abc123",
                "commit_result": "abc123",
                "message": "fix: bug",
                "name": "feat-x",
                "bead_id": "",
                "patch_name": "proj_feat_1",
                "changespec_name": "proj_feat_1",
                "commit_patch_name": "proj_feat_1",
                "commit_changespec_name": "proj_feat_1",
                "entry_id": None,
                "stitch_id": None,
                "commit_entry_id": None,
                "diff_path": None,
                "commit_diff_path": None,
            }

    def test_writes_committed_at_when_resolver_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "fix: bug"}
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch(
                    "sase.workflows.commit.commit_tracking._resolve_commit_created_at",
                    return_value=1_700_000_000,
                ),
            ):
                write_result_marker("create_commit", payload, None, "abc123", None)

            data = json.loads((Path(tmpdir) / "commit_result.json").read_text())
            assert data["committed_at"] == 1_700_000_000
            results = json.loads((Path(tmpdir) / "commit_results.json").read_text())
            assert results[0]["committed_at"] == 1_700_000_000

    def test_resolver_failure_still_writes_complete_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "fix: bug", "name": "feat-x"}
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch(
                    "sase.vcs_provider.get_vcs_provider",
                    side_effect=RuntimeError("provider unavailable"),
                ),
            ):
                write_result_marker(
                    "create_commit", payload, None, "abc123", "proj_feat_1"
                )

            data = json.loads((Path(tmpdir) / "commit_result.json").read_text())
            assert "committed_at" not in data
            assert data == {
                "method": "create_commit",
                "run_id": Path(tmpdir).name,
                "cwd": os.getcwd(),
                "result": "abc123",
                "commit_result": "abc123",
                "message": "fix: bug",
                "name": "feat-x",
                "bead_id": "",
                "patch_name": "proj_feat_1",
                "changespec_name": "proj_feat_1",
                "commit_patch_name": "proj_feat_1",
                "commit_changespec_name": "proj_feat_1",
                "entry_id": None,
                "stitch_id": None,
                "commit_entry_id": None,
                "diff_path": None,
                "commit_diff_path": None,
            }

    def test_writes_none_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "test"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                write_result_marker("create_proposal", payload, None, None, None)

            data = json.loads((Path(tmpdir) / "commit_result.json").read_text())
            assert data["result"] is None
            assert data["patch_name"] is None
            assert data["changespec_name"] is None
            assert data["stitch_id"] is None
            assert data["entry_id"] is None

    def test_writes_marker_with_entry_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "fix: bug"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                write_result_marker(
                    "create_commit", payload, None, "abc123", None, entry_id="entry_42"
                )

            data = json.loads((Path(tmpdir) / "commit_result.json").read_text())
            assert data["entry_id"] == "entry_42"
            assert data["stitch_id"] == "entry_42"
            assert data["commit_entry_id"] == "entry_42"

    def test_accumulates_commit_results_and_upserts_entry_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "fix: primary"}
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch("os.getcwd", return_value="/workspace/sase_7"),
            ):
                write_result_marker(
                    "create_commit",
                    payload,
                    "/tmp/primary.diff",
                    "abc123",
                    "proj_feat_1",
                )

            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch("os.getcwd", return_value="/workspace/sase-core_7"),
            ):
                write_result_marker(
                    "create_commit",
                    {"message": "fix: linked"},
                    "/tmp/linked.diff",
                    "def456",
                    "proj_feat_1",
                )

            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch("os.getcwd", return_value="/workspace/sase_7"),
            ):
                write_result_marker(
                    "create_commit",
                    payload,
                    "/tmp/primary.diff",
                    "abc123",
                    "proj_feat_1",
                    entry_id="entry_1",
                )

            latest = json.loads((Path(tmpdir) / "commit_result.json").read_text())
            assert latest["cwd"] == "/workspace/sase_7"
            assert latest["result"] == "abc123"
            assert latest["entry_id"] == "entry_1"

            results = json.loads((Path(tmpdir) / "commit_results.json").read_text())
            assert [item["cwd"] for item in results] == [
                "/workspace/sase_7",
                "/workspace/sase-core_7",
            ]
            assert [item["result"] for item in results] == ["abc123", "def456"]
            assert results[0]["entry_id"] == "entry_1"
            assert results[1]["entry_id"] is None

    def test_corrupt_commit_results_file_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "commit_results.json").write_text("{", encoding="utf-8")
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch("os.getcwd", return_value="/workspace/sase_7"),
            ):
                write_result_marker(
                    "create_commit",
                    {"message": "fix: bug"},
                    None,
                    "abc123",
                    None,
                )

            results = json.loads((Path(tmpdir) / "commit_results.json").read_text())
            assert len(results) == 1
            assert results[0]["cwd"] == "/workspace/sase_7"
            assert results[0]["result"] == "abc123"

    def test_writes_agent_run_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "fix: bug"}
            with patch.dict(
                "os.environ",
                {
                    "SASE_ARTIFACTS_DIR": tmpdir,
                    "SASE_AGENT_TIMESTAMP": "20260522112233",
                },
            ):
                write_result_marker("create_commit", payload, None, "abc123", None)

            data = json.loads((Path(tmpdir) / "commit_result.json").read_text())
            assert data["run_id"] == "20260522112233"
            assert data["cwd"] == os.getcwd()

    def test_skips_when_no_artifacts_dir(self) -> None:
        payload = {"message": "test"}
        with patch.dict("os.environ", {}, clear=True):
            # Should not raise
            write_result_marker("create_commit", payload, None, "abc", None)

    def test_records_commit_sha_and_tree_when_provided(self) -> None:
        """The run-owned ledger fields are additive: absent unless resolved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "fix: bug"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                write_result_marker(
                    "create_commit",
                    payload,
                    None,
                    None,
                    None,
                    commit_sha="a" * 40,
                    commit_tree="b" * 40,
                )

            data = json.loads((Path(tmpdir) / "commit_result.json").read_text())
            assert data["commit_sha"] == "a" * 40
            assert data["commit_tree"] == "b" * 40
            results = json.loads((Path(tmpdir) / "commit_results.json").read_text())
            assert results[0]["commit_sha"] == "a" * 40
            assert results[0]["commit_tree"] == "b" * 40

    def test_omits_commit_sha_and_tree_when_not_resolved(self) -> None:
        """A resolution failure must not add placeholder keys to the marker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "fix: bug"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                write_result_marker("create_commit", payload, None, "abc123", None)

            data = json.loads((Path(tmpdir) / "commit_result.json").read_text())
            assert "commit_sha" not in data
            assert "commit_tree" not in data

    def test_explicit_commit_cwd_overrides_ambient_working_directory(self) -> None:
        """Resume/direct callers can attribute the marker to a checkpointed repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "docs: update plan"}
            explicit_cwd = "/workspace/sase_7/sase/repos/plans"
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch("os.getcwd", return_value="/workspace/sase_7"),
                patch(
                    "sase.workflows.commit.commit_tracking._resolve_commit_created_at",
                    return_value=1_700_000_000,
                ) as resolve_created_at,
            ):
                write_result_marker(
                    "create_commit",
                    payload,
                    "/tmp/plans.diff",
                    "84aeb6a1",
                    None,
                    commit_cwd=explicit_cwd,
                )

            resolve_created_at.assert_called_once_with(explicit_cwd, "84aeb6a1")
            latest = json.loads((Path(tmpdir) / "commit_result.json").read_text())
            assert latest["cwd"] == explicit_cwd
            assert latest["result"] == "84aeb6a1"
            results = json.loads((Path(tmpdir) / "commit_results.json").read_text())
            assert len(results) == 1
            assert results[0]["cwd"] == explicit_cwd
            assert results[0]["result"] == "84aeb6a1"
            assert results[0]["committed_at"] == 1_700_000_000
