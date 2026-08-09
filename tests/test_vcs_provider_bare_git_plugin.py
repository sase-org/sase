"""Tests for the BareGit pluggy plugin.

Verifies that :class:`BareGitPlugin` works correctly when routed through
:class:`VCSPluginManager`.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pluggy
import pytest
from sase.vcs_provider._base import VCSProvider
from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider.plugins.bare_git import BareGitPlugin

_MOCK_TARGET = "sase.vcs_provider._command_runner.subprocess.run"


def _git_cmd_handler(stdout: str = "", *, push_rc: int = 0):  # type: ignore[no-untyped-def]
    """Return a ``subprocess.run`` side-effect for git-commit dispatch tests.

    ``git diff --cached --quiet`` returns non-zero (staged changes exist) and
    ``git show-ref --verify --quiet`` returns 1 (no remote branch → skip merge).
    """
    from typing import Any

    def handler(*args: Any, **kwargs: Any) -> MagicMock:
        cmd: list[str] = args[0] if args else kwargs.get("cmd", [])
        if isinstance(cmd, list):
            if "diff" in cmd and "--cached" in cmd and "--quiet" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="")
            if "show-ref" in cmd and "--verify" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="")
            if "push" in cmd:
                return MagicMock(
                    returncode=push_rc,
                    stdout="" if push_rc else stdout,
                    stderr="push rejected" if push_rc else "",
                )
        return MagicMock(returncode=0, stdout=stdout, stderr="")

    return handler


@pytest.fixture
def bare_git_provider() -> VCSPluginManager:
    """Create a VCSPluginManager backed by BareGitPlugin."""
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(BareGitPlugin())
    return VCSPluginManager(pm)


# === Tests for isinstance / type checks ===


def test_bare_git_plugin_is_command_runner() -> None:
    """BareGitPlugin inherits from CommandRunner."""
    plugin = BareGitPlugin()
    assert isinstance(plugin, CommandRunner)


# === Tests for core git operations via plugin ===


# === Tests for bare-git-specific operations ===


def test_plugin_get_change_url_returns_none(
    bare_git_provider: VCSPluginManager,
) -> None:
    """Bare git repos have no PR URL."""
    success, url = bare_git_provider.get_change_url("/workspace")

    assert success is True
    assert url is None


def test_plugin_get_pr_number_returns_none(
    bare_git_provider: VCSPluginManager,
) -> None:
    """Bare git repos have no PR number."""
    success, number = bare_git_provider.get_pr_number("/workspace")

    assert success is True
    assert number is None


@patch(_MOCK_TARGET)
def test_plugin_mail_push_failure(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """mail returns failure when push fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="push rejected")
    success, error = bare_git_provider.mail("feature-branch", "/workspace")

    assert success is False
    assert isinstance(error, str)


# === Tests for prepare_description_for_reword ===


# === Test registry integration ===


# === Tests for commit dispatch hooks ===


