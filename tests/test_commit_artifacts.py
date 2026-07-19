"""Tests for CommitWorkflow result markers, PR bodies, and commit entries."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.workflows.commit.commit_tracking import (
    append_commits_entry,
    record_sdd_commit_result_marker,
    write_commit_diff_artifact,
    write_result_marker,
)
from sase.workflows.commit.pr_operations import build_pr_body


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
                "changespec_name": "proj_feat_1",
                "commit_changespec_name": "proj_feat_1",
                "entry_id": None,
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
            assert data["changespec_name"] is None
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

    def test_persists_primary_commit_metadata_without_graph_relationships(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta_path = Path(tmpdir) / "agent_meta.json"
            meta_path.write_text(json.dumps({"name": "agent-alpha"}))
            diff_path = str(Path(tmpdir) / "commit.diff")
            payload = {"message": "fix: bug", "bead_id": "sase-1.2"}
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch(
                    "sase.workflows.commit.commit_tracking."
                    "update_agent_artifact_index_for_marker_mutation"
                ) as update_index,
            ):
                write_result_marker(
                    "create_commit",
                    payload,
                    diff_path,
                    "abc123",
                    "proj_feat_1",
                    entry_id="7",
                )

            meta = json.loads(meta_path.read_text())
            assert meta == {
                "name": "agent-alpha",
                "commit_diff_path": diff_path,
                "commit_changespec_name": "proj_feat_1",
            }
            assert "commit_entry_id" not in meta
            assert "commit_result" not in meta
            update_index.assert_called_once_with(tmpdir)

    @pytest.mark.parametrize("existing_diff", [None, "/tmp/primary.diff"])
    def test_external_commit_neither_seeds_nor_overwrites_primary_diff(
        self,
        tmp_path: Path,
        existing_diff: str | None,
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        primary = tmp_path / "sase_7"
        sidecar = primary / ".sase" / "sdd"
        artifacts_dir.mkdir()
        (primary / ".git").mkdir(parents=True)
        (sidecar / ".git").mkdir(parents=True)
        meta = {
            "name": "agent-alpha",
            "workspace_dir": str(primary),
            "commit_changespec_name": "primary_spec",
        }
        if existing_diff is not None:
            meta["commit_diff_path"] = existing_diff
        meta_path = artifacts_dir / "agent_meta.json"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        with (
            patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": str(artifacts_dir)}),
            patch("os.getcwd", return_value=str(sidecar)),
            patch(
                "sase.workflows.commit.commit_tracking."
                "update_agent_artifact_index_for_marker_mutation"
            ) as update_index,
        ):
            write_result_marker(
                "create_commit",
                {"message": "docs: sidecar"},
                "/tmp/sidecar.diff",
                "def456",
                "sidecar_spec",
            )

        persisted = json.loads(meta_path.read_text(encoding="utf-8"))
        assert persisted.get("commit_diff_path") == existing_diff
        assert persisted["commit_changespec_name"] == "primary_spec"
        results = json.loads(
            (artifacts_dir / "commit_results.json").read_text(encoding="utf-8")
        )
        assert results[0]["cwd"] == str(sidecar)
        assert results[0]["diff_path"] == "/tmp/sidecar.diff"
        update_index.assert_not_called()

    def test_primary_subdirectory_commit_updates_primary_diff(
        self,
        tmp_path: Path,
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        primary = tmp_path / "sase_7"
        source_dir = primary / "src"
        artifacts_dir.mkdir()
        (primary / ".git").mkdir(parents=True)
        source_dir.mkdir()
        meta_path = artifacts_dir / "agent_meta.json"
        meta_path.write_text(
            json.dumps({"workspace_dir": str(primary)}),
            encoding="utf-8",
        )

        with (
            patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": str(artifacts_dir)}),
            patch("os.getcwd", return_value=str(source_dir)),
        ):
            write_result_marker(
                "create_commit",
                {"message": "fix: primary"},
                "/tmp/primary.diff",
                "abc123",
                "primary_spec",
            )

        persisted = json.loads(meta_path.read_text(encoding="utf-8"))
        assert persisted["commit_diff_path"] == "/tmp/primary.diff"
        assert persisted["commit_changespec_name"] == "primary_spec"

    def test_sidecar_commit_records_store_repo_name(
        self,
        tmp_path: Path,
    ) -> None:
        from sase.sdd.store import write_sdd_store_record

        artifacts_dir = tmp_path / "artifacts"
        primary = tmp_path / "sase_7"
        sidecar = primary / "sase" / "repos" / "plans"
        artifacts_dir.mkdir()
        sidecar.mkdir(parents=True)
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps({"workspace_dir": str(primary)}),
            encoding="utf-8",
        )
        write_sdd_store_record(
            primary,
            {
                "schema_version": 2,
                "storage": "sidecar_repos",
                "provider": "github",
                "sidecars": {
                    "plans": {
                        "repo": "sase-org/sase--plans",
                        "remote_url": "git@example.com:sase-org/sase--plans.git",
                    },
                    "research": {
                        "repo": "sase-org/sase--research",
                        "remote_url": "git@example.com:sase-org/sase--research.git",
                    },
                },
            },
        )

        with (
            patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": str(artifacts_dir)}),
            patch("os.getcwd", return_value=str(sidecar)),
        ):
            write_result_marker(
                "create_commit",
                {"message": "docs: update plan"},
                "/tmp/plans.diff",
                "abc123",
                None,
            )

        marker = json.loads(
            (artifacts_dir / "commit_result.json").read_text(encoding="utf-8")
        )
        assert marker["repo_name"] == "sase-org/sase--plans"

    @pytest.mark.parametrize(
        ("clone_parts", "repo_name"),
        [
            (("gh", "acme", "widget"), "gh:acme/widget"),
            (("projects", "dotdrop"), "dotdrop"),
        ],
    )
    def test_external_commit_records_canonical_repo_and_own_diff(
        self,
        tmp_path: Path,
        clone_parts: tuple[str, ...],
        repo_name: str,
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        primary = tmp_path / "sase_7"
        external = primary.joinpath("sase", "repos", "external", *clone_parts)
        source_dir = external / "src"
        artifacts_dir.mkdir()
        (primary / ".git").mkdir(parents=True)
        (external / ".git").mkdir(parents=True)
        source_dir.mkdir()
        meta_path = artifacts_dir / "agent_meta.json"
        meta_path.write_text(
            json.dumps(
                {
                    "workspace_dir": str(primary),
                    "commit_diff_path": "/tmp/primary.diff",
                    "commit_changespec_name": "primary_spec",
                }
            ),
            encoding="utf-8",
        )
        diff_path = write_commit_diff_artifact(
            "diff --git a/src/demo.py b/src/demo.py\n",
            artifacts_dir=artifacts_dir,
        )
        assert diff_path is not None

        with (
            patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": str(artifacts_dir)}),
            patch("os.getcwd", return_value=str(source_dir)),
        ):
            write_result_marker(
                "create_commit",
                {"message": "fix: external"},
                diff_path,
                "def456",
                "external_spec",
            )

        results = json.loads(
            (artifacts_dir / "commit_results.json").read_text(encoding="utf-8")
        )
        assert results[0]["repo_name"] == repo_name
        assert results[0]["commit_diff_path"] == diff_path
        assert Path(diff_path).read_text(encoding="utf-8").startswith("diff --git")
        persisted = json.loads(meta_path.read_text(encoding="utf-8"))
        assert persisted["commit_diff_path"] == "/tmp/primary.diff"
        assert persisted["commit_changespec_name"] == "primary_spec"

    def test_persists_changespec_without_diff_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta_path = Path(tmpdir) / "agent_meta.json"
            meta_path.write_text(json.dumps({"name": "agent-alpha"}))
            payload = {"message": "fix: bug"}
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch(
                    "sase.workflows.commit.commit_tracking."
                    "update_agent_artifact_index_for_marker_mutation"
                ) as update_index,
            ):
                write_result_marker(
                    "create_commit",
                    payload,
                    None,
                    "abc123",
                    "proj_feat_1",
                    entry_id="7",
                )

            meta = json.loads(meta_path.read_text())
            assert meta == {
                "name": "agent-alpha",
                "commit_changespec_name": "proj_feat_1",
            }
            update_index.assert_called_once_with(tmpdir)

    def test_primary_commit_metadata_skips_noop_rewrite(self, tmp_path: Path) -> None:
        artifacts_dir = tmp_path / "artifacts"
        primary = tmp_path / "sase_7"
        artifacts_dir.mkdir()
        (primary / ".git").mkdir(parents=True)
        meta = {
            "workspace_dir": str(primary),
            "commit_diff_path": "/tmp/primary.diff",
            "commit_changespec_name": "primary_spec",
        }
        meta_path = artifacts_dir / "agent_meta.json"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        with (
            patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": str(artifacts_dir)}),
            patch("os.getcwd", return_value=str(primary)),
            patch(
                "sase.workflows.commit.commit_tracking."
                "update_agent_artifact_index_for_marker_mutation"
            ) as update_index,
        ):
            write_result_marker(
                "create_commit",
                {"message": "fix: primary"},
                "/tmp/primary.diff",
                "abc123",
                "primary_spec",
            )

        assert json.loads(meta_path.read_text(encoding="utf-8")) == meta
        update_index.assert_not_called()

    def test_does_not_update_agent_meta_without_commit_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta_path = Path(tmpdir) / "agent_meta.json"
            meta_path.write_text(json.dumps({"name": "agent-alpha"}))
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch(
                    "sase.workflows.commit.commit_tracking."
                    "update_agent_artifact_index_for_marker_mutation"
                ) as update_index,
            ):
                write_result_marker(
                    "create_commit",
                    {"message": "fix: bug"},
                    None,
                    "abc123",
                    None,
                )

            assert json.loads(meta_path.read_text()) == {"name": "agent-alpha"}
            update_index.assert_not_called()

    def test_skips_when_no_artifacts_dir(self) -> None:
        payload = {"message": "test"}
        with patch.dict("os.environ", {}, clear=True):
            # Should not raise
            write_result_marker("create_commit", payload, None, "abc", None)

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


class TestBuildPrBody:
    """Verify build_pr_body reads agent_meta.json and sets _pr_body."""

    def test_sets_pr_body_with_full_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta = {"name": "my-agent", "model": "opus-4", "llm_provider": "anthropic"}
            (Path(tmpdir) / "agent_meta.json").write_text(json.dumps(meta))

            payload = {"message": "add feature"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                build_pr_body(payload)

            assert payload["_pr_body"] == (
                "add feature\n\n---\n"
                "**Model:** `anthropic/opus-4`\n"
                "**Agent:** `my-agent`"
            )

    def test_model_only_when_name_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta = {"model": "opus-4", "llm_provider": "anthropic"}
            (Path(tmpdir) / "agent_meta.json").write_text(json.dumps(meta))

            payload = {"message": "msg"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                build_pr_body(payload)

            assert payload["_pr_body"] == ("msg\n\n---\n**Model:** `anthropic/opus-4`")

    def test_name_only_when_provider_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta = {"name": "my-agent", "model": "opus-4"}
            (Path(tmpdir) / "agent_meta.json").write_text(json.dumps(meta))

            payload = {"message": "msg"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                build_pr_body(payload)

            assert payload["_pr_body"] == "msg\n\n---\n**Agent:** `my-agent`"

    def test_no_pr_body_when_meta_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "agent_meta.json").write_text("{}")

            payload = {"message": "msg"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                build_pr_body(payload)

            assert "_pr_body" not in payload

    def test_no_pr_body_when_no_artifacts_dir(self) -> None:
        payload = {"message": "msg"}
        with patch.dict("os.environ", {}, clear=True):
            build_pr_body(payload)

        assert "_pr_body" not in payload

    def test_no_pr_body_when_meta_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "msg"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                build_pr_body(payload)

            assert "_pr_body" not in payload


class TestAppendCommitsEntry:
    """Verify append_commits_entry calls entry functions directly."""

    _COMMIT_ENTRY_TARGET = (
        "sase.workflows.commit_utils.entries.add_commit_entry_with_id"
    )
    _PROPOSAL_ENTRY_TARGET = (
        "sase.workflows.commit_utils.entries.add_proposed_commit_entry"
    )

    def test_returns_entry_id_on_success(self, tmp_path: Path) -> None:
        project_file = tmp_path / "proj.sase"
        project_file.write_text("NAME: branch\nCOMMITS:\nSTATUS: Pending\n")
        with patch(
            self._COMMIT_ENTRY_TARGET,
            return_value=(True, "99"),
        ) as mock_add:
            result = append_commits_entry(
                str(project_file), "branch", {"message": "test"}, "create_commit", None
            )
            assert result == "99"
            mock_add.assert_called_once()

    def test_returns_none_on_failure(self) -> None:
        assert (
            append_commits_entry(None, None, {"message": "test"}, "create_commit", None)
            is None
        )

    def test_uses_proposal_mode_for_create_proposal(self, tmp_path: Path) -> None:
        project_file = tmp_path / "proj.sase"
        project_file.write_text("NAME: branch\nCOMMITS:\nSTATUS: Pending\n")
        with patch(
            self._PROPOSAL_ENTRY_TARGET,
            return_value=(True, "0a"),
        ) as mock_add:
            result = append_commits_entry(
                str(project_file),
                "branch",
                {"message": "test"},
                "create_proposal",
                None,
            )
            assert result == "0a"
            mock_add.assert_called_once()
