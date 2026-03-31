"""Tests for CommitWorkflow changespec creation and related helpers."""

from unittest.mock import MagicMock, patch

import pytest

from sase.workflows.commit.workflow import CommitWorkflow

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"
_CONFIG_TARGET = "sase.workflows.commit.workflow.load_merged_config"
_DETECT_VCS_TARGET = "sase.workflows.commit.workflow.detect_vcs"
_CHANGESPEC_TARGET = "sase.workspace_provider.changespec.create_changespec_for_workflow"
_PROJECT_NAME_TARGET = "sase.workflows.utils.get_project_from_workspace"
_PROJECT_FILE_TARGET = "sase.workflows.utils.get_project_file_path"
_SUFFIXED_CL_TARGET = (
    "sase.workflows.commit.changespec_operations.compute_suffixed_cl_name"
)


@pytest.fixture(autouse=True)
def _no_precommit():  # type: ignore[no-untyped-def]
    """Prevent precommit commands, SASE_PLAN, and detect_vcs from running in tests."""
    with (
        patch(_CONFIG_TARGET, return_value={"precommit_command": ""}),
        patch.dict("os.environ", {"SASE_PLAN": ""}, clear=False),
        patch(_DETECT_VCS_TARGET, return_value="github"),
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
            bug=None,
            reserved_name="feat-x_1",
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
        mock_provider.create_pull_request.return_value = (
            True,
            "https://github.com/org/repo/pull/2",
        )
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


class TestCommitWorkflowBugId:
    """Verify SASE_BUG_ID env var propagation to ChangeSpec."""

    @patch(_SUFFIXED_CL_TARGET, return_value="feat-x_1")
    @patch(_CHANGESPEC_TARGET, return_value="proj_feat_1")
    @patch(_PROJECT_FILE_TARGET, return_value="/fake/proj.gp")
    @patch(_PROJECT_NAME_TARGET, return_value="proj")
    @patch(_PROVIDER_TARGET)
    def test_bug_id_propagated_to_changespec(
        self,
        mock_get: MagicMock,
        mock_proj_name: MagicMock,
        mock_proj_file: MagicMock,
        mock_cs: MagicMock,
        mock_suffixed: MagicMock,
        mock_provider: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When SASE_BUG_ID is set, bug=http://b/<id> is passed to create_changespec_for_workflow."""
        monkeypatch.setenv("SASE_BUG_ID", "12345")
        mock_provider.create_pull_request.return_value = (
            True,
            "https://github.com/org/repo/pull/1",
        )
        mock_get.return_value = mock_provider
        payload = {"name": "feat-x", "message": "add feature", "files": []}
        wf = CommitWorkflow(payload, "create_pull_request")

        assert wf.run() is True
        mock_cs.assert_called_once()
        assert mock_cs.call_args.kwargs["bug"] == "http://b/12345"

    @patch(_SUFFIXED_CL_TARGET, return_value="feat-x_1")
    @patch(_CHANGESPEC_TARGET, return_value="proj_feat_1")
    @patch(_PROJECT_FILE_TARGET, return_value="/fake/proj.gp")
    @patch(_PROJECT_NAME_TARGET, return_value="proj")
    @patch(_PROVIDER_TARGET)
    def test_bug_id_not_set_passes_none(
        self,
        mock_get: MagicMock,
        mock_proj_name: MagicMock,
        mock_proj_file: MagicMock,
        mock_cs: MagicMock,
        mock_suffixed: MagicMock,
        mock_provider: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When SASE_BUG_ID is not set, bug=None is passed."""
        monkeypatch.delenv("SASE_BUG_ID", raising=False)
        mock_provider.create_pull_request.return_value = (
            True,
            "https://github.com/org/repo/pull/1",
        )
        mock_get.return_value = mock_provider
        payload = {"name": "feat-x", "message": "add feature", "files": []}
        wf = CommitWorkflow(payload, "create_pull_request")

        assert wf.run() is True
        mock_cs.assert_called_once()
        assert mock_cs.call_args.kwargs["bug"] is None

    @patch(_SUFFIXED_CL_TARGET, return_value="feat-x_1")
    @patch(_CHANGESPEC_TARGET, return_value="proj_feat_1")
    @patch(_PROJECT_FILE_TARGET, return_value="/fake/proj.gp")
    @patch(_PROJECT_NAME_TARGET, return_value="proj")
    @patch(_PROVIDER_TARGET)
    def test_bug_id_zero_passes_none(
        self,
        mock_get: MagicMock,
        mock_proj_name: MagicMock,
        mock_proj_file: MagicMock,
        mock_cs: MagicMock,
        mock_suffixed: MagicMock,
        mock_provider: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When SASE_BUG_ID is '0', bug=None is passed (falsy value)."""
        monkeypatch.setenv("SASE_BUG_ID", "0")
        mock_provider.create_pull_request.return_value = (
            True,
            "https://github.com/org/repo/pull/1",
        )
        mock_get.return_value = mock_provider
        payload = {"name": "feat-x", "message": "add feature", "files": []}
        wf = CommitWorkflow(payload, "create_pull_request")

        assert wf.run() is True
        mock_cs.assert_called_once()
        assert mock_cs.call_args.kwargs["bug"] is None


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
        mock_provider.create_pull_request.return_value = (
            True,
            "https://github.com/org/repo/pull/1",
        )
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
        mock_provider.create_pull_request.return_value = (
            True,
            "https://github.com/org/repo/pull/1",
        )
        mock_get.return_value = mock_provider
        payload = {"name": "feat-branch", "message": "test"}
        wf = CommitWorkflow(payload, "create_pull_request")

        assert wf.run() is True


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