@patch(_MOCK_TARGET)
def test_vcs_create_commit_success(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """All git commands (add, validate, merge-skip, commit, push, rev-parse) succeed."""
    mock_run.side_effect = _git_cmd_handler(stdout="abc1234")
    ok, result = bare_git_provider.create_commit(
        {"message": "fix: bug", "files": ["a.py"]}, "/workspace"
    )

    assert ok is True
    assert result == "abc1234"


@patch(_MOCK_TARGET)
def test_vcs_create_commit_no_files_uses_add_all(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """Empty files list falls back to git add -A."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    bare_git_provider.create_commit({"message": "chore: sync", "files": []}, "/ws")

    add_call = mock_run.call_args_list[0]
    cmd = add_call[0][0]
    assert cmd == ["git", "add", "-A"]


@patch(_MOCK_TARGET)
def test_vcs_create_commit_stages_concrete_bead_files(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager, tmp_path: Path
) -> None:
    """Bead staging should add concrete changed files, not the whole bead dir."""
    cwd = tmp_path
    (cwd / "sdd" / "beads").mkdir(parents=True)
    bead_files = [
        "sdd/beads/issues.jsonl",
        "sdd/beads/events/streams/sase-1.jsonl",
    ]
    bead_stdout = "\0".join(bead_files) + "\0"

    def handler(*args: object, **kwargs: object) -> MagicMock:
        cmd = args[0] if args else kwargs.get("cmd", [])
        if isinstance(cmd, list):
            if cmd[:2] == ["git", "ls-files"]:
                return MagicMock(returncode=0, stdout=bead_stdout, stderr="")
            if cmd == ["git", "diff", "--cached", "--quiet"]:
                return MagicMock(returncode=1, stdout="", stderr="")
            if cmd[:3] == ["git", "symbolic-ref", "--short"]:
                return MagicMock(returncode=1, stdout="", stderr="")
            if cmd[:3] == ["git", "remote", "get-url"]:
                return MagicMock(returncode=1, stdout="", stderr="")
            if cmd[:3] == ["git", "rev-parse", "--short"]:
                return MagicMock(returncode=0, stdout="abc1234\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = handler

    ok, result = bare_git_provider.create_commit(
        {
            "message": "chore: sync beads",
            "files": ["src/main.py"],
            "bead_id": "sase-1",
        },
        str(cwd),
    )

    assert ok is True
    assert result == "abc1234"
    commands = [call[0][0] for call in mock_run.call_args_list]
    bead_add_calls = [
        cmd
        for cmd in commands
        if cmd[:3] == ["git", "add", "--"] and any("sdd/beads/" in p for p in cmd)
    ]
    assert bead_add_calls
    assert all(cmd == ["git", "add", "--", *bead_files] for cmd in bead_add_calls)
    assert ["git", "add", "sdd/beads/"] not in commands
    assert not any(cmd[:3] == ["git", "status", "--porcelain"] for cmd in commands)


@patch(_MOCK_TARGET)
def test_vcs_create_commit_does_not_write_bead_notes(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager, tmp_path: Path
) -> None:
    """Committing a bead-carrying change must preserve the bead's notes."""
    cwd = tmp_path
    (cwd / "sdd" / "beads").mkdir(parents=True)
    bead_stdout = "sdd/beads/issues.jsonl\0"

    def handler(*args: object, **kwargs: object) -> MagicMock:
        cmd = args[0] if args else kwargs.get("cmd", [])
        if isinstance(cmd, list):
            if cmd[:2] == ["git", "ls-files"]:
                return MagicMock(returncode=0, stdout=bead_stdout, stderr="")
            if cmd == ["git", "diff", "--cached", "--quiet"]:
                return MagicMock(returncode=1, stdout="", stderr="")
            if cmd[:3] == ["git", "symbolic-ref", "--short"]:
                return MagicMock(returncode=1, stdout="", stderr="")
            if cmd[:3] == ["git", "rev-parse", "--short"]:
                return MagicMock(returncode=0, stdout="abc1234\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = handler

    ok, result = bare_git_provider.create_commit(
        {
            "message": "fix: preserve bead notes",
            "files": ["src/main.py"],
            "bead_id": "sase-1",
        },
        str(cwd),
    )

    assert ok is True
    assert result == "abc1234"
    commands = [call[0][0] for call in mock_run.call_args_list]
    assert not any(cmd[:3] == ["sase", "bead", "update"] for cmd in commands)
    assert not any("--notes" in cmd for cmd in commands)


@patch(_MOCK_TARGET)
def test_vcs_finalize_commit_does_not_write_bead_notes(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager, tmp_path: Path
) -> None:
    """Resuming a bead-carrying commit must preserve the bead's notes."""
    cwd = tmp_path
    (cwd / "sdd" / "beads").mkdir(parents=True)

    def handler(*args: object, **kwargs: object) -> MagicMock:
        cmd = args[0] if args else kwargs.get("cmd", [])
        if isinstance(cmd, list):
            if cmd[:2] == ["git", "ls-files"]:
                return MagicMock(
                    returncode=0,
                    stdout="sdd/beads/issues.jsonl\0",
                    stderr="",
                )
            if cmd[:3] == ["git", "remote", "get-url"]:
                return MagicMock(returncode=1, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = handler

    ok, result = bare_git_provider.finalize_commit({"bead_id": "sase-1"}, str(cwd))

    assert ok is True
    assert result is None
    commands = [call[0][0] for call in mock_run.call_args_list]
    assert not any(cmd[:3] == ["sase", "bead", "update"] for cmd in commands)
    assert not any("--notes" in cmd for cmd in commands)


@patch(_MOCK_TARGET)
def test_vcs_finalize_commit_amends_straggler_bead_changes(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager, tmp_path: Path
) -> None:
    """Resume still folds bead-store changes into the existing commit."""
    cwd = tmp_path
    (cwd / "sdd" / "beads").mkdir(parents=True)
    bead_files = [
        "sdd/beads/issues.jsonl",
        "sdd/beads/events/streams/sase-1.jsonl",
    ]
    bead_stdout = "\0".join(bead_files) + "\0"

    def handler(*args: object, **kwargs: object) -> MagicMock:
        cmd = args[0] if args else kwargs.get("cmd", [])
        if isinstance(cmd, list):
            if cmd[:2] == ["git", "ls-files"]:
                return MagicMock(returncode=0, stdout=bead_stdout, stderr="")
            if cmd[:3] == ["git", "remote", "get-url"]:
                return MagicMock(returncode=1, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = handler

    ok, result = bare_git_provider.finalize_commit({"bead_id": "sase-1"}, str(cwd))

    assert ok is True
    assert result is None
    commands = [call[0][0] for call in mock_run.call_args_list]
    assert ["git", "add", "--", *bead_files] in commands
    assert ["git", "commit", "--amend", "--no-edit", "--quiet"] in commands


@patch(_MOCK_TARGET)
def test_vcs_create_commit_push_fails(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """Returns error tuple when push fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # git add
        MagicMock(returncode=0, stdout="", stderr=""),  # git commit
        MagicMock(returncode=1, stdout="", stderr="push rejected"),  # git push
    ]
    ok, err = bare_git_provider.create_commit({"message": "test", "files": []}, "/ws")

    assert ok is False
    assert isinstance(err, str)


@patch("sase.workflows.commit_utils.workspace.clean_workspace")
@patch(
    "sase.workflows.commit_utils.workspace.save_diff", return_value="~/diffs/test.diff"
)
def test_vcs_create_proposal_saves_diff(
    mock_save: MagicMock,
    mock_clean: MagicMock,
    bare_git_provider: VCSPluginManager,
) -> None:
    """create_proposal saves a diff and cleans workspace instead of committing."""
    ok, result = bare_git_provider.create_proposal(
        {"name": "my_cl", "message": "propose: change"}, "/ws"
    )

    assert ok is True
    assert result == "~/diffs/test.diff"
    mock_save.assert_called_once_with("my_cl", target_dir="/ws")
    mock_clean.assert_called_once_with("/ws")


@patch(_MOCK_TARGET)
def test_vcs_create_pull_request_creates_branch(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """create_pull_request creates a new branch, commits, and pushes."""
    mock_run.side_effect = _git_cmd_handler()
    ok, err = bare_git_provider.create_pull_request(
        {"name": "feat-x", "message": "add feature", "files": []}, "/ws"
    )

    assert ok is True
    checkout_call = mock_run.call_args_list[0]
    cmd = checkout_call[0][0]
    assert cmd == ["git", "checkout", "-b", "feat-x"]


@patch(_MOCK_TARGET)
def test_vcs_create_pull_request_push_fails(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """Returns error when push fails for a reason other than a branch collision."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # checkout -b
        MagicMock(returncode=0, stdout="", stderr=""),  # add
        MagicMock(returncode=0, stdout="", stderr=""),  # commit
        MagicMock(returncode=0, stdout="", stderr=""),  # remote get-url (push retry)
        MagicMock(returncode=1, stdout="", stderr="push failed"),  # push
        MagicMock(returncode=1, stdout="", stderr=""),  # pull --no-edit
        MagicMock(returncode=0, stdout="", stderr=""),  # merge --abort
        MagicMock(returncode=0, stdout="", stderr=""),  # ls-remote: branch absent
    ]
    ok, err = bare_git_provider.create_pull_request(
        {"name": "feat-x", "message": "test", "files": []}, "/ws"
    )

    assert ok is False
    assert isinstance(err, str)


@patch(_MOCK_TARGET)
def test_vcs_create_pull_request_resuffixes_on_branch_collision(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """A branch already on the remote triggers a rename to the next free suffix.

    Regression for the orphaned-PR bug: when the reserved branch ``feat_2``
    races with a concurrent push, the dispatch must re-suffix to ``feat_3`` and
    push successfully (so the workflow still records a Patch) rather than
    failing and leaving the agent to hand-roll an orphaned PR.
    """
    from typing import Any

    def handler(*args: Any, **kwargs: Any) -> MagicMock:
        cmd: list[str] = args[0] if args else kwargs.get("cmd", [])
        if "diff" in cmd and "--cached" in cmd and "--quiet" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="")  # staged changes
        if cmd[:2] == ["git", "push"]:
            # The original reserved branch collides; the re-suffixed one wins.
            if "feat_2" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="rejected")
            return MagicMock(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["git", "pull"]:
            return MagicMock(returncode=1, stdout="", stderr="unrelated histories")
        if cmd[:2] == ["git", "ls-remote"]:
            # _remote_branch_exists("feat_2") -> exists (collision confirmed).
            if "feat_2" in cmd:
                return MagicMock(
                    returncode=0,
                    stdout="sha\trefs/heads/feat_2\n",
                    stderr="",
                )
            # Suffix scan over feat_* -> remote namespace is dense {1, 2},
            # so the next free suffix is 3.
            if "feat_*" in cmd:
                return MagicMock(
                    returncode=0,
                    stdout="sha1\trefs/heads/feat_1\nsha2\trefs/heads/feat_2\n",
                    stderr="",
                )
            return MagicMock(returncode=0, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = handler

    payload = {"name": "feat_2", "message": "test", "files": []}
    ok, err = bare_git_provider.create_pull_request(payload, "/ws")

    assert ok is True
    assert payload["name"] == "feat_3"
    assert payload["_resuffixed"] is True
    # The rename targeted the next free suffix.
    rename_calls = [
        c[0][0]
        for c in mock_run.call_args_list
        if c[0][0][:3] == ["git", "branch", "-m"]
    ]
    assert rename_calls == [["git", "branch", "-m", "feat_3"]]


# === Test registry integration ===


@patch("sase.vcs_provider._registry._resolve_vcs_name", return_value="bare_git")
def test_registry_routes_bare_git_through_plugin(mock_resolve: MagicMock) -> None:
    """get_vcs_provider returns a VCSPluginManager for bare_git."""
    from sase.vcs_provider._registry import get_vcs_provider

    provider = get_vcs_provider("/workspace")
    assert isinstance(provider, VCSPluginManager)
    assert isinstance(provider, VCSProvider)
