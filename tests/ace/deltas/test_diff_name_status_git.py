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

from sase.ace.changespec.models import ChangeSpec, DeltaEntry, DeltaLineStats
from sase.ace.deltas import compute_deltas
from sase.core.git_query_facade import parse_git_name_status_z, parse_git_numstat_z
from sase.vcs_provider import VCSOperationError
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider.plugins.bare_git import BareGitPlugin

_GIT_AVAILABLE = shutil.which("git") is not None

pytestmark = pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")


def _make_git_provider() -> VCSPluginManager:
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(BareGitPlugin())
    return VCSPluginManager(pm)


def _git(args: list[str], cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)


def _rev_parse(revision: str, cwd: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", revision],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


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
    base = _rev_parse("HEAD", repo)

    # Modify README, add a new file, delete nothing-to-delete (so we add+delete)
    (Path(repo) / "README.md").write_text("# changed\n")
    (Path(repo) / "newfile.py").write_text("print('hi')\n")
    (Path(repo) / "to_delete.txt").write_text("doomed\n")
    _git(["add", "."], repo)
    _git(["commit", "-m", "stage1"], repo)
    _git(["rm", "to_delete.txt"], repo)
    _git(["commit", "-m", "delete it"], repo)

    head = _rev_parse("HEAD", repo)

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
    base = _rev_parse("HEAD", repo)

    _git(["mv", "old_name.py", "new_name.py"], repo)
    _git(["commit", "-m", "rename"], repo)
    head = _rev_parse("HEAD", repo)

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


def test_diff_line_stats_added_modified_deleted(repo: str) -> None:
    base = _rev_parse("HEAD", repo)

    (Path(repo) / "README.md").write_text("# repo\nchanged\n")
    (Path(repo) / "newfile.py").write_text("print('hi')\n")
    (Path(repo) / "gone.txt").write_text("doomed\n")
    _git(["add", "."], repo)
    _git(["commit", "-m", "stage1"], repo)
    _git(["rm", "gone.txt"], repo)
    _git(["commit", "-m", "delete"], repo)

    head = _rev_parse("HEAD", repo)

    provider = _make_git_provider()
    raw = provider.diff_line_stats(base, head, repo)

    by_path = {path: (added, removed) for added, removed, path in raw}
    assert by_path["README.md"] == ("1", "0")
    assert by_path["newfile.py"] == ("1", "0")
    assert "gone.txt" not in by_path


def test_diff_name_status_uses_merge_base_when_base_advances(repo: str) -> None:
    _git(["checkout", "-b", "feature"], repo)
    (Path(repo) / "branch_only.py").write_text("branch\n")
    _git(["add", "branch_only.py"], repo)
    _git(["commit", "-m", "branch change"], repo)

    _git(["checkout", "main"], repo)
    (Path(repo) / "base_only.py").write_text("base\n")
    _git(["add", "base_only.py"], repo)
    _git(["commit", "-m", "base change"], repo)

    provider = _make_git_provider()
    raw = provider.diff_name_status("main", "feature", repo)

    by_path = {path: status for status, path in raw}
    assert by_path == {"branch_only.py": "A"}


def test_diff_line_stats_uses_same_merge_base_range(repo: str) -> None:
    _git(["checkout", "-b", "feature"], repo)
    (Path(repo) / "branch_only.py").write_text("branch\nmore branch\n")
    _git(["add", "branch_only.py"], repo)
    _git(["commit", "-m", "branch change"], repo)

    _git(["checkout", "main"], repo)
    (Path(repo) / "base_only.py").write_text("base\n")
    _git(["add", "base_only.py"], repo)
    _git(["commit", "-m", "base change"], repo)

    provider = _make_git_provider()
    raw = provider.diff_line_stats("main", "feature", repo)

    by_path = {path: (added, removed) for added, removed, path in raw}
    assert by_path == {"branch_only.py": ("2", "0")}


def test_compute_deltas_reports_cumulative_pr_state(repo: str, tmp_path: Path) -> None:
    _git(["update-ref", "refs/remotes/origin/main", "HEAD"], repo)
    _git(["checkout", "-b", "feature"], repo)
    (Path(repo) / "a.py").write_text("print('a')\n")
    _git(["add", "a.py"], repo)
    _git(["commit", "-m", "add a"], repo)
    (Path(repo) / "b.py").write_text("one\ntwo\n")
    _git(["add", "b.py"], repo)
    _git(["commit", "-m", "add b"], repo)

    project_file = tmp_path / "myproject.gp"
    changespec = ChangeSpec(
        name="feature",
        description="x",
        parent=None,
        cl=None,
        status="Draft",
        test_targets=None,
        kickstart=None,
        file_path=str(project_file),
        line_number=1,
    )

    result = compute_deltas(changespec, _make_git_provider(), repo)

    assert result == [
        DeltaEntry(
            path="a.py",
            change_type="A",
            line_stats=DeltaLineStats(added=1),
        ),
        DeltaEntry(
            path="b.py",
            change_type="A",
            line_stats=DeltaLineStats(added=2),
        ),
    ]


def test_resolve_current_changespec_head_ref_prefers_fetched_remote(
    tmp_path: Path,
) -> None:
    origin = tmp_path / "origin.git"
    source = tmp_path / "source"
    observer = tmp_path / "observer"

    _git(["init", "-q", "--bare", str(origin)], str(tmp_path))
    source.mkdir()
    _git(["init", "-q", "-b", "main"], str(source))
    _git(["config", "user.email", "t@t"], str(source))
    _git(["config", "user.name", "T"], str(source))
    _git(["config", "commit.gpgsign", "false"], str(source))
    (source / "README.md").write_text("# repo\n")
    _git(["add", "README.md"], str(source))
    _git(["commit", "-m", "init"], str(source))
    _git(["remote", "add", "origin", str(origin)], str(source))
    _git(["push", "-u", "origin", "main"], str(source))
    _git(["checkout", "-b", "feature"], str(source))
    (source / "old.py").write_text("old\n")
    _git(["add", "old.py"], str(source))
    _git(["commit", "-m", "old feature"], str(source))
    _git(["push", "-u", "origin", "feature"], str(source))

    subprocess.run(
        ["git", "clone", "-q", str(origin), str(observer)],
        capture_output=True,
        check=True,
    )
    _git(["checkout", "feature"], str(observer))
    _git(["checkout", "main"], str(observer))

    (source / "new.py").write_text("new\n")
    _git(["add", "new.py"], str(source))
    _git(["commit", "-m", "new feature"], str(source))
    _git(["push"], str(source))

    provider = _make_git_provider()
    head_ref = provider.resolve_current_changespec_head_ref(
        "feature", "myproject", str(observer)
    )

    assert head_ref == "origin/feature"
    raw = provider.diff_name_status("origin/main", head_ref, str(observer))
    assert {path for _, path in raw} == {"new.py", "old.py"}


def test_diff_line_stats_invalid_ref_raises_typed_error(repo: str) -> None:
    provider = _make_git_provider()
    with pytest.raises(VCSOperationError) as exc:
        provider.diff_line_stats("HEAD", "no-such-ref-xyz", repo)
    assert exc.value.operation == "diff_line_stats"


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


def test_parse_git_numstat_z_handles_renames_and_simple_entries() -> None:
    raw = "\0".join(["1\t0\ta.py", "0\t0\t", "old.py", "new.py", "-\t-\timage.bin", ""])
    parsed = parse_git_numstat_z(raw)
    assert parsed == [
        ("1", "0", "a.py"),
        ("0", "0", "new.py"),
        ("-", "-", "image.bin"),
    ]
