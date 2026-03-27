"""Tests for the CommitWorkflow dispatch class."""

import json
import tempfile
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

from sase.workflows.commit.workflow import CommitWorkflow

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"
_CONFIG_TARGET = "sase.workflows.commit.workflow.load_merged_config"
_SDD_CONFIG_TARGET = "sase.sdd.beads.get_sdd_config"
_CHANGESPEC_TARGET = "sase.workspace_provider.changespec.create_changespec_for_workflow"
_PROJECT_NAME_TARGET = "sase.workflows.utils.get_project_from_workspace"
_PROJECT_FILE_TARGET = "sase.workflows.utils.get_project_file_path"
_SUFFIXED_CL_TARGET = (
    "sase.workflows.commit.changespec_operations.compute_suffixed_cl_name"
)


@pytest.fixture(autouse=True)
def _no_precommit():  # type: ignore[no-untyped-def]
    """Prevent precommit commands and SASE_PLAN from running in tests."""
    with (
        patch(_CONFIG_TARGET, return_value={"precommit_command": ""}),
        patch.dict("os.environ", {"SASE_PLAN": ""}, clear=False),
    ):
        yield


@pytest.fixture
def mock_provider() -> MagicMock:
    """Create a mock VCS provider with dispatch methods."""
    provider = MagicMock()
    provider.create_commit.return_value = (True, None)
    provider.create_proposal.return_value = (True, None)
    provider.create_pull_request.return_value = (True, None)
    return provider


class TestCommitWorkflowDispatch:
    """Verify that CommitWorkflow routes to the correct provider method."""

    @patch(_PROVIDER_TARGET)
    def test_dispatches_create_commit(
        self, mock_get: MagicMock, mock_provider: MagicMock
    ) -> None:
        mock_get.return_value = mock_provider
        payload = {"message": "fix: bug", "files": ["a.py"]}
        wf = CommitWorkflow(payload, "create_commit")

        assert wf.run() is True
        mock_provider.create_commit.assert_called_once_with(payload, ANY)

    @patch(_PROVIDER_TARGET)
    def test_dispatches_create_proposal(
        self, mock_get: MagicMock, mock_provider: MagicMock
    ) -> None:
        mock_get.return_value = mock_provider
        payload = {"message": "propose: new feature"}
        wf = CommitWorkflow(payload, "create_proposal")

        assert wf.run() is True
        mock_provider.create_proposal.assert_called_once_with(payload, ANY)

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_dispatches_create_pull_request(
        self,
        mock_get: MagicMock,
        mock_proj_name: MagicMock,
        mock_provider: MagicMock,
    ) -> None:
        mock_get.return_value = mock_provider
        payload = {"name": "feat-branch", "message": "add feature", "files": []}
        wf = CommitWorkflow(payload, "create_pull_request")

        assert wf.run() is True
        mock_provider.create_pull_request.assert_called_once_with(payload, ANY)

    def test_invalid_method_returns_false(self) -> None:
        wf = CommitWorkflow({"message": "test"}, "invalid_method")
        assert wf.run() is False

    @patch(_PROVIDER_TARGET)
    def test_provider_failure_returns_false(
        self, mock_get: MagicMock, mock_provider: MagicMock
    ) -> None:
        mock_provider.create_commit.return_value = (False, "git add failed")
        mock_get.return_value = mock_provider
        wf = CommitWorkflow({"message": "test"}, "create_commit")

        assert wf.run() is False


