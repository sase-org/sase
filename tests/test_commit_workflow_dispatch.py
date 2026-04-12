"""Tests for CommitWorkflow dispatch routing, validation, and properties."""

from unittest.mock import ANY, MagicMock, patch

import pytest

from sase.workflows.commit.workflow import CommitWorkflow

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"
_CONFIG_TARGET = "sase.workflows.commit.precommit_hooks.load_merged_config"
_PROJECT_NAME_TARGET = "sase.workflows.utils.get_project_from_workspace"


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
    provider.create_pull_request.return_value = (
        True,
        "https://github.com/org/repo/pull/1",
    )
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
                mock_prov.create_pull_request.return_value = (
                    True,
                    "https://github.com/org/repo/pull/1",
                )
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
            patch("sase.workflows.commit.workflow.handle_beads") as mock_beads,
            patch("sase.workflows.commit.workflow.handle_sase_plan") as mock_plan,
            patch(
                "sase.workflows.commit.workflow.append_commits_entry", return_value=None
            ),
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
            patch("sase.workflows.commit.workflow.handle_beads") as mock_beads,
            patch("sase.workflows.commit.workflow.handle_sase_plan") as mock_plan,
            patch(
                "sase.workflows.commit.workflow.append_commits_entry", return_value=None
            ),
        ):
            assert wf.run() is True
            mock_beads.assert_called_once()
            mock_plan.assert_called_once()


class TestCreatePullRequestValidation:
    """Verify create_pull_request dispatch and ChangeSpec creation."""

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_succeeds_with_none_result_bare_git(
        self,
        mock_get: MagicMock,
        mock_proj_name: MagicMock,
    ) -> None:
        """create_pull_request succeeds when dispatch returns (True, None) (bare_git path)."""
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider
        payload = {"name": "feat-branch", "message": "add feature"}
        wf = CommitWorkflow(payload, "create_pull_request")
        assert wf.run() is True

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_succeeds_when_dispatch_returns_pr_url(
        self,
        mock_get: MagicMock,
        mock_proj_name: MagicMock,
    ) -> None:
        """create_pull_request succeeds when dispatch returns a PR URL."""
        provider = MagicMock()
        provider.create_pull_request.return_value = (
            True,
            "https://github.com/org/repo/pull/1",
        )
        mock_get.return_value = provider
        payload = {"name": "feat-branch", "message": "add feature"}
        wf = CommitWorkflow(payload, "create_pull_request")
        assert wf.run() is True
