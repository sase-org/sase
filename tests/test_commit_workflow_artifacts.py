"""Tests for CommitWorkflow result markers, PR body, commit entries, and plan handling."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.workflows.commit.commit_tracking import (
    append_commits_entry,
    write_result_marker,
)
from sase.workflows.commit.precommit_hooks import handle_beads, handle_sase_plan
from sase.workflows.commit.pr_operations import build_pr_body

_CONFIG_TARGET = "sase.workflows.commit.precommit_hooks.load_merged_config"
_SDD_CONFIG_TARGET = "sase.sdd.beads.get_sdd_config"
_GET_REPO_ROOT_TARGET = "sase.workflows.commit.precommit_hooks._get_repo_root"


@pytest.fixture(autouse=True)
def _no_precommit():  # type: ignore[no-untyped-def]
    """Prevent precommit commands and SASE_PLAN from running in tests."""
    with (
        patch(_CONFIG_TARGET, return_value={"precommit_command": ""}),
        patch.dict("os.environ", {"SASE_PLAN": ""}, clear=False),
    ):
        yield


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

    def test_skips_when_no_artifacts_dir(self) -> None:
        payload = {"message": "test"}
        with patch.dict("os.environ", {}, clear=True):
            # Should not raise
            write_result_marker("create_commit", payload, None, "abc", None)


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
        project_file = tmp_path / "proj.gp"
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
        project_file = tmp_path / "proj.gp"
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


class TestHandleSasePlan:
    """Verify handle_sase_plan gates copy/frontmatter/staging on version_controlled."""

    def test_vc_true_copies_plan_into_repo(self, tmp_path: Path) -> None:
        """version_controlled=True: plan is copied into sdd/plans/<YYYYMM>/."""
        plan_file = tmp_path / "my_plan.md"
        plan_file.write_text("# Plan\nstatus: wip\n")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        payload: dict = {"message": "fix: bug"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patch(_SDD_CONFIG_TARGET, return_value=True),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("sase.sdd.files.get_yyyymm", return_value="202603"),
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert "_plan_path" in payload
        dest = repo_dir / "sdd" / "plans" / "202603" / "my_plan.md"
        assert dest.exists()
        assert "PLAN=sdd/plans/202603/my_plan.md" in payload["message"]

    def test_vc_false_does_not_copy_plan(self, tmp_path: Path) -> None:
        """version_controlled=False: plan NOT copied, no _plan_path, no PLAN= tag."""
        plan_file = tmp_path / "my_plan.md"
        plan_file.write_text("# Plan\nstatus: wip\n")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        payload: dict = {"message": "fix: bug"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patch(_SDD_CONFIG_TARGET, return_value=False),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert "_plan_path" not in payload
        assert not (repo_dir / "plans").exists()
        assert "PLAN=" not in payload["message"]

    def test_archive_fallback_vc_true_copies(self, tmp_path: Path) -> None:
        """Archive fallback + version_controlled=True: copies into YYYYMM subdir."""
        archive_dir = tmp_path / ".sase" / "plans"
        archive_dir.mkdir(parents=True)
        archive_plan = archive_dir / "my_plan.md"
        archive_plan.write_text("# Plan\nstatus: wip\n")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        payload: dict = {"message": "fix: bug"}

        with (
            patch.dict(
                "os.environ",
                {"SASE_PLAN": "/nonexistent/my_plan.md"},
            ),
            patch(_SDD_CONFIG_TARGET, return_value=True),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("os.path.expanduser", return_value=str(tmp_path)),
            patch("sase.sdd.files.get_yyyymm", return_value="202603"),
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert "_plan_path" in payload
        assert (repo_dir / "sdd" / "plans" / "202603" / "my_plan.md").exists()

    def test_archive_fallback_vc_false_no_copy(self, tmp_path: Path) -> None:
        """Archive fallback + version_controlled=False: does NOT copy into repo."""
        archive_dir = tmp_path / ".sase" / "plans"
        archive_dir.mkdir(parents=True)
        archive_plan = archive_dir / "my_plan.md"
        archive_plan.write_text("# Plan\nstatus: wip\n")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        payload: dict = {"message": "fix: bug"}

        with (
            patch.dict(
                "os.environ",
                {"SASE_PLAN": "/nonexistent/my_plan.md"},
            ),
            patch(_SDD_CONFIG_TARGET, return_value=False),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("os.path.expanduser", return_value=str(tmp_path)),
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert "_plan_path" not in payload
        assert not (repo_dir / "plans").exists()
        assert "PLAN=" not in payload["message"]

    def test_vc_true_extracts_yyyymm_from_frontmatter(self, tmp_path: Path) -> None:
        """version_controlled=True: YYYYMM is extracted from create_time frontmatter."""
        plan_file = tmp_path / "my_plan.md"
        plan_file.write_text("---\ncreate_time: 2025-11-15 10:30:00\n---\n# Plan\n")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        payload: dict = {"message": "fix: bug"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patch(_SDD_CONFIG_TARGET, return_value=True),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
        ):
            handle_sase_plan(payload, str(repo_dir))

        dest = repo_dir / "sdd" / "plans" / "202511" / "my_plan.md"
        assert dest.exists()

    def test_vc_true_adds_prompt_frontmatter_when_prompt_exists(
        self, tmp_path: Path
    ) -> None:
        plan_file = tmp_path / "my_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        repo_dir = tmp_path / "repo"
        prompt_file = repo_dir / "sdd" / "prompts" / "202603" / "my_plan.md"
        prompt_file.parent.mkdir(parents=True)
        prompt_file.write_text("# Prompt\n", encoding="utf-8")

        payload: dict = {"message": "fix: bug"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patch(_SDD_CONFIG_TARGET, return_value=True),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("sase.sdd.files.get_yyyymm", return_value="202603"),
        ):
            handle_sase_plan(payload, str(repo_dir))

        dest = repo_dir / "sdd" / "plans" / "202603" / "my_plan.md"
        text = dest.read_text(encoding="utf-8")
        assert "prompt: sdd/prompts/202603/my_plan.md" in text
        assert payload["_plan_path"] == str(dest)


class TestHandleBeads:
    """Verify bead hook remains best-effort in test/CI environments."""

    def test_missing_sase_cli_is_non_fatal_and_message_is_still_tagged(
        self, tmp_path: Path
    ) -> None:
        payload = {"message": "Fix bug", "bead_id": "B-123"}
        with patch(
            "sase.workflows.commit.precommit_hooks.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            handle_beads(payload, str(tmp_path))

        assert payload["message"] == "Fix bug (B-123)"

    def test_bead_sync_runs_when_bead_dir_exists(self, tmp_path: Path) -> None:
        (tmp_path / "sdd/beads").mkdir(parents=True)
        payload = {"message": "Fix bug"}
        with patch(
            "sase.workflows.commit.precommit_hooks.subprocess.run",
        ) as mock_run:
            handle_beads(payload, str(tmp_path))

        mock_run.assert_called_once_with(
            ["sase", "bead", "sync"],
            cwd=str(tmp_path),
            capture_output=True,
            check=False,
        )