class TestCommitWorkflowChangeSpec:
    """Verify ChangeSpec creation after create_pull_request."""

    @patch(_SUFFIXED_CL_TARGET, return_value="feat-x_1")
    @patch(_CHANGESPEC_TARGET, return_value="proj_feat_1")
    @patch(_PROJECT_FILE_TARGET, return_value="/fake/proj.gp")
    @patch(_PROJECT_NAME_TARGET, return_value="proj")
    @patch(_PROVIDER_TARGET)
    def test_creates_changespec_on_pr_success(
        self,
        mock_get: MagicMock,
        mock_proj_name: MagicMock,
        mock_proj_file: MagicMock,
        mock_cs: MagicMock,
        mock_suffixed: MagicMock,
        mock_provider: MagicMock,
    ) -> None:
        mock_provider.create_pull_request.return_value = (
            True,
            "https://github.com/org/repo/pull/1",
        )
        mock_get.return_value = mock_provider
        payload = {"name": "feat-x", "message": "add feature", "files": []}
        wf = CommitWorkflow(payload, "create_pull_request")

        assert wf.run() is True
        mock_cs.assert_called_once_with(
            project_name="proj",
            project_file="/fake/proj.gp",
            checkout_target="HEAD~1",
            branch_name="feat-x_1",
            prompt="",
            response="",
            workflow_name="sase_commit",
            cl_url="https://github.com/org/repo/pull/1",
            cl_name="feat-x",
            commit_description="add feature",
            parent=None,
        )

    @patch(_CHANGESPEC_TARGET, return_value="proj_feat_1")
    @patch(_PROJECT_FILE_TARGET, return_value="/fake/proj.gp")
    @patch(_PROJECT_NAME_TARGET, return_value="proj")
    @patch(_PROVIDER_TARGET)
    def test_uses_checkout_target_from_payload(
        self,
        mock_get: MagicMock,
        mock_proj_name: MagicMock,
        mock_proj_file: MagicMock,
        mock_cs: MagicMock,
        mock_provider: MagicMock,
    ) -> None:
        mock_provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = mock_provider
        payload = {
            "name": "feat-x",
            "message": "test",
            "files": [],
            "checkout_target": "origin/main",
        }
        wf = CommitWorkflow(payload, "create_pull_request")

        wf.run()
        mock_cs.assert_called_once()
        assert mock_cs.call_args.kwargs["checkout_target"] == "origin/main"

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_skips_changespec_when_no_project(
        self,
        mock_get: MagicMock,
        mock_proj_name: MagicMock,
        mock_provider: MagicMock,
    ) -> None:
        """No crash when project name can't be detected."""
        mock_provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = mock_provider
        wf = CommitWorkflow(
            {"name": "feat-x", "message": "test", "files": []},
            "create_pull_request",
        )

        assert wf.run() is True

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_no_changespec_for_create_commit(
        self, mock_get: MagicMock, mock_proj: MagicMock, mock_provider: MagicMock
    ) -> None:
        """ChangeSpec is only created for create_pull_request, not create_commit."""
        mock_get.return_value = mock_provider
        wf = CommitWorkflow({"message": "test", "files": []}, "create_commit")

        with patch(_CHANGESPEC_TARGET) as mock_cs:
            wf.run()
            mock_cs.assert_not_called()


class TestCommitWorkflowValidation:
    """Verify payload validation."""

    def test_non_dict_payload_returns_false(self) -> None:
        wf = CommitWorkflow("not a dict", "create_commit")  # type: ignore[arg-type]
        assert wf.run() is False

    def test_missing_message_returns_false(self) -> None:
        wf = CommitWorkflow({"files": ["a.py"]}, "create_commit")
        assert wf.run() is False

    def test_missing_message_ok_for_pull_request(self) -> None:
        """create_pull_request doesn't require 'message' at validation time."""
        wf = CommitWorkflow({"name": "feat-x"}, "create_pull_request")
        # Will fail at provider dispatch, but passes validation
        with patch(_PROJECT_NAME_TARGET, return_value=None):
            with patch(_PROVIDER_TARGET) as mock_get:
                mock_prov = MagicMock()
                mock_prov.create_pull_request.return_value = (True, None)
                mock_get.return_value = mock_prov
                assert wf.run() is True


