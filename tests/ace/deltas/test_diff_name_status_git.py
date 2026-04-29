"""Integration test for the bare-git ``diff_name_status`` hookimpl.

Exercises :class:`BareGitPlugin.vcs_diff_name_status` against a real
temporary git repository covering all status letters compute_deltas
cares about: A, M, D, and R (rename).
"""

import shutil
import subprocess
from pathlib import Path

import pluggy
import pytest

from sase.vcs_provider import VCSOperationError
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.core.git_query_facade import parse_git_name_status_z
from sase.vcs_provider.plugins.bare_git import BareGitPlugin

_GIT_AVAILABLE = shutil.which("git") is not None

pytestmark = [
    pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available"),
    pytest.mark.usefixtures("python_core_backend"),
]


def _make_git_provider() -> VCSPluginManager:
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(BareGitPlugin())
    return VCSPluginManager(pm)


def _git(args: list[str], cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)


@pytest.fixture()
def repo(tmp_path: Path) -> str:
    """Repo with one initial commit on the default branch."""
    cwd = str(tmp_path)
    _git(["init", "-q", "-b", "main"], cwd)
    _git(["config", "user.email", "t@t"], cwd)
    _git(["config", "user.name", "T"], cwd)
    _git(["config", "commit.gpgsign", "false"], cwd)
    (tmp_path / "README.md").write_text("# repo\n")
    _git(["add", "README.md"], cwd)
    _git(["commit", "-m", "init"], cwd)
    return cwd


def test_diff_name_status_added_modified_deleted(repo: str) -> None:
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    # Modify README, add a new file, delete nothing-to-delete (so we add+delete)
    (Path(repo) / "README.md").write_text("# changed\n")
    (Path(repo) / "newfile.py").write_text("print('hi')\n")
    (Path(repo) / "to_delete.txt").write_text("doomed\n")
    _git(["add", "."], repo)
    _git(["commit", "-m", "stage1"], repo)
    _git(["rm", "to_delete.txt"], repo)
    _git(["commit", "-m", "delete it"], repo)

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    provider = _make_git_provider()
    raw = provider.diff_name_status(base, head, repo)

    by_path = {path: status for status, path in raw}
    assert by_path["README.md"] == "M"
    assert by_path["newfile.py"] == "A"
    # to_delete.txt was added then removed: net is no entry.
    assert "to_delete.txt" not in by_path


def test_diff_name_status_rename_returns_paired_paths(repo: str) -> None:
    (Path(repo) / "old_name.py").write_text("x = 1\n")
    _git(["add", "old_name.py"], repo)
    _git(["commit", "-m", "add file"], repo)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    _git(["mv", "old_name.py", "new_name.py"], repo)
    _git(["commit", "-m", "rename"], repo)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    provider = _make_git_provider()
    raw = provider.diff_name_status(base, head, repo)

    # Without rename detection, git emits an A + D pair; with detection it
    # emits a single R<score> with both paths.  Either is acceptable — the
    # apply_status_mapping helper tests cover both shapes.
    statuses = {s[0] for s, _ in raw}
    if "R" in statuses:
        rename = next(((s, p) for s, p in raw if s.startswith("R")))
        old, _, new = rename[1].partition("\t")
        assert old == "old_name.py"
        assert new == "new_name.py"
    else:
        paths = {p: s for s, p in raw}
        assert paths.get("old_name.py") == "D"
        assert paths.get("new_name.py") == "A"


def test_diff_name_status_invalid_ref_raises_typed_error(repo: str) -> None:
    provider = _make_git_provider()
    with pytest.raises(VCSOperationError) as exc:
        provider.diff_name_status("HEAD", "no-such-ref-xyz", repo)
    assert exc.value.operation == "diff_name_status"


def test_parse_git_name_status_z_handles_renames_and_simple_entries() -> None:
    # status\0path\0  for simple entries; status\0old\0new\0 for renames.
    raw = "M\0a.py\0R100\0old.py\0new.py\0A\0b.py\0"
    parsed = parse_git_name_status_z(raw)
    assert parsed == [
        ("M", "a.py"),
        ("R100", "old.py\tnew.py"),
        ("A", "b.py"),
    ]


def test_parse_git_name_status_z_empty() -> None:
    assert parse_git_name_status_z("") == []
