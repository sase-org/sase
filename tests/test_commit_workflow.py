"""Tests for the CommitWorkflow dispatch class."""

from unittest.mock import ANY, MagicMock, patch

import pytest

from sase.workflows.commit.workflow import CommitWorkflow


@pytest.fixture
def mock_provider() -> MagicMock:
    """Create a mock VCS provider with dispatch methods."""
    provider = MagicMock()
    provider.create_commit.return_value = (True, None)
    provider.create_proposal.return_value = (True, None)
    provider.create_pull_request.return_value = (True, None)
    return provider


_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"


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

    @patch(_PROVIDER_TARGET)
    def test_dispatches_create_pull_request(
        self, mock_get: MagicMock, mock_provider: MagicMock
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


class TestCommitWorkflowProperties:
    """Verify workflow metadata."""

    def test_name(self) -> None:
        wf = CommitWorkflow({}, "create_commit")
        assert wf.name == "commit"

    def test_description(self) -> None:
        wf = CommitWorkflow({}, "create_commit")
        assert "VCS" in wf.description
