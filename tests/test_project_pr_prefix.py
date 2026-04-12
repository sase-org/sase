"""Tests for use_project_pr_prefix config, stripping, and workflow integration."""

from unittest.mock import MagicMock, patch

import pytest

from sase.vcs_provider.config import (
    get_use_project_pr_prefix,
    strip_project_pr_prefix,
)
from sase.workflows.commit.workflow import CommitWorkflow

_VCS_CONFIG_TARGET = "sase.vcs_provider.config.get_vcs_provider_config"
_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"
_CONFIG_TARGET = "sase.workflows.commit.precommit_hooks.load_merged_config"
_PROJECT_NAME_TARGET = "sase.workflows.utils.get_project_from_workspace"


@pytest.fixture(autouse=True)
def _no_precommit():  # type: ignore[no-untyped-def]
    with (
        patch(_CONFIG_TARGET, return_value={"precommit_command": ""}),
        patch.dict("os.environ", {"SASE_PLAN": ""}, clear=False),
    ):
        yield


# === get_use_project_pr_prefix ===


class TestGetUseProjectPrPrefix:
    @patch(_VCS_CONFIG_TARGET, return_value={"use_project_pr_prefix": True})
    def test_enabled(self, _mock: MagicMock) -> None:
        assert get_use_project_pr_prefix() is True

    @patch(_VCS_CONFIG_TARGET, return_value={"use_project_pr_prefix": False})
    def test_disabled(self, _mock: MagicMock) -> None:
        assert get_use_project_pr_prefix() is False

    @patch(_VCS_CONFIG_TARGET, return_value={})
    def test_missing_defaults_false(self, _mock: MagicMock) -> None:
        assert get_use_project_pr_prefix() is False


# === strip_project_pr_prefix ===


class TestStripProjectPrPrefix:
    @patch(_VCS_CONFIG_TARGET, return_value={"use_project_pr_prefix": True})
    def test_strips_prefix(self, _mock: MagicMock) -> None:
        assert strip_project_pr_prefix("[myproj] Fix bug") == "Fix bug"

    @patch(_VCS_CONFIG_TARGET, return_value={"use_project_pr_prefix": True})
    def test_strips_prefix_multiline(self, _mock: MagicMock) -> None:
        desc = "[myproj] Fix bug\n\nMore details here."
        assert strip_project_pr_prefix(desc) == "Fix bug\n\nMore details here."

    @patch(_VCS_CONFIG_TARGET, return_value={"use_project_pr_prefix": False})
    def test_noop_when_disabled(self, _mock: MagicMock) -> None:
        desc = "[myproj] Fix bug"
        assert strip_project_pr_prefix(desc) == desc

    @patch(_VCS_CONFIG_TARGET, return_value={"use_project_pr_prefix": True})
    def test_no_prefix_present(self, _mock: MagicMock) -> None:
        assert strip_project_pr_prefix("Fix bug") == "Fix bug"

    @patch(_VCS_CONFIG_TARGET, return_value={"use_project_pr_prefix": True})
    def test_empty_string(self, _mock: MagicMock) -> None:
        assert strip_project_pr_prefix("") == ""


# === _apply_project_pr_prefix workflow method ===


class TestApplyProjectPrPrefix:
    @patch(_PROJECT_NAME_TARGET, return_value="myproj")
    @patch(_PROVIDER_TARGET)
    def test_sets_prefix_when_enabled(
        self, mock_get: MagicMock, _mock_proj: MagicMock
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Add feature"}
        wf = CommitWorkflow(payload, "create_pull_request")

        with patch(
            "sase.vcs_provider.config.get_use_project_pr_prefix", return_value=True
        ):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        assert sent.get("_pr_title_prefix") == "[myproj] "

    @patch(_PROJECT_NAME_TARGET, return_value="myproj")
    @patch(_PROVIDER_TARGET)
    def test_no_prefix_when_disabled(
        self, mock_get: MagicMock, _mock_proj: MagicMock
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Add feature"}
        wf = CommitWorkflow(payload, "create_pull_request")

        with patch(
            "sase.vcs_provider.config.get_use_project_pr_prefix", return_value=False
        ):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        assert "_pr_title_prefix" not in sent

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_no_prefix_when_no_project(
        self, mock_get: MagicMock, _mock_proj: MagicMock
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Add feature"}
        wf = CommitWorkflow(payload, "create_pull_request")

        with patch(
            "sase.vcs_provider.config.get_use_project_pr_prefix", return_value=True
        ):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        assert "_pr_title_prefix" not in sent

    @patch(_PROJECT_NAME_TARGET, return_value="myproj")
    @patch(_PROVIDER_TARGET)
    def test_message_stays_clean(
        self, mock_get: MagicMock, _mock_proj: MagicMock
    ) -> None:
        """The payload message must NOT contain the prefix."""
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Add feature"}
        wf = CommitWorkflow(payload, "create_pull_request")

        with patch(
            "sase.vcs_provider.config.get_use_project_pr_prefix", return_value=True
        ):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        assert not sent["message"].startswith("[myproj]")

    @patch(_PROJECT_NAME_TARGET, return_value="myproj")
    @patch(_PROVIDER_TARGET)
    def test_strips_existing_prefix_from_message(
        self, mock_get: MagicMock, _mock_proj: MagicMock
    ) -> None:
        """When the agent already included a [project] prefix in the message,
        it must be stripped so the PR title doesn't get a duplicate prefix."""
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {
            "name": "feat-x",
            "message": "[myproj] Implement feature",
        }
        wf = CommitWorkflow(payload, "create_pull_request")

        with patch(
            "sase.vcs_provider.config.get_use_project_pr_prefix", return_value=True
        ):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        assert sent["_pr_title_prefix"] == "[myproj] "
        assert sent["message"].startswith("Implement feature")
        assert "[myproj]" not in sent["message"]
