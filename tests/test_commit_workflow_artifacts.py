"""Tests for CommitWorkflow result markers, PR body, commit entries, and plan handling."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.sdd.store import write_sdd_store_record
from sase.workflows.commit.commit_tracking import (
    append_commits_entry,
    record_sdd_commit_result_marker,
    write_result_marker,
)
from sase.workflows.commit.commit_hooks import handle_beads, handle_sase_plan
from sase.workflows.commit.pr_operations import build_pr_body
from tests.sdd_policy_helpers import patched_sdd_policy

_CONFIG_TARGET = "sase.workflows.commit.commit_hooks.load_merged_config"
_GET_REPO_ROOT_TARGET = "sase.workflows.commit.commit_hooks._get_repo_root"


@pytest.fixture(autouse=True)
def _no_commit_hooks():  # type: ignore[no-untyped-def]
    """Prevent commit hooks and SASE_PLAN from running in tests."""
    with (
        patch(
            _CONFIG_TARGET,
            return_value={"commit_hooks": {"before": "", "after": ""}},
        ),
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
                "run_id": Path(tmpdir).name,
                "cwd": os.getcwd(),
                "result": "abc123",
                "commit_result": "abc123",
                "message": "fix: bug",
                "name": "feat-x",
                "bead_id": "",
                "changespec_name": "proj_feat_1",
                "commit_changespec_name": "proj_feat_1",
                "entry_id": None,
                "commit_entry_id": None,
                "diff_path": None,
                "commit_diff_path": None,
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
            assert data["commit_entry_id"] == "entry_42"

    def test_accumulates_commit_results_and_upserts_entry_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "fix: primary"}
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch("os.getcwd", return_value="/workspace/sase_7"),
            ):
                write_result_marker(
                    "create_commit",
                    payload,
                    "/tmp/primary.diff",
                    "abc123",
                    "proj_feat_1",
                )

            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch("os.getcwd", return_value="/workspace/sase-core_7"),
            ):
                write_result_marker(
                    "create_commit",
                    {"message": "fix: linked"},
                    "/tmp/linked.diff",
                    "def456",
                    "proj_feat_1",
                )

            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch("os.getcwd", return_value="/workspace/sase_7"),
            ):
                write_result_marker(
                    "create_commit",
                    payload,
                    "/tmp/primary.diff",
                    "abc123",
                    "proj_feat_1",
                    entry_id="entry_1",
                )

            latest = json.loads((Path(tmpdir) / "commit_result.json").read_text())
            assert latest["cwd"] == "/workspace/sase_7"
            assert latest["result"] == "abc123"
            assert latest["entry_id"] == "entry_1"

            results = json.loads((Path(tmpdir) / "commit_results.json").read_text())
            assert [item["cwd"] for item in results] == [
                "/workspace/sase_7",
                "/workspace/sase-core_7",
            ]
            assert [item["result"] for item in results] == ["abc123", "def456"]
            assert results[0]["entry_id"] == "entry_1"
            assert results[1]["entry_id"] is None

    def test_corrupt_commit_results_file_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "commit_results.json").write_text("{", encoding="utf-8")
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch("os.getcwd", return_value="/workspace/sase_7"),
            ):
                write_result_marker(
                    "create_commit",
                    {"message": "fix: bug"},
                    None,
                    "abc123",
                    None,
                )

            results = json.loads((Path(tmpdir) / "commit_results.json").read_text())
            assert len(results) == 1
            assert results[0]["cwd"] == "/workspace/sase_7"
            assert results[0]["result"] == "abc123"

    def test_writes_agent_run_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "fix: bug"}
            with patch.dict(
                "os.environ",
                {
                    "SASE_ARTIFACTS_DIR": tmpdir,
                    "SASE_AGENT_TIMESTAMP": "20260522112233",
                },
            ):
                write_result_marker("create_commit", payload, None, "abc123", None)

            data = json.loads((Path(tmpdir) / "commit_result.json").read_text())
            assert data["run_id"] == "20260522112233"
            assert data["cwd"] == os.getcwd()

    def test_persists_commit_diff_path_without_graph_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta_path = Path(tmpdir) / "agent_meta.json"
            meta_path.write_text(json.dumps({"name": "agent-alpha"}))
            diff_path = str(Path(tmpdir) / "commit.diff")
            payload = {"message": "fix: bug", "bead_id": "sase-1.2"}
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch(
                    "sase.workflows.commit.commit_tracking."
                    "update_agent_artifact_index_for_marker_mutation"
                ) as update_index,
            ):
                write_result_marker(
                    "create_commit",
                    payload,
                    diff_path,
                    "abc123",
                    "proj_feat_1",
                    entry_id="7",
                )

            meta = json.loads(meta_path.read_text())
            assert meta == {
                "name": "agent-alpha",
                "commit_diff_path": diff_path,
            }
            assert "commit_entry_id" not in meta
            assert "commit_result" not in meta
            assert "commit_changespec_name" not in meta
            update_index.assert_called_once_with(tmpdir)

    def test_does_not_update_agent_meta_without_diff_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta_path = Path(tmpdir) / "agent_meta.json"
            meta_path.write_text(json.dumps({"name": "agent-alpha"}))
            payload = {"message": "fix: bug"}
            with (
                patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}),
                patch(
                    "sase.workflows.commit.commit_tracking."
                    "update_agent_artifact_index_for_marker_mutation"
                ) as update_index,
            ):
                write_result_marker(
                    "create_commit",
                    payload,
                    None,
                    "abc123",
                    "proj_feat_1",
                    entry_id="7",
                )

            meta = json.loads(meta_path.read_text())
            assert meta == {"name": "agent-alpha"}
            update_index.assert_not_called()

    def test_skips_when_no_artifacts_dir(self) -> None:
        payload = {"message": "test"}
        with patch.dict("os.environ", {}, clear=True):
            # Should not raise
            write_result_marker("create_commit", payload, None, "abc", None)

    def test_records_sdd_commit_in_results_list_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "sase.workflows.commit.commit_tracking."
                "update_agent_artifact_index_for_marker_mutation"
            ) as update_index:
                record_sdd_commit_result_marker(
                    artifacts_dir=tmpdir,
                    cwd="/workspace/sase/.sase/sdd",
                    result="abc123",
                    message="Archive approved plan demo\n\nSASE_TYPE=sdd",
                    repo_name="sase-org/sase--sdd",
                )
                record_sdd_commit_result_marker(
                    artifacts_dir=tmpdir,
                    cwd="/workspace/sase/.sase/sdd",
                    result="abc123",
                    message="Archive approved plan demo updated\n\nSASE_TYPE=sdd",
                    repo_name="sase-org/sase--sdd",
                )

            assert not (Path(tmpdir) / "commit_result.json").exists()
            results = json.loads((Path(tmpdir) / "commit_results.json").read_text())
            assert results == [
                {
                    "method": "sdd_commit",
                    "run_id": Path(tmpdir).name,
                    "cwd": "/workspace/sase/.sase/sdd",
                    "result": "abc123",
                    "commit_result": "abc123",
                    "message": "Archive approved plan demo updated\n\nSASE_TYPE=sdd",
                    "repo_name": "sase-org/sase--sdd",
                    "diff_path": None,
                    "commit_diff_path": None,
                }
            ]
            assert update_index.call_count == 2
            update_index.assert_called_with(tmpdir)


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
        project_file = tmp_path / "proj.sase"
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
        project_file = tmp_path / "proj.sase"
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
    """Verify handle_sase_plan honors each SDD storage layout."""

    def test_vc_true_copies_plan_into_repo(self, tmp_path: Path) -> None:
        """version_controlled=True: plan is copied into sdd/tales/<YYYYMM>/."""
        plan_file = tmp_path / "my_plan.md"
        plan_file.write_text("# Plan\nstatus: wip\n")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        payload: dict = {"message": "fix: bug"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patched_sdd_policy("in_tree"),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("sase.sdd.files.get_yyyymm", return_value="202603"),
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert "_plan_path" in payload
        dest = repo_dir / "sdd" / "tales" / "202603" / "my_plan.md"
        assert dest.exists()
        assert "SASE_PLAN=sdd/tales/202603/my_plan.md" in payload["message"]

    def test_vc_true_in_repo_absolute_plan_uses_repo_relative_tag(
        self, tmp_path: Path
    ) -> None:
        """version_controlled=True: existing in-repo plans are tagged repo-relative."""
        repo_dir = tmp_path / "repo"
        plan_file = repo_dir / "sdd" / "tales" / "202605" / "my_plan.md"
        plan_file.parent.mkdir(parents=True)
        plan_file.write_text("---\nstatus: wip\n---\n# Plan\n", encoding="utf-8")

        payload: dict = {"message": "fix: bug"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patched_sdd_policy("in_tree"),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert payload["_plan_path"] == str(plan_file)
        assert "SASE_PLAN=sdd/tales/202605/my_plan.md" in payload["message"]
        assert str(repo_dir) not in payload["message"]

    def test_local_store_copies_external_plan_and_tags_it(self, tmp_path: Path) -> None:
        """Store-backed plans are copied and tagged relative to the store."""
        plan_file = tmp_path / "my_plan.md"
        plan_file.write_text("# Plan\nstatus: wip\n")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        payload: dict = {"message": "fix: bug"}
        committed_contents: list[str] = []

        def capture_committed_plan(*_args: object, **kwargs: object) -> None:
            paths = kwargs["paths"]
            assert isinstance(paths, list)
            committed_contents.append(Path(paths[0]).read_text(encoding="utf-8"))

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patched_sdd_policy("local"),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("sase.sdd.files.get_yyyymm", return_value="202603"),
            patch(
                "sase.sdd.files.commit_sdd_store_files",
                side_effect=capture_committed_plan,
            ) as mock_commit,
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert "_plan_path" not in payload
        dest = repo_dir / ".sase" / "sdd" / "tales" / "202603" / "my_plan.md"
        assert dest.exists()
        assert "status: done" in dest.read_text(encoding="utf-8")
        assert payload["message"].endswith("SASE_PLAN=tales/202603/my_plan.md")
        mock_commit.assert_called_once()
        store_arg, message = mock_commit.call_args.args
        assert store_arg.sdd_dir == repo_dir / ".sase" / "sdd"
        assert message == "Add SDD plan for my_plan"
        assert mock_commit.call_args.kwargs == {"paths": [str(dest)]}
        assert committed_contents == [dest.read_text(encoding="utf-8")]
        assert "status: done" in committed_contents[0]

    def test_separate_repo_plan_is_tagged_without_code_repo_staging(
        self, tmp_path: Path
    ) -> None:
        """An approved companion-store plan is tagged but not copied or staged."""
        repo_dir = tmp_path / "repo"
        plan_file = repo_dir / ".sase" / "sdd" / "tales" / "202607" / "my_plan.md"
        plan_file.parent.mkdir(parents=True)
        plan_file.write_text("---\nstatus: wip\n---\n# Plan\n", encoding="utf-8")
        write_sdd_store_record(
            repo_dir,
            {
                "storage": "separate_repo",
                "provider": "github",
                "repo": "owner/repo--sdd",
                "remote_url": "git@example.com:owner/repo--sdd.git",
                "discovery": "found",
            },
        )
        payload: dict = {"message": "fix: bug"}
        committed_contents: list[str] = []

        def capture_committed_plan(*_args: object, **kwargs: object) -> None:
            paths = kwargs["paths"]
            assert isinstance(paths, list)
            committed_contents.append(Path(paths[0]).read_text(encoding="utf-8"))

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch(
                "sase.sdd.files.commit_sdd_store_files",
                side_effect=capture_committed_plan,
            ) as mock_commit,
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert "_plan_path" not in payload
        assert "status: done" in plan_file.read_text(encoding="utf-8")
        assert payload["message"].endswith("SASE_PLAN=tales/202607/my_plan.md")
        mock_commit.assert_called_once()
        store_arg, message = mock_commit.call_args.args
        assert store_arg.sdd_dir == repo_dir / ".sase" / "sdd"
        assert message == "Complete SDD plan for my_plan"
        assert mock_commit.call_args.kwargs == {"paths": [str(plan_file)]}
        assert committed_contents == [plan_file.read_text(encoding="utf-8")]
        assert "status: done" in committed_contents[0]

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
            patched_sdd_policy("in_tree"),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("os.path.expanduser", return_value=str(tmp_path)),
            patch("sase.sdd.files.get_yyyymm", return_value="202603"),
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert "_plan_path" in payload
        assert (repo_dir / "sdd" / "tales" / "202603" / "my_plan.md").exists()

    def test_archive_fallback_local_copies_into_store(self, tmp_path: Path) -> None:
        """An archived plan is normalized, committed, and tagged in the store."""
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
            patched_sdd_policy("local"),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("os.path.expanduser", return_value=str(tmp_path)),
            patch("sase.sdd.files.get_yyyymm", return_value="202603"),
            patch("sase.sdd.files.commit_sdd_store_files") as mock_commit,
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert "_plan_path" not in payload
        dest = repo_dir / ".sase" / "sdd" / "tales" / "202603" / "my_plan.md"
        assert dest.exists()
        assert "status: done" in dest.read_text(encoding="utf-8")
        assert payload["message"].endswith("SASE_PLAN=tales/202603/my_plan.md")
        mock_commit.assert_called_once()

    def test_vc_true_extracts_yyyymm_from_frontmatter(self, tmp_path: Path) -> None:
        """version_controlled=True: YYYYMM is extracted from create_time frontmatter."""
        plan_file = tmp_path / "my_plan.md"
        plan_file.write_text("---\ncreate_time: 2025-11-15 10:30:00\n---\n# Plan\n")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        payload: dict = {"message": "fix: bug"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patched_sdd_policy("in_tree"),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
        ):
            handle_sase_plan(payload, str(repo_dir))

        dest = repo_dir / "sdd" / "tales" / "202511" / "my_plan.md"
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
            patched_sdd_policy("in_tree"),
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("sase.sdd.files.get_yyyymm", return_value="202603"),
        ):
            handle_sase_plan(payload, str(repo_dir))

        dest = repo_dir / "sdd" / "tales" / "202603" / "my_plan.md"
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
            "sase.workflows.commit.commit_hooks.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            handle_beads(payload, str(tmp_path))

        assert payload["message"] == "Fix bug (B-123)"

    def test_bead_sync_runs_when_bead_dir_exists(self, tmp_path: Path) -> None:
        (tmp_path / "sdd/beads").mkdir(parents=True)
        payload = {"message": "Fix bug"}
        with patch(
            "sase.workflows.commit.commit_hooks.subprocess.run",
        ) as mock_run:
            handle_beads(payload, str(tmp_path))

        mock_run.assert_called_once_with(
            ["sase", "bead", "sync"],
            cwd=str(tmp_path),
            capture_output=True,
            check=False,
        )
