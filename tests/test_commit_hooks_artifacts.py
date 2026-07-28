"""Tests for CommitWorkflow plan and bead hooks."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.sdd.committed_plan_validation import _CommittedPlanValidationError
from sase.sdd.store import write_sdd_store_record
from sase.workflows.commit.commit_hooks import handle_beads, handle_sase_plan
from tests.sdd_policy_helpers import patched_sdd_policy

_CONFIG_TARGET = "sase.workflows.commit.commit_hooks.load_merged_config"
_GET_REPO_ROOT_TARGET = "sase.workflows.commit.commit_hooks._get_repo_root"


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q"],
        cwd=path,
        check=True,
        capture_output=True,
    )


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


class TestHandleSasePlan:
    """Verify handle_sase_plan honors each SDD storage layout."""

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
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
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
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
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
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
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
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
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

    def test_separate_repo_plan_is_tagged_without_code_repo_staging(
        self, tmp_path: Path
    ) -> None:
        """An approved sidecar-store plan is tagged but not copied or staged."""
        repo_dir = tmp_path / "repo"
        plan_file = repo_dir / ".sase" / "sdd" / "plans" / "202607" / "my_plan.md"
        plan_file.parent.mkdir(parents=True)
        plan_file.write_text(
            "---\ntier: tale\nstatus: wip\n---\n# Plan\n",
            encoding="utf-8",
        )
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
        assert payload["message"].endswith("SASE_PLAN=plans/202607/my_plan.md")
        mock_commit.assert_called_once()
        store_arg, message = mock_commit.call_args.args
        assert store_arg.sdd_dir == repo_dir / ".sase" / "sdd"
        assert message == "Complete SDD plan for my_plan"
        assert mock_commit.call_args.kwargs == {"paths": [str(plan_file)]}
        assert committed_contents == [plan_file.read_text(encoding="utf-8")]
        assert "status: done" in committed_contents[0]

    def test_plan_in_different_sdd_clone_uses_owning_store(
        self, tmp_path: Path
    ) -> None:
        """A linked-repo commit never copies a host plan into its own store."""
        code_repo = tmp_path / "linked-repo"
        _init_git_repo(code_repo)
        cwd_store = code_repo / ".sase" / "sdd"
        cwd_store.mkdir(parents=True)
        write_sdd_store_record(
            code_repo,
            {
                "storage": "separate_repo",
                "provider": "github",
                "repo": "owner/linked-repo--sdd",
                "remote_url": "git@example.com:owner/linked-repo--sdd.git",
                "discovery": "found",
            },
        )

        owning_store = tmp_path / "host-plans"
        _init_git_repo(owning_store)
        plan_file = owning_store / "202607" / "my_plan.md"
        plan_file.parent.mkdir()
        plan_file.write_text(
            "---\ntier: tale\nstatus: wip\n---\n# Plan\n",
            encoding="utf-8",
        )
        payload: dict = {"message": "fix: linked code"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patch("sase.sdd.files.commit_sdd_store_files") as mock_commit,
        ):
            handle_sase_plan(payload, str(code_repo))

        assert "_plan_path" not in payload
        assert payload["message"].endswith("SASE_PLAN=202607/my_plan.md")
        assert "status: done" in plan_file.read_text(encoding="utf-8")
        assert not (cwd_store / "plans" / "202607" / "my_plan.md").exists()
        mock_commit.assert_called_once()
        store_arg, message = mock_commit.call_args.args
        assert store_arg.sdd_dir == owning_store
        assert message == "Complete SDD plan for my_plan"
        assert mock_commit.call_args.kwargs == {"paths": [str(plan_file)]}

    def test_linked_repo_commit_links_flat_github_plan_in_owning_sidecar(
        self, tmp_path: Path
    ) -> None:
        code_repo = tmp_path / "linked-repo"
        _init_git_repo(code_repo)
        owning_store = tmp_path / "host-plans"
        _init_git_repo(owning_store)
        subprocess.run(
            ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
            cwd=owning_store,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "remote",
                "add",
                "origin",
                "git@github.com:sase-org/sase--plans.git",
            ],
            cwd=owning_store,
            check=True,
            capture_output=True,
        )
        plan_file = owning_store / "202607" / "my_plan.md"
        plan_file.parent.mkdir()
        plan_file.write_text(
            "---\ntier: tale\nstatus: wip\n---\n# Plan\n",
            encoding="utf-8",
        )
        payload: dict = {"message": "fix: linked code"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patch("sase.sdd.files.commit_sdd_store_files"),
        ):
            handle_sase_plan(payload, str(code_repo))

        assert payload["message"] == (
            "fix: linked code\n\nSASE_PLAN=[202607/my_plan.md][1]\n\n"
            "[1]: https://github.com/sase-org/sase--plans/blob/"
            "main/202607/my_plan.md"
        )

    def test_legacy_separate_github_store_links_plans_prefixed_path(
        self, tmp_path: Path
    ) -> None:
        repo_dir = tmp_path / "repo"
        _init_git_repo(repo_dir)
        store_root = repo_dir / ".sase" / "sdd"
        _init_git_repo(store_root)
        subprocess.run(
            ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
            cwd=store_root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "remote",
                "add",
                "origin",
                "git@github.com:acme/widget--sdd.git",
            ],
            cwd=store_root,
            check=True,
            capture_output=True,
        )
        write_sdd_store_record(
            repo_dir,
            {
                "storage": "separate_repo",
                "provider": "github",
                "repo": "acme/widget--sdd",
                "remote_url": "git@github.com:acme/widget--sdd.git",
                "discovery": "found",
            },
        )
        plan_file = store_root / "plans" / "202607" / "my_plan.md"
        plan_file.parent.mkdir(parents=True)
        plan_file.write_text(
            "---\ntier: tale\nstatus: wip\n---\n# Plan\n",
            encoding="utf-8",
        )
        payload: dict = {"message": "fix: code"}

        with (
            patch.dict("os.environ", {"SASE_PLAN": str(plan_file)}),
            patch("sase.sdd.files.commit_sdd_store_files"),
        ):
            handle_sase_plan(payload, str(repo_dir))

        assert payload["message"] == (
            "fix: code\n\nSASE_PLAN=[plans/202607/my_plan.md][1]\n\n"
            "[1]: https://github.com/acme/widget--sdd/blob/"
            "main/plans/202607/my_plan.md"
        )

    def test_archive_plan_from_linked_repo_routes_to_host_store(
        self, tmp_path: Path
    ) -> None:
        host = tmp_path / "host"
        linked_repo = host / "sase" / "repos" / "linked" / "foreign"
        _init_git_repo(linked_repo)
        host_store = host / ".sase" / "sdd"
        host_store.mkdir(parents=True)
        write_sdd_store_record(
            host,
            {
                "storage": "separate_repo",
                "provider": "github",
                "repo": "owner/host--sdd",
                "remote_url": "git@example.com:owner/host--sdd.git",
                "discovery": "found",
            },
        )
        (host / ".sase" / "checkout.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "project_name": "host",
                    "project_key": "host-key",
                    "workspace_num": 2,
                    "primary_workspace_dir": str(host),
                    "registry_path": str(tmp_path / "registry.json"),
                }
            ),
            encoding="utf-8",
        )

        sase_home = tmp_path / "sase-home"
        archive_plan = sase_home / "plans" / "202607" / "my_plan.md"
        archive_plan.parent.mkdir(parents=True)
        archive_plan.write_text("# Plan\nstatus: wip\n", encoding="utf-8")
        payload: dict = {"message": "fix: linked code"}

        with (
            patch.dict(
                "os.environ",
                {"SASE_HOME": str(sase_home), "SASE_PLAN": str(archive_plan)},
            ),
            patch("sase.sdd.files.commit_sdd_store_files") as mock_commit,
        ):
            handle_sase_plan(payload, str(linked_repo))

        dest = host_store / "plans" / "202607" / "my_plan.md"
        assert dest.exists()
        assert "status: done" in dest.read_text(encoding="utf-8")
        assert "_plan_path" not in payload
        assert payload["message"].endswith("SASE_PLAN=plans/202607/my_plan.md")
        assert not (linked_repo / ".sase" / "sdd").exists()
        mock_commit.assert_called_once()
        store_arg, message = mock_commit.call_args.args
        assert store_arg.sdd_dir == host_store
        assert message == "Add SDD plan for my_plan"
        assert mock_commit.call_args.kwargs == {"paths": [str(dest)]}

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
            patch(_GET_REPO_ROOT_TARGET, return_value=str(repo_dir)),
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
        prompt_file = repo_dir / "sdd" / "plans" / "202603" / "prompts" / "my_plan.md"
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

        dest = repo_dir / "sdd" / "plans" / "202603" / "my_plan.md"
        text = dest.read_text(encoding="utf-8")
        assert (
            "- **PROMPT:** [sdd/plans/202603/prompts/my_plan.md]"
            "(prompts/my_plan.md)" in text
        )
        assert payload["_plan_path"] == str(dest)


class TestHandleBeads:
    """Verify bead hook remains best-effort in test/CI environments."""

    def test_missing_sase_cli_is_non_fatal_and_message_is_unchanged(
        self, tmp_path: Path
    ) -> None:
        payload = {"message": "Fix bug", "bead_id": "B-123"}
        with patch(
            "sase.workflows.commit.commit_hooks.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            handle_beads(payload, str(tmp_path))

        assert payload["message"] == "Fix bug"

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

    def test_bead_sync_runs_when_split_sidecar_exists(self, tmp_path: Path) -> None:
        (tmp_path / "sase/repos/beads").mkdir(parents=True)
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
