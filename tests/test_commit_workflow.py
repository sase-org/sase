"""Tests for the CommitWorkflow dispatch class."""

from unittest.mock import ANY, MagicMock, patch

import pytest

from sase.workflows.commit.workflow import CommitWorkflow

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"
_CHANGESPEC_TARGET = "sase.workspace_provider.changespec.create_changespec_for_workflow"
_PROJECT_NAME_TARGET = "sase.workflows.utils.get_project_from_workspace"
_PROJECT_FILE_TARGET = "sase.workflows.utils.get_project_file_path"


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
            branch_name="feat-x",
            prompt="",
            response="",
            workflow_name="sase_commit",
            cl_url="https://github.com/org/repo/pull/1",
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

    @patch(_PROVIDER_TARGET)
    def test_no_changespec_for_create_commit(
        self, mock_get: MagicMock, mock_provider: MagicMock
    ) -> None:
        """ChangeSpec is only created for create_pull_request, not create_commit."""
        mock_get.return_value = mock_provider
        wf = CommitWorkflow({"message": "test", "files": []}, "create_commit")

        with patch(_PROJECT_NAME_TARGET) as mock_proj:
            wf.run()
            mock_proj.assert_not_called()


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


class TestCommitWorkflowProperties:
    """Verify workflow metadata."""

    def test_name(self) -> None:
        wf = CommitWorkflow({}, "create_commit")
        assert wf.name == "commit"

    def test_description(self) -> None:
        wf = CommitWorkflow({}, "create_commit")
        assert "VCS" in wf.description
