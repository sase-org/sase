"""Tests for chat history names, paths, and catalog helpers."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sase.history.chat import (
    build_fork_injected_history,
    _get_branch_or_workspace_name,
    _load_chat_history,
    find_chat_by_timestamp,
    generate_chat_filename,
    get_chat_file_path,
    list_chat_histories,
    load_chat_for_resume,
    resolve_chat_file_path,
    save_chat_history,
)
from sase.history.chat_storage import iter_chat_files

from tests.conftest import redirect_sase_home

_GIT_SHOW_CURRENT = ["git", "branch", "--show-current"]


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_get_branch_or_workspace_name_strips_reverted_suffix() -> None:
    """Helper output wins and has its reverted suffix stripped."""
    helper = _completed(0, stdout="feature_branch__3\n")

    with (
        patch("sase.history.chat.run_shell_command", return_value=helper) as helper_cmd,
        patch("sase.history.chat.subprocess.run") as git_cmd,
    ):
        result = _get_branch_or_workspace_name()

    assert result == "feature_branch"
    helper_cmd.assert_called_once()
    git_cmd.assert_not_called()


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (127, ""),
        (1, "ignored\n"),
        (0, "\n"),
    ],
    ids=["missing", "failed", "empty"],
)
def test_get_branch_or_workspace_name_falls_through_to_git_branch(
    returncode: int, stdout: str
) -> None:
    """A missing, failed, or empty helper falls through to the current git branch."""
    helper = _completed(returncode, stdout=stdout, stderr="command not found")
    git = _completed(0, stdout="feature_branch__3\n")

    with (
        patch("sase.history.chat.run_shell_command", return_value=helper) as helper_cmd,
        patch("sase.history.chat.subprocess.run", return_value=git) as git_cmd,
    ):
        result = _get_branch_or_workspace_name()

    assert result == "feature_branch"
    helper_cmd.assert_called_once()
    git_cmd.assert_called_once_with(
        _GIT_SHOW_CURRENT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "git",
    [
        _completed(128, stdout=""),
        _completed(0, stdout="\n"),
    ],
    ids=["failed", "empty"],
)
def test_get_branch_or_workspace_name_falls_through_to_cwd_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git: MagicMock
) -> None:
    """A failed or empty git lookup falls through to the current directory name."""
    workdir = tmp_path / "myproj"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    helper = _completed(127, stderr="command not found")

    with (
        patch("sase.history.chat.run_shell_command", return_value=helper) as helper_cmd,
        patch("sase.history.chat.subprocess.run", return_value=git) as git_cmd,
    ):
        result = _get_branch_or_workspace_name()

    assert result == "myproj"
    helper_cmd.assert_called_once()
    git_cmd.assert_called_once_with(
        _GIT_SHOW_CURRENT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_get_branch_or_workspace_name_git_launch_error_uses_cwd_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A git process-launch error falls through to the current directory name."""
    workdir = tmp_path / "myproj"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    helper = _completed(127, stderr="command not found")

    with (
        patch("sase.history.chat.run_shell_command", return_value=helper) as helper_cmd,
        patch(
            "sase.history.chat.subprocess.run",
            side_effect=FileNotFoundError("git"),
        ) as git_cmd,
    ):
        result = _get_branch_or_workspace_name()

    assert result == "myproj"
    helper_cmd.assert_called_once()
    git_cmd.assert_called_once()


def test_get_branch_or_workspace_name_directory_fallback_strips_reverted_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The directory fallback also has a reverted suffix stripped."""
    workdir = tmp_path / "feature branch__2"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    helper = _completed(127, stderr="command not found")
    git = _completed(128, stdout="")

    with (
        patch("sase.history.chat.run_shell_command", return_value=helper) as helper_cmd,
        patch("sase.history.chat.subprocess.run", return_value=git) as git_cmd,
    ):
        result = _get_branch_or_workspace_name()

    assert result == "feature branch"
    helper_cmd.assert_called_once()
    git_cmd.assert_called_once()


def test_get_branch_or_workspace_name_empty_directory_name_uses_workspace() -> None:
    """An empty current-directory name falls back to the literal workspace label."""
    cwd = MagicMock()
    cwd.resolve.return_value.name = ""
    helper = _completed(127, stderr="command not found")
    git = _completed(128, stdout="")

    with (
        patch("sase.history.chat.run_shell_command", return_value=helper),
        patch("sase.history.chat.subprocess.run", return_value=git),
        patch("sase.history.chat.Path.cwd", return_value=cwd),
    ):
        assert _get_branch_or_workspace_name() == "workspace"


def test_missing_helper_workspace_fallback_round_trips_chat_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fallback-derived chat basenames still resolve for resume and fork lookups."""
    redirect_sase_home(monkeypatch, tmp_path)
    workspace = tmp_path / "feature branch__2"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    helper = _completed(127, stderr="command not found")
    git = _completed(128, stdout="")

    with (
        patch("sase.history.chat.run_shell_command", return_value=helper) as helper_cmd,
        patch("sase.history.chat.subprocess.run", return_value=git) as git_cmd,
        patch("sase.history.chat.generate_timestamp", return_value="260827_120000"),
    ):
        saved = save_chat_history(
            prompt="Continue from fallback",
            response="Fallback works",
            workflow="ace-run",
        )

    basename = Path(saved).stem
    assert basename == "feature_branch-ace_run-260827_120000"
    assert "Continue from fallback" in load_chat_for_resume(basename)
    rendered = build_fork_injected_history(
        [{"kind": "agent", "name": "fallback", "path": basename}]
    )
    assert "Continue from fallback" in rendered
    helper_cmd.assert_called_once()
    git_cmd.assert_called_once()


