"""Tests for pr_tags config reading and commit message appending."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.core.commit_footer_facade import LinkedCommitTagValue
from sase.vcs_provider.config import extract_pr_tags, get_pr_tags
from sase.workflows.commit.pr_operations import append_pr_tags, build_pr_body
from sase.workflows.commit.workflow import CommitWorkflow
from tests._commit_workflow_fixtures import (
    no_commit_hooks,  # noqa: F401 (imported for fixture discovery, re-used as fixture arg)
)

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"
_PR_TAGS_TARGET = "sase.vcs_provider.config.get_vcs_provider_config"
_PROJECT_NAME_TARGET = "sase.workflows.utils.get_project_from_workspace"
_FETCH_PARENT_TARGET = "sase.workflows.commit.pr_operations._fetch_parent_pr_tags"


@pytest.fixture(autouse=True)
def _no_commit_hooks(no_commit_hooks):  # type: ignore[no-untyped-def]  # noqa: F811
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

    @patch(_FETCH_PARENT_TARGET, return_value={})
    def test_existing_tag_block_is_updated_without_duplicate(
        self,
        _mock_fetch: MagicMock,
    ) -> None:
        payload = {"message": "Add feature\n\nPLAN=sdd/plans/plan.md\nMARKDOWN=false"}

        with patch(
            "sase.vcs_provider.config.get_pr_tags",
            return_value={"MARKDOWN": "true"},
        ):
            append_pr_tags(payload, None)

        assert payload["message"] == (
            "Add feature\n\nSASE_PLAN=sdd/plans/plan.md\nSASE_MARKDOWN=true"
        )


class TestExtractPrTags:
    """Unit tests for extract_pr_tags()."""

    def test_simple_tags(self) -> None:
        body = "Some description\n\nFOO=bar\nBAZ=qux"
        assert extract_pr_tags(body) == {"FOO": "bar", "BAZ": "qux"}

    def test_mixed_content(self) -> None:
        body = "Title\n\nSome body text.\n\nFOO=bar"
        assert extract_pr_tags(body) == {"FOO": "bar"}

    def test_no_tags(self) -> None:
        body = "Just a description\nwith no tags"
        assert extract_pr_tags(body) == {}

    def test_empty_string(self) -> None:
        assert extract_pr_tags("") == {}

    def test_trailing_blank_lines(self) -> None:
        body = "Description\n\nFOO=bar\nBAZ=1\n\n"
        assert extract_pr_tags(body) == {"FOO": "bar", "BAZ": "1"}

    def test_tag_with_equals_in_value(self) -> None:
        body = "Description\n\nFOO=a=b=c"
        assert extract_pr_tags(body) == {"FOO": "a=b=c"}

    def test_prefixed_tags_canonicalized(self) -> None:
        body = "Description\n\nSASE_TEAM=infra\nSASE_OWNER=alice"
        assert extract_pr_tags(body) == {"TEAM": "infra", "OWNER": "alice"}

    def test_mixed_legacy_and_prefixed_tags(self) -> None:
        body = "Description\n\nTEAM=infra\nSASE_OWNER=alice"
        assert extract_pr_tags(body) == {"TEAM": "infra", "OWNER": "alice"}

    def test_linked_tag_retains_destination(self) -> None:
        body = (
            "Description\n\nSASE_PLAN=[202607/p.md][4]\n\n"
            "[4]: https://github.com/acme/plans/blob/main/202607/p.md"
        )

        assert extract_pr_tags(body) == {
            "PLAN": LinkedCommitTagValue(
                "202607/p.md",
                "https://github.com/acme/plans/blob/main/202607/p.md",
                "4",
            )
        }


def test_linked_parent_tag_inheritance_keeps_reference_definition() -> None:
    parent_body = (
        "Parent\n\nSASE_PLAN=[202607/p.md][4]\n\n"
        "[4]: https://github.com/acme/plans/blob/main/202607/p.md"
    )
    payload = {"message": "Child"}

    with (
        patch(_FETCH_PARENT_TARGET, return_value=extract_pr_tags(parent_body)),
        patch("sase.vcs_provider.config.get_pr_tags", return_value={}),
    ):
        append_pr_tags(payload, "parent")

    assert payload["message"] == (
        "Child\n\nSASE_PLAN=[202607/p.md][4]\n\n"
        "[4]: https://github.com/acme/plans/blob/main/202607/p.md"
    )


def test_pr_body_agent_info_precedes_structured_footer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"llm_provider": "codex", "model": "gpt-5", "name": "worker"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    payload = {
        "message": (
            "Description\n\nSASE_PLAN=[202607/p.md][1]\n"
            "SASE_AGENT=[alice.athena.worker][2]\n\n"
            "[1]: https://github.com/acme/plans/blob/main/202607/p.md\n"
            "[2]: https://github.com/acme/project--agents/blob/main/"
            "agents/alice.athena.worker/README.md"
        )
    }

    build_pr_body(payload)

    assert payload["_pr_body"] == (
        "Description\n\n---\n**Model:** `codex/gpt-5`\n"
        "**Agent:** [alice.athena.worker]"
        "(https://github.com/acme/project--agents/blob/main/"
        "agents/alice.athena.worker/README.md)\n\n"
        "SASE_PLAN=[202607/p.md][1]\n"
        "SASE_AGENT=[alice.athena.worker][2]\n\n"
        "[1]: https://github.com/acme/plans/blob/main/202607/p.md\n"
        "[2]: https://github.com/acme/project--agents/blob/main/"
        "agents/alice.athena.worker/README.md"
    )


def test_linked_bead_tag_survives_into_pr_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"llm_provider": "codex", "model": "gpt-5"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    destination = (
        "https://github.com/sase-org/sase--beads/blob/main/pages/sase-ai/sase-ai.2.md"
    )
    payload = {
        "message": (f"Description\n\nSASE_BEAD=[sase-ai.2][1]\n\n[1]: {destination}")
    }

    build_pr_body(payload)

    assert "SASE_BEAD=[sase-ai.2][1]" in payload["_pr_body"]
    assert f"[1]: {destination}" in payload["_pr_body"]


class TestInheritParentPrTags:
    """Integration tests for parent PR tag inheritance."""

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    @patch(_FETCH_PARENT_TARGET, return_value={"TEAM": "infra", "OWNER": "alice"})
    def test_parent_tags_inherited(
        self,
        _mock_fetch: MagicMock,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Child PR"}
        wf = CommitWorkflow(payload, "create_pull_request")

        with patch("sase.vcs_provider.config.get_pr_tags", return_value={}):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        # Legacy parent tags are rendered with the SASE_ prefix on the child PR.
        assert "SASE_TEAM=infra" in sent["message"]
        assert "SASE_OWNER=alice" in sent["message"]

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    @patch(
        _FETCH_PARENT_TARGET,
        return_value={"BEAD": "sase-parent.1", "TEAM": "infra"},
    )
    def test_current_bead_tag_survives_inherited_pr_tags(
        self,
        _mock_fetch: MagicMock,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider
        payload = {
            "name": "feat-x",
            "message": "Child PR",
            "bead_id": "sase-ai.2",
        }

        with patch(
            "sase.vcs_provider.config.get_pr_tags",
            return_value={"SASE_BEAD": "configured-stale"},
        ):
            CommitWorkflow(payload, "create_pull_request").run()

        sent = provider.create_pull_request.call_args.args[0]
        assert sent["message"].count("SASE_BEAD=") == 1
        assert "SASE_BEAD=sase-ai.2" in sent["message"]
        assert "sase-parent.1" not in sent["message"]
        assert "configured-stale" not in sent["message"]
        assert "SASE_TEAM=infra" in sent["message"]

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    @patch(_FETCH_PARENT_TARGET, return_value={"TEAM": "infra", "OWNER": "alice"})
    def test_config_tags_override_parent(
        self,
        _mock_fetch: MagicMock,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Child PR"}
        wf = CommitWorkflow(payload, "create_pull_request")

        config_tags = {"TEAM": "platform"}
        with patch("sase.vcs_provider.config.get_pr_tags", return_value=config_tags):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        assert "TEAM=platform" in sent["message"]
        assert "TEAM=infra" not in sent["message"]
        assert "OWNER=alice" in sent["message"]

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    @patch(_FETCH_PARENT_TARGET, return_value={"BUG": "parent-111", "TEAM": "infra"})
    def test_bug_tag_overrides_parent(
        self,
        _mock_fetch: MagicMock,
        mock_get: MagicMock,
        _mock_proj: MagicMock,
    ) -> None:
        provider = MagicMock()
        provider.create_pull_request.return_value = (True, None)
        mock_get.return_value = provider

        payload = {"name": "feat-x", "message": "Child PR"}
        wf = CommitWorkflow(payload, "create_pull_request")

        with (
            patch("sase.vcs_provider.config.get_pr_tags", return_value={}),
            patch.dict("os.environ", {"SASE_BUG_ID": "child-222"}),
        ):
            wf.run()

        sent = provider.create_pull_request.call_args[0][0]
        assert "BUG=child-222" in sent["message"]
        assert "BUG=parent-111" not in sent["message"]
        assert "TEAM=infra" in sent["message"]

    @patch(_PROJECT_NAME_TARGET, return_value=None)
    @patch(_PROVIDER_TARGET)
    @patch(_FETCH_PARENT_TARGET, return_value={})
    def test_graceful_noop_when_no_parent_tags(
        self,
        _mock_fetch: MagicMock,
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

        sent = provider.create_pull_request.call_args[0][0]
        assert sent["message"] == "Add feature"