class TestCommitWorkflowChangeSpecErrorHandling:
    """Verify that _create_changespec exceptions don't fail the workflow."""

    @patch(_PROJECT_FILE_TARGET, side_effect=RuntimeError("boom"))
    @patch(_PROJECT_NAME_TARGET, return_value="proj")
    @patch(_PROVIDER_TARGET)
    def test_changespec_exception_does_not_fail_workflow(
        self,
        mock_get: MagicMock,
        mock_proj_name: MagicMock,
        mock_proj_file: MagicMock,
        mock_provider: MagicMock,
    ) -> None:
        """An exception in _create_changespec must not cause run() to fail."""
        mock_provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = mock_provider
        payload = {"name": "feat-x", "message": "add feature", "files": []}
        wf = CommitWorkflow(payload, "create_pull_request")

        assert wf.run() is True

    def test_missing_name_for_pull_request_returns_false(self) -> None:
        """Empty/missing name field fails validation for create_pull_request."""
        wf = CommitWorkflow({"message": "test"}, "create_pull_request")
        assert wf.run() is False

    def test_empty_name_for_pull_request_returns_false(self) -> None:
        """Explicitly empty name field fails validation."""
        wf = CommitWorkflow({"name": "", "message": "test"}, "create_pull_request")
        assert wf.run() is False

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_name_present_for_pull_request_passes_validation(
        self,
        mock_get: MagicMock,
        mock_proj_name: MagicMock,
        mock_provider: MagicMock,
    ) -> None:
        """Valid payload with name passes validation."""
        mock_provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = mock_provider
        payload = {"name": "feat-branch", "message": "test"}
        wf = CommitWorkflow(payload, "create_pull_request")

        assert wf.run() is True


class TestCommitWorkflowProperties:
    """Verify workflow metadata."""

    def test_name(self) -> None:
        wf = CommitWorkflow({}, "create_commit")
        assert wf.name == "commit"

    def test_description(self) -> None:
        wf = CommitWorkflow({}, "create_commit")
        assert "VCS" in wf.description


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


class TestCreateChangespecReturn:
    """Verify _create_changespec returns cs_name."""

    @patch(_CHANGESPEC_TARGET, return_value="proj_feat_1")
    @patch(_PROJECT_FILE_TARGET, return_value="/fake/proj.gp")
    @patch(_PROJECT_NAME_TARGET, return_value="proj")
    def test_returns_cs_name_on_success(
        self,
        mock_proj_name: MagicMock,
        mock_proj_file: MagicMock,
        mock_cs: MagicMock,
    ) -> None:
        payload = {"name": "feat-x", "message": "add feature"}
        wf = CommitWorkflow(payload, "create_pull_request")
        result = wf._create_changespec(cl_url="https://github.com/org/repo/pull/1")
        assert result == "proj_feat_1"

    @patch(_CHANGESPEC_TARGET, return_value=None)
    @patch(_PROJECT_FILE_TARGET, return_value="/fake/proj.gp")
    @patch(_PROJECT_NAME_TARGET, return_value="proj")
    def test_returns_none_when_no_commits(
        self,
        mock_proj_name: MagicMock,
        mock_proj_file: MagicMock,
        mock_cs: MagicMock,
    ) -> None:
        payload = {"name": "feat-x", "message": "test"}
        wf = CommitWorkflow(payload, "create_pull_request")
        result = wf._create_changespec(cl_url=None)
        assert result is None

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    def test_returns_none_when_no_project(self, mock_proj_name: MagicMock) -> None:
        payload = {"name": "feat-x", "message": "test"}
        wf = CommitWorkflow(payload, "create_pull_request")
        result = wf._create_changespec(cl_url=None)
        assert result is None

    @patch(_PROJECT_FILE_TARGET, side_effect=RuntimeError("boom"))
    @patch(_PROJECT_NAME_TARGET, return_value="proj")
    def test_returns_none_on_exception(
        self,
        mock_proj_name: MagicMock,
        mock_proj_file: MagicMock,
    ) -> None:
        payload = {"name": "feat-x", "message": "test"}
        wf = CommitWorkflow(payload, "create_pull_request")
        result = wf._create_changespec(cl_url=None)
        assert result is None


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


