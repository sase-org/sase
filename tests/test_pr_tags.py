"""Tests for pr_tags config reading and commit message appending."""

import os
from unittest.mock import ANY, MagicMock, patch

import pytest

from sase.vcs_provider.config import get_pr_tags
from sase.workflows.commit.workflow import CommitWorkflow

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"
_CONFIG_TARGET = "sase.workflows.commit.workflow.load_merged_config"
_PR_TAGS_TARGET = "sase.vcs_provider.config.get_vcs_provider_config"
_PROJECT_NAME_TARGET = "sase.workflows.utils.get_project_from_workspace"


@pytest.fixture(autouse=True)
def _no_precommit():  # type: ignore[no-untyped-def]
    with (
        patch(_CONFIG_TARGET, return_value={"precommit_command": ""}),
        patch.dict("os.environ", {"SASE_PLAN": ""}, clear=False),
    ):
        yield


class TestGetPrTags:
    """Unit tests for get_pr_tags() config reader."""

    @patch(_PR_TAGS_TARGET, return_value={"pr_tags": {"FOO": "bar", "BAZ": 42}})
    def test_returns_string_dict(self, _mock: MagicMock) -> None:
        result = get_pr_tags()
        assert result == {"FOO": "bar", "BAZ": "42"}

    @patch(_PR_TAGS_TARGET, return_value={})
    def test_empty_when_missing(self, _mock: MagicMock) -> None:
        assert get_pr_tags() == {}

    @patch(_PR_TAGS_TARGET, return_value={"pr_tags": None})
    def test_empty_when_none(self, _mock: MagicMock) -> None:
        assert get_pr_tags() == {}

    @patch(_PR_TAGS_TARGET, return_value={"pr_tags": "not a dict"})
    def test_empty_when_not_dict(self, _mock: MagicMock) -> None:
        assert get_pr_tags() == {}


class TestAppendPrTags:
    """Integration tests for _append_pr_tags in CommitWorkflow."""

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_tags_appended_to_message(
        self,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Add feature"}
        wf = CommitWorkflow(payload, "create_pull_request")

        tags = {"AUTOSUBMIT_BEHAVIOR": "SYNC_SUBMIT", "MARKDOWN": "true"}
        with patch("sase.vcs_provider.config.get_pr_tags", return_value=tags):
            wf.run()

        sent_payload = provider.create_pull_request.call_args[0][0]
        assert "AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT" in sent_payload["message"]
        assert "MARKDOWN=true" in sent_payload["message"]

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_tags_flow_into_pr_body(
        self,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        """Tags appended to message before _build_pr_body should appear in _pr_body."""
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Add feature"}
        wf = CommitWorkflow(payload, "create_pull_request")

        tags = {"R": "startblock"}
        with patch("sase.vcs_provider.config.get_pr_tags", return_value=tags):
            # Set SASE_ARTIFACTS_DIR with agent_meta.json so _build_pr_body produces _pr_body
            import json
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                meta_path = f"{tmpdir}/agent_meta.json"
                with open(meta_path, "w") as f:
                    json.dump({"llm_provider": "test", "model": "m1"}, f)
                with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                    wf.run()

        sent_payload = provider.create_pull_request.call_args[0][0]
        assert "R=startblock" in sent_payload.get("_pr_body", "")

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_bug_tag_from_env(
        self,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Fix bug"}
        wf = CommitWorkflow(payload, "create_pull_request")

        with (
            patch("sase.vcs_provider.config.get_pr_tags", return_value={}),
            patch.dict("os.environ", {"SASE_BUG_ID": "12345"}),
        ):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        assert "BUG=12345" in sent["message"]

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_bug_tag_from_payload(
        self,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Fix bug", "bug_id": "99999"}
        wf = CommitWorkflow(payload, "create_pull_request")

        with patch("sase.vcs_provider.config.get_pr_tags", return_value={}):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        assert "BUG=99999" in sent["message"]

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_bug_tag_payload_overrides_env(
        self,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Fix bug", "bug_id": "111"}
        wf = CommitWorkflow(payload, "create_pull_request")

        with (
            patch("sase.vcs_provider.config.get_pr_tags", return_value={}),
            patch.dict("os.environ", {"SASE_BUG_ID": "222"}),
        ):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        assert "BUG=111" in sent["message"]
        assert "BUG=222" not in sent["message"]

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_bug_tag_zero_skipped(
        self,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Add feature"}
        wf = CommitWorkflow(payload, "create_pull_request")

        with (
            patch("sase.vcs_provider.config.get_pr_tags", return_value={}),
            patch.dict("os.environ", {"SASE_BUG_ID": "0"}),
        ):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        assert "BUG=" not in sent["message"]

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_bug_tag_unset_skipped(
        self,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Add feature"}
        wf = CommitWorkflow(payload, "create_pull_request")

        env = {k: v for k, v in os.environ.items() if k != "SASE_BUG_ID"}
        with (
            patch("sase.vcs_provider.config.get_pr_tags", return_value={}),
            patch.dict("os.environ", env, clear=True),
        ):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        assert "BUG=" not in sent["message"]

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_bug_tag_alongside_config_tags(
        self,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Fix bug"}
        wf = CommitWorkflow(payload, "create_pull_request")

        tags = {"AUTOSUBMIT_BEHAVIOR": "SYNC_SUBMIT", "MARKDOWN": "true"}
        with (
            patch("sase.vcs_provider.config.get_pr_tags", return_value=tags),
            patch.dict("os.environ", {"SASE_BUG_ID": "99"}),
        ):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        msg = sent["message"]
        assert "BUG=99" in msg
        assert "AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT" in msg
        assert "MARKDOWN=true" in msg
        # BUG should appear before other tags
        assert msg.index("BUG=99") < msg.index("AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT")

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_bug_tag_env_overrides_static_config(
        self,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Fix bug"}
        wf = CommitWorkflow(payload, "create_pull_request")

        tags = {"BUG": "static-111", "MARKDOWN": "true"}
        with (
            patch("sase.vcs_provider.config.get_pr_tags", return_value=tags),
            patch.dict("os.environ", {"SASE_BUG_ID": "222"}),
        ):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        msg = sent["message"]
        assert "BUG=222" in msg
        assert "BUG=static-111" not in msg

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    def test_no_tags_no_change(
        self,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Add feature"}
        wf = CommitWorkflow(payload, "create_pull_request")

        with patch("sase.vcs_provider.config.get_pr_tags", return_value={}):
            wf.run()

        sent_payload = provider.create_pull_request.call_args[0][0]
        assert sent_payload["message"] == "Add feature"