def testgenerate_chat_filename_with_agent() -> None:
    """Test generate_chat_filename with agent name."""
    with (
        patch(
            "sase.history.chat._get_branch_or_workspace_name", return_value="my-branch"
        ),
        patch("sase.history.chat.generate_timestamp", return_value="251128_120000"),
    ):
        # User/workflow-derived filename components are sanitized.
        result = generate_chat_filename("crs", agent="planner")
        assert result == "my_branch-crs-planner-251128_120000"


def testgenerate_chat_filename_with_explicit_values() -> None:
    """Test generate_chat_filename with explicit branch and timestamp."""
    result = generate_chat_filename(
        "rerun",
        branch_or_workspace="feature-branch",
        timestamp="251128130000",
    )
    assert result == "feature_branch-rerun-251128130000"


def testgenerate_chat_filename_sanitizes_path_like_branch() -> None:
    """Path-like branch/workspace labels are kept inside one basename."""
    result = generate_chat_filename(
        "ace-run",
        branch_or_workspace="~/org",
        timestamp="260501_225009",
    )

    assert result == "__org-ace_run-260501_225009"
    assert "/" not in result


def testgenerate_chat_filename_preserves_simple_shape() -> None:
    """Simple safe names keep the established branch-workflow-timestamp shape."""
    result = generate_chat_filename(
        "ace-run",
        branch_or_workspace="feature_branch",
        timestamp="260501_225009",
    )

    assert result == "feature_branch-ace_run-260501_225009"


def testget_chat_file_path_with_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_chat_file_path returns the sharded write location for a basename."""
    redirect_sase_home(monkeypatch, tmp_path)
    result = get_chat_file_path("my-branch-run-251128_120000.md")
    # Sharded into the YYYYMM directory derived from the filename timestamp.
    assert result == str(
        tmp_path / "chats" / "202511" / "my-branch-run-251128_120000.md"
    )


def test__load_chat_history_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test _load_chat_history with non-existent file."""
    redirect_sase_home(monkeypatch, tmp_path)
    with pytest.raises(FileNotFoundError):
        _load_chat_history("nonexistent-run-251128_120000")


def test_list_chat_histories_nonexistent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test list_chat_histories when directory doesn't exist."""
    # Redirect ~/.sase/ into an empty tmp_path -- no chats/ subdir.
    redirect_sase_home(monkeypatch, tmp_path)
    result = list_chat_histories()
    assert result == []


def test_list_chat_histories_with_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test list_chat_histories with multiple files."""
    redirect_sase_home(monkeypatch, tmp_path)
    chats_shard = tmp_path / "chats" / "202511"
    chats_shard.mkdir(parents=True)
    (chats_shard / "test-run-251128_120000.md").write_text("content")
    (chats_shard / "test-run-251128_130000.md").write_text("content")

    result = list_chat_histories()
    assert len(result) == 2
    assert "test-run-251128_120000" in result
    assert "test-run-251128_130000" in result


def test_iter_chat_files_includes_imported_non_shard_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path)
    chats = tmp_path / "chats"
    sharded = chats / "202511" / "test-run-251128_120000.md"
    legacy = chats / "legacy-run-251128_120001.md"
    imported = chats / "v2-abc" / "imported-v2-alpha-v2-abcdef.md"
    sharded.parent.mkdir(parents=True)
    imported.parent.mkdir(parents=True)
    sharded.write_text("sharded", encoding="utf-8")
    legacy.write_text("legacy", encoding="utf-8")
    imported.write_text("imported", encoding="utf-8")

    assert [path.name for path in iter_chat_files()] == [
        "test-run-251128_120000.md",
        "legacy-run-251128_120001.md",
        "imported-v2-alpha-v2-abcdef.md",
    ]


def test_list_chat_histories_deduplicates_by_basename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path)
    sharded = tmp_path / "chats" / "202511" / "same-run-251128_120000.md"
    imported = tmp_path / "chats" / "v2-abc" / "same-run-251128_120000.md"
    sharded.parent.mkdir(parents=True)
    imported.parent.mkdir(parents=True)
    sharded.write_text("sharded", encoding="utf-8")
    imported.write_text("imported", encoding="utf-8")

    assert list_chat_histories() == ["same-run-251128_120000"]


def test_find_chat_by_timestamp_finds_imported_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path)
    imported = tmp_path / "chats" / "v2-abc" / "imported-run-251128_120000.md"
    imported.parent.mkdir(parents=True)
    imported.write_text("imported", encoding="utf-8")

    assert find_chat_by_timestamp("251128_120000") == str(imported).replace(
        str(Path.home()), "~"
    )


def test_resolve_chat_file_path_finds_imported_basename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path)
    imported = tmp_path / "chats" / "v2-abc" / "imported-v2-alpha-v2-abcdef.md"
    imported.parent.mkdir(parents=True)
    imported.write_text("imported", encoding="utf-8")

    assert resolve_chat_file_path("imported-v2-alpha-v2-abcdef") == str(imported)


def test__load_chat_history_with_increment_headings() -> None:
    """Test _load_chat_history with increment_headings=True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.md"
        content = """# Main Title

## Section 1

Some content here.

### Subsection

More content.

#### Deep section

Even more."""
        test_file.write_text(content, encoding="utf-8")

        result = _load_chat_history(str(test_file), increment_headings=True)

        # All headings should be incremented by one level
        assert "## Main Title" in result
        assert "### Section 1" in result
        assert "#### Subsection" in result
        assert "##### Deep section" in result
        # Original headings should not be present
        assert "\n# Main Title" not in result