class TestGetMetaChangespecName:
    """Verify get_meta_changespec_name with new and legacy variables."""

    def _make_agent(self, step_output: dict | None) -> MagicMock:
        agent = MagicMock()
        agent.step_output = step_output
        return agent

    def test_meta_changespec_direct(self) -> None:
        from sase.ace.tui.actions.agents._notification_actions import (
            get_meta_changespec_name,
        )

        agent = self._make_agent({"meta_changespec": "proj_feat_1"})
        assert get_meta_changespec_name(agent) == "proj_feat_1"

    def test_meta_changespec_strips_whitespace(self) -> None:
        from sase.ace.tui.actions.agents._notification_actions import (
            get_meta_changespec_name,
        )

        agent = self._make_agent({"meta_changespec": "  proj_feat_1  "})
        assert get_meta_changespec_name(agent) == "proj_feat_1"

    def test_legacy_meta_new_cl(self) -> None:
        from sase.ace.tui.actions.agents._notification_actions import (
            get_meta_changespec_name,
        )

        agent = self._make_agent({"meta_new_cl": "proj_feat_1 (http://cl/123)"})
        assert get_meta_changespec_name(agent) == "proj_feat_1"

    def test_legacy_meta_new_pr_with_changespec(self) -> None:
        from sase.ace.tui.actions.agents._notification_actions import (
            get_meta_changespec_name,
        )

        agent = self._make_agent(
            {
                "meta_new_pr": "https://github.com/org/repo/pull/1",
                "meta_changespec": "proj_feat_1",
            }
        )
        # meta_changespec takes priority (new canonical path)
        assert get_meta_changespec_name(agent) == "proj_feat_1"

    def test_returns_none_for_empty_output(self) -> None:
        from sase.ace.tui.actions.agents._notification_actions import (
            get_meta_changespec_name,
        )

        agent = self._make_agent({})
        assert get_meta_changespec_name(agent) is None

    def test_returns_none_for_none_output(self) -> None:
        from sase.ace.tui.actions.agents._notification_actions import (
            get_meta_changespec_name,
        )

        agent = self._make_agent(None)
        assert get_meta_changespec_name(agent) is None


class TestProposalSkipsBeadsAndPlan:
    """Verify that create_proposal skips bead and plan handling."""

    @patch(_PROVIDER_TARGET)
    def test_proposal_skips_handle_beads(
        self, mock_get: MagicMock, mock_provider: MagicMock
    ) -> None:
        mock_get.return_value = mock_provider
        payload = {"message": "propose: change", "bead_id": "b123"}
        wf = CommitWorkflow(payload, "create_proposal")

        with (
            patch.object(wf, "_handle_beads") as mock_beads,
            patch.object(wf, "_handle_sase_plan") as mock_plan,
            patch.object(wf, "_append_commits_entry", return_value=None),
        ):
            assert wf.run() is True
            mock_beads.assert_not_called()
            mock_plan.assert_not_called()

    @patch(_PROVIDER_TARGET)
    def test_commit_still_calls_beads_and_plan(
        self, mock_get: MagicMock, mock_provider: MagicMock
    ) -> None:
        mock_get.return_value = mock_provider
        payload = {"message": "fix: bug"}
        wf = CommitWorkflow(payload, "create_commit")

        with (
            patch.object(wf, "_handle_beads") as mock_beads,
            patch.object(wf, "_handle_sase_plan") as mock_plan,
            patch.object(wf, "_append_commits_entry", return_value=None),
        ):
            assert wf.run() is True
            mock_beads.assert_called_once()
            mock_plan.assert_called_once()


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
