"""Tests for CommitWorkflow plan storage hooks."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.sdd.committed_plan_validation import _CommittedPlanValidationError
from sase.workflows.commit.plan_hooks import handle_sase_plan
from tests.sdd_policy_helpers import patched_sdd_policy

_CONFIG_TARGET = "sase.workflows.commit.command_hooks.load_merged_config"
_PLAN_REPO_ROOT_TARGET = "sase.workflows.commit.plan_hooks.get_repo_root"


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


class TestHandleSasePlanStorage:
    """Verify handle_sase_plan stores ordinary plans according to policy."""

    def test_vc_true_copies_plan_into_repo(self, tmp_path: Path) -> None:
        """version_controlled=True: plan is copied into sdd/plans/<YYYYMM>/."""
        plan_file = tmp_path / "my_plan.md"
        plan_file.write_text("# Plan\nstatus: wip\n")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        payload: dict = {"message": "fix: bug"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patched_sdd_policy("in_tree"),
            patch(_PLAN_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("sase.sdd.files.get_yyyymm", return_value="202603"),
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert "_plan_path" in payload
        dest = repo_dir / "sdd" / "plans" / "202603" / "my_plan.md"
        assert dest.exists()
        assert "tier: tale" in dest.read_text(encoding="utf-8")
        assert "SASE_PLAN=sdd/plans/202603/my_plan.md" in payload["message"]

    def test_rejects_invalid_cutover_plan_before_copy(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "my_plan.md"
        plan_file.write_text(
            "---\ntier: tale\nstatus: wip\n---\n# Plan\n",
            encoding="utf-8",
        )
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        payload: dict = {"message": "fix: bug"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patched_sdd_policy("in_tree"),
            patch(_PLAN_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("sase.sdd.files.get_yyyymm", return_value="202608"),
            patch(
                "sase.file_references.format_with_prettier",
                side_effect=lambda content: content,
            ),
            pytest.raises(_CommittedPlanValidationError, match="required-missing"),
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert payload == {"message": "fix: bug"}
        assert not (repo_dir / "sdd" / "plans" / "202608" / "my_plan.md").exists()

    def test_vc_true_in_repo_absolute_plan_uses_repo_relative_tag(
        self, tmp_path: Path
    ) -> None:
        """version_controlled=True: existing in-repo plans are tagged repo-relative."""
        repo_dir = tmp_path / "repo"
        plan_file = repo_dir / "sdd" / "plans" / "202605" / "my_plan.md"
        plan_file.parent.mkdir(parents=True)
        plan_file.write_text("---\nstatus: wip\n---\n# Plan\n", encoding="utf-8")

        payload: dict = {"message": "fix: bug"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patched_sdd_policy("in_tree"),
            patch(_PLAN_REPO_ROOT_TARGET, return_value=str(repo_dir)),
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert payload["_plan_path"] == str(plan_file)
        assert "SASE_PLAN=sdd/plans/202605/my_plan.md" in payload["message"]
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
            patch(_PLAN_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("sase.sdd.files.get_yyyymm", return_value="202603"),
            patch(
                "sase.sdd.files.commit_sdd_store_files",
                side_effect=capture_committed_plan,
            ) as mock_commit,
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert "_plan_path" not in payload
        dest = repo_dir / ".sase" / "sdd" / "plans" / "202603" / "my_plan.md"
        assert dest.exists()
        assert "status: done" in dest.read_text(encoding="utf-8")
        assert "tier: tale" in dest.read_text(encoding="utf-8")
        assert payload["message"].endswith("SASE_PLAN=plans/202603/my_plan.md")
        mock_commit.assert_called_once()
        store_arg, message = mock_commit.call_args.args
        assert store_arg.sdd_dir == repo_dir / ".sase" / "sdd"
        assert message == "Add SDD plan for my_plan"
        assert mock_commit.call_args.kwargs == {"paths": [str(dest)]}
        assert committed_contents == [dest.read_text(encoding="utf-8")]
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
            patch(_PLAN_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("os.path.expanduser", return_value=str(tmp_path)),
            patch("sase.sdd.files.get_yyyymm", return_value="202603"),
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert "_plan_path" in payload
        assert (repo_dir / "sdd" / "plans" / "202603" / "my_plan.md").exists()

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
            patch(_PLAN_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("os.path.expanduser", return_value=str(tmp_path)),
            patch("sase.sdd.files.get_yyyymm", return_value="202603"),
            patch("sase.sdd.files.commit_sdd_store_files") as mock_commit,
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert "_plan_path" not in payload
        dest = repo_dir / ".sase" / "sdd" / "plans" / "202603" / "my_plan.md"
        assert dest.exists()
        assert "status: done" in dest.read_text(encoding="utf-8")
        assert payload["message"].endswith("SASE_PLAN=plans/202603/my_plan.md")
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
            patch(_PLAN_REPO_ROOT_TARGET, return_value=str(repo_dir)),
        ):
            handle_sase_plan(payload, str(repo_dir))

        dest = repo_dir / "sdd" / "plans" / "202511" / "my_plan.md"
        assert dest.exists()

    def test_vc_true_ignores_retired_plans_prompt_snapshot(
        self, tmp_path: Path
    ) -> None:
        plan_file = tmp_path / "my_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        repo_dir = tmp_path / "repo"
        prompt_file = repo_dir / "sdd" / "plans" / "202603" / "prompts" / "my_plan.md"
        prompt_file.parent.mkdir(parents=True)
        prompt_file.write_text("# Prompt\n", encoding="utf-8")

        payload: dict = {"message": "fix: bug"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patched_sdd_policy("in_tree"),
            patch(_PLAN_REPO_ROOT_TARGET, return_value=str(repo_dir)),
            patch("sase.sdd.files.get_yyyymm", return_value="202603"),
        ):
            handle_sase_plan(payload, str(repo_dir))

        dest = repo_dir / "sdd" / "plans" / "202603" / "my_plan.md"
        text = dest.read_text(encoding="utf-8")
        assert "**PROMPT:**" not in text
        assert prompt_file.read_text(encoding="utf-8") == "# Prompt\n"
        assert payload["_plan_path"] == str(dest)
