"""Tests for CommitWorkflow result markers, PR body, commit entries, and plan handling."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.workflows.commit.workflow import CommitWorkflow

_CONFIG_TARGET = "sase.workflows.commit.workflow.load_merged_config"
_SDD_CONFIG_TARGET = "sase.sdd.beads.get_sdd_config"


@pytest.fixture(autouse=True)
def _no_precommit():  # type: ignore[no-untyped-def]
    """Prevent precommit commands and SASE_PLAN from running in tests."""
    with (
        patch(_CONFIG_TARGET, return_value={"precommit_command": ""}),
        patch.dict("os.environ", {"SASE_PLAN": ""}, clear=False),
    ):
        yield


class TestWriteResultMarker:
    """Verify _write_result_marker writes correct marker file."""

    def test_writes_marker_with_all_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "fix: bug", "name": "feat-x"}
            wf = CommitWorkflow(payload, "create_commit")
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                wf._write_result_marker("abc123", "proj_feat_1")

            marker_path = Path(tmpdir) / "commit_result.json"
            assert marker_path.exists()
            data = json.loads(marker_path.read_text())
            assert data == {
                "method": "create_commit",
                "result": "abc123",
                "message": "fix: bug",
                "name": "feat-x",
                "bead_id": "",
                "changespec_name": "proj_feat_1",
                "entry_id": None,
                "diff_path": None,
            }

    def test_writes_none_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "test"}
            wf = CommitWorkflow(payload, "create_proposal")
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                wf._write_result_marker(None, None)

            data = json.loads((Path(tmpdir) / "commit_result.json").read_text())
            assert data["result"] is None
            assert data["changespec_name"] is None
            assert data["entry_id"] is None

    def test_writes_marker_with_entry_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "fix: bug"}
            wf = CommitWorkflow(payload, "create_commit")
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                wf._write_result_marker("abc123", None, entry_id="entry_42")

            data = json.loads((Path(tmpdir) / "commit_result.json").read_text())
            assert data["entry_id"] == "entry_42"

    def test_skips_when_no_artifacts_dir(self) -> None:
        payload = {"message": "test"}
        wf = CommitWorkflow(payload, "create_commit")
        with patch.dict("os.environ", {}, clear=True):
            # Should not raise
            wf._write_result_marker("abc", None)


class TestBuildPrBody:
    """Verify _build_pr_body reads agent_meta.json and sets _pr_body."""

    def test_sets_pr_body_with_full_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta = {"name": "my-agent", "model": "opus-4", "llm_provider": "anthropic"}
            (Path(tmpdir) / "agent_meta.json").write_text(json.dumps(meta))

            payload = {"message": "add feature"}
            wf = CommitWorkflow(payload, "create_pull_request")
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                wf._build_pr_body()

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
            wf = CommitWorkflow(payload, "create_pull_request")
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                wf._build_pr_body()

            assert payload["_pr_body"] == ("msg\n\n---\n**Model:** `anthropic/opus-4`")

    def test_name_only_when_provider_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta = {"name": "my-agent", "model": "opus-4"}
            (Path(tmpdir) / "agent_meta.json").write_text(json.dumps(meta))

            payload = {"message": "msg"}
            wf = CommitWorkflow(payload, "create_pull_request")
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                wf._build_pr_body()

            assert payload["_pr_body"] == "msg\n\n---\n**Agent:** `my-agent`"

    def test_no_pr_body_when_meta_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "agent_meta.json").write_text("{}")

            payload = {"message": "msg"}
            wf = CommitWorkflow(payload, "create_pull_request")
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                wf._build_pr_body()

            assert "_pr_body" not in payload

    def test_no_pr_body_when_no_artifacts_dir(self) -> None:
        payload = {"message": "msg"}
        wf = CommitWorkflow(payload, "create_pull_request")
        with patch.dict("os.environ", {}, clear=True):
            wf._build_pr_body()

        assert "_pr_body" not in payload

    def test_no_pr_body_when_meta_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "msg"}
            wf = CommitWorkflow(payload, "create_pull_request")
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                wf._build_pr_body()

            assert "_pr_body" not in payload


class TestAppendCommitsEntry:
    """Verify _append_commits_entry calls entry functions directly."""

    _COMMIT_ENTRY_TARGET = (
        "sase.workflows.commit_utils.entries.add_commit_entry_with_id"
    )
    _PROPOSAL_ENTRY_TARGET = (
        "sase.workflows.commit_utils.entries.add_proposed_commit_entry"
    )

    def test_returns_entry_id_on_success(self, tmp_path: Path) -> None:
        project_file = tmp_path / "proj.gp"
        project_file.write_text("NAME: branch\nCOMMITS:\nSTATUS: Pending\n")
        wf = CommitWorkflow({"message": "test"}, "create_commit")
        wf._cl_name = "branch"
        wf._project_file = str(project_file)
        with patch(
            self._COMMIT_ENTRY_TARGET,
            return_value=(True, "99"),
        ) as mock_add:
            result = wf._append_commits_entry()
            assert result == "99"
            mock_add.assert_called_once()

    def test_returns_none_on_failure(self) -> None:
        wf = CommitWorkflow({"message": "test"}, "create_commit")
        wf._cl_name = None
        wf._project_file = None
        assert wf._append_commits_entry() is None

    def test_uses_proposal_mode_for_create_proposal(self, tmp_path: Path) -> None:
        project_file = tmp_path / "proj.gp"
        project_file.write_text("NAME: branch\nCOMMITS:\nSTATUS: Pending\n")
        wf = CommitWorkflow({"message": "test"}, "create_proposal")
        wf._cl_name = "branch"
        wf._project_file = str(project_file)
        with patch(
            self._PROPOSAL_ENTRY_TARGET,
            return_value=(True, "0a"),
        ) as mock_add:
            result = wf._append_commits_entry()
            assert result == "0a"
            mock_add.assert_called_once()


class TestHandleSasePlan:
    """Verify _handle_sase_plan gates copy/frontmatter/staging on version_controlled."""

    def test_vc_true_copies_plan_into_repo(self, tmp_path: Path) -> None:
        """version_controlled=True: plan is copied into plans/, _plan_path set."""
        plan_file = tmp_path / "my_plan.md"
        plan_file.write_text("# Plan\nstatus: wip\n")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        payload: dict = {"message": "fix: bug"}
        wf = CommitWorkflow(payload, "create_commit")

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patch(_SDD_CONFIG_TARGET, return_value=True),
            patch.object(CommitWorkflow, "_get_repo_root", return_value=str(repo_dir)),
        ):
            wf._handle_sase_plan(str(repo_dir))

        assert "_plan_path" in payload
        dest = repo_dir / "plans" / "my_plan.md"
        assert dest.exists()
        assert "PLAN=plans/my_plan.md" in payload["message"]

    def test_vc_false_does_not_copy_plan(self, tmp_path: Path) -> None:
        """version_controlled=False: plan NOT copied, no _plan_path, PLAN= still appended."""
        plan_file = tmp_path / "my_plan.md"
        plan_file.write_text("# Plan\nstatus: wip\n")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        payload: dict = {"message": "fix: bug"}
        wf = CommitWorkflow(payload, "create_commit")

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patch(_SDD_CONFIG_TARGET, return_value=False),
            patch.object(CommitWorkflow, "_get_repo_root", return_value=str(repo_dir)),
        ):
            wf._handle_sase_plan(str(repo_dir))

        assert "_plan_path" not in payload
        assert not (repo_dir / "plans").exists()
        assert "PLAN=" in payload["message"]

    def test_archive_fallback_vc_true_copies(self, tmp_path: Path) -> None:
        """Archive fallback + version_controlled=True: copies into repo."""
        archive_dir = tmp_path / ".sase" / "plans"
        archive_dir.mkdir(parents=True)
        archive_plan = archive_dir / "my_plan.md"
        archive_plan.write_text("# Plan\nstatus: wip\n")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        payload: dict = {"message": "fix: bug"}
        wf = CommitWorkflow(payload, "create_commit")

        with (
            patch.dict(
                "os.environ",
                {"SASE_PLAN": "/nonexistent/my_plan.md"},
            ),
            patch(_SDD_CONFIG_TARGET, return_value=True),
            patch.object(CommitWorkflow, "_get_repo_root", return_value=str(repo_dir)),
            patch("os.path.expanduser", return_value=str(tmp_path)),
        ):
            wf._handle_sase_plan(str(repo_dir))

        assert "_plan_path" in payload
        assert (repo_dir / "plans" / "my_plan.md").exists()

    def test_archive_fallback_vc_false_no_copy(self, tmp_path: Path) -> None:
        """Archive fallback + version_controlled=False: does NOT copy into repo."""
        archive_dir = tmp_path / ".sase" / "plans"
        archive_dir.mkdir(parents=True)
        archive_plan = archive_dir / "my_plan.md"
        archive_plan.write_text("# Plan\nstatus: wip\n")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        payload: dict = {"message": "fix: bug"}
        wf = CommitWorkflow(payload, "create_commit")

        with (
            patch.dict(
                "os.environ",
                {"SASE_PLAN": "/nonexistent/my_plan.md"},
            ),
            patch(_SDD_CONFIG_TARGET, return_value=False),
            patch.object(CommitWorkflow, "_get_repo_root", return_value=str(repo_dir)),
            patch("os.path.expanduser", return_value=str(tmp_path)),
        ):
            wf._handle_sase_plan(str(repo_dir))

        assert "_plan_path" not in payload
        assert not (repo_dir / "plans").exists()
        assert "PLAN=" in payload["message"]
