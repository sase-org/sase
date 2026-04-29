"""Golden tests pinning the Git query parser facade contract.

The Phase 5B contract guarantees that
:mod:`sase.core.git_query_facade` produces the exact strings exercised
here. The Phase 5C Rust implementations must match byte-for-byte,
including the rename/copy ``"<old>\\t<new>"`` encoding, the detached-HEAD
sentinel handling, and the workspace-name remote-vs-root priority.
"""

from __future__ import annotations

from sase.core.git_query_facade import (
    derive_git_workspace_name,
    parse_git_branch_name,
    parse_git_conflicted_files,
    parse_git_local_changes,
    parse_git_name_status_z,
)
from sase.core.git_query_wire import (
    GIT_QUERY_WIRE_SCHEMA_VERSION,
    GitNameStatusEntryWire,
    git_name_status_entry_from_dict,
    git_query_wire_to_json_dict,
)

# ---------------------------------------------------------------------------
# parse_git_name_status_z
# ---------------------------------------------------------------------------


def test_parse_name_status_empty_stream_returns_empty_list() -> None:
    assert parse_git_name_status_z("") == []


def test_parse_name_status_trailing_nul_is_ignored() -> None:
    # Real ``git diff -z`` output terminates every field with a NUL,
    # leaving an empty trailing token after split.
    stream = "M\0src/a.py\0"
    assert parse_git_name_status_z(stream) == [("M", "src/a.py")]


def test_parse_name_status_simple_status_letters() -> None:
    stream = "A\0added.py\0M\0modified.py\0D\0deleted.py\0T\0type_changed.py\0U\0conflicted.py\0"
    assert parse_git_name_status_z(stream) == [
        ("A", "added.py"),
        ("M", "modified.py"),
        ("D", "deleted.py"),
        ("T", "type_changed.py"),
        ("U", "conflicted.py"),
    ]


def test_parse_name_status_rename_with_score_carries_paired_paths() -> None:
    stream = "R100\0old_name.py\0new_name.py\0"
    assert parse_git_name_status_z(stream) == [("R100", "old_name.py\tnew_name.py")]


def test_parse_name_status_copy_with_score_carries_paired_paths() -> None:
    stream = "C75\0src/orig.py\0src/copy.py\0"
    assert parse_git_name_status_z(stream) == [("C75", "src/orig.py\tsrc/copy.py")]


def test_parse_name_status_mixed_simple_and_rename_in_one_stream() -> None:
    stream = "M\0a.py\0R100\0b_old.py\0b_new.py\0D\0c.py\0"
    assert parse_git_name_status_z(stream) == [
        ("M", "a.py"),
        ("R100", "b_old.py\tb_new.py"),
        ("D", "c.py"),
    ]


def test_parse_name_status_truncated_status_only_drops_entry() -> None:
    """A trailing status with no following path is silently dropped."""
    # Status ``M`` with no path field — the current Python parser
    # tolerates this and skips the entry.
    stream = "M\0a.py\0M"
    assert parse_git_name_status_z(stream) == [("M", "a.py")]


def test_parse_name_status_truncated_rename_falls_back_to_single_path() -> None:
    """A trailing rename with only one path field degrades to a single-path entry.

    The current Python parser checks for two paths (``i + 1 < len(parts)``)
    and, when that fails, falls through to the single-path branch
    (``i < len(parts)``) so the rename is recorded with just the
    available path. Rust must preserve this behavior — flagged in
    Phase 5A as forgiving rather than buggy.
    """
    stream = "M\0a.py\0R100\0only_one_path.py"
    assert parse_git_name_status_z(stream) == [
        ("M", "a.py"),
        ("R100", "only_one_path.py"),
    ]


def test_parse_name_status_skips_empty_status_tokens() -> None:
    """Stray empty fields between entries are skipped."""
    stream = "\0M\0a.py\0"
    assert parse_git_name_status_z(stream) == [("M", "a.py")]


# ---------------------------------------------------------------------------
# parse_git_branch_name
# ---------------------------------------------------------------------------


def test_parse_branch_name_simple_value() -> None:
    assert parse_git_branch_name("feature-x\n") == "feature-x"


def test_parse_branch_name_detached_head_returns_none() -> None:
    assert parse_git_branch_name("HEAD\n") is None


def test_parse_branch_name_empty_stdout_returns_none() -> None:
    assert parse_git_branch_name("") is None


def test_parse_branch_name_whitespace_only_returns_none() -> None:
    assert parse_git_branch_name("   \n") is None


def test_parse_branch_name_strips_surrounding_whitespace() -> None:
    assert parse_git_branch_name("  feature-x  \n") == "feature-x"


# ---------------------------------------------------------------------------
# derive_git_workspace_name
# ---------------------------------------------------------------------------


def test_derive_workspace_name_https_remote_with_dot_git_suffix() -> None:
    assert (
        derive_git_workspace_name("https://github.com/sase-org/sase_100.git", None)
        == "sase_100"
    )


def test_derive_workspace_name_https_remote_without_dot_git_suffix() -> None:
    assert (
        derive_git_workspace_name("https://github.com/sase-org/sase_100", None)
        == "sase_100"
    )


def test_derive_workspace_name_ssh_remote_with_dot_git_suffix() -> None:
    assert (
        derive_git_workspace_name("git@github.com:sase-org/sase_100.git", None)
        == "sase_100"
    )


def test_derive_workspace_name_path_like_remote() -> None:
    assert derive_git_workspace_name("/srv/git/sase_100.git", None) == "sase_100"


def test_derive_workspace_name_falls_back_to_root_path_when_remote_blank() -> None:
    assert derive_git_workspace_name("", "/home/user/projects/sase_100") == "sase_100"


def test_derive_workspace_name_falls_back_to_root_path_when_remote_none() -> None:
    assert derive_git_workspace_name(None, "/home/user/projects/sase_100") == "sase_100"


def test_derive_workspace_name_remote_takes_priority_over_root() -> None:
    assert (
        derive_git_workspace_name(
            "https://github.com/sase-org/repo_a.git", "/tmp/repo_b"
        )
        == "repo_a"
    )


def test_derive_workspace_name_returns_none_when_both_inputs_empty() -> None:
    assert derive_git_workspace_name(None, None) is None
    assert derive_git_workspace_name("", "") is None


def test_derive_workspace_name_remote_dot_git_only_returns_none() -> None:
    """A remote URL of just ``.git`` strips to empty; fall through to root."""
    assert derive_git_workspace_name(".git", "/tmp/fallback") is None


# ---------------------------------------------------------------------------
# parse_git_conflicted_files
# ---------------------------------------------------------------------------


def test_parse_conflicted_files_empty_stdout_returns_empty_list() -> None:
    assert parse_git_conflicted_files("") == []


def test_parse_conflicted_files_strips_blank_lines() -> None:
    stdout = "src/a.py\n\nsrc/b.py\n\n"
    assert parse_git_conflicted_files(stdout) == ["src/a.py", "src/b.py"]


def test_parse_conflicted_files_preserves_path_order() -> None:
    stdout = "z.py\na.py\nm.py\n"
    assert parse_git_conflicted_files(stdout) == ["z.py", "a.py", "m.py"]


def test_parse_conflicted_files_only_blank_lines_returns_empty() -> None:
    assert parse_git_conflicted_files("\n\n   \n") == []


# ---------------------------------------------------------------------------
# parse_git_local_changes
# ---------------------------------------------------------------------------


def test_parse_local_changes_clean_tree_returns_none() -> None:
    assert parse_git_local_changes("") is None


def test_parse_local_changes_whitespace_only_returns_none() -> None:
    assert parse_git_local_changes("   \n") is None


def test_parse_local_changes_dirty_tree_returns_stripped_text() -> None:
    """Whitespace at both ends is stripped; interior content is preserved verbatim."""
    stdout = "M src/a.py\n?? new.py\n"
    assert parse_git_local_changes(stdout) == "M src/a.py\n?? new.py"


# ---------------------------------------------------------------------------
# Wire helpers
# ---------------------------------------------------------------------------


def test_git_query_wire_schema_version_is_one() -> None:
    assert GIT_QUERY_WIRE_SCHEMA_VERSION == 1


def test_git_query_wire_to_json_dict_round_trip_for_entry() -> None:
    entry = GitNameStatusEntryWire(status="R100", path="old.py\tnew.py")
    payload = git_query_wire_to_json_dict(entry)
    assert payload == {"status": "R100", "path": "old.py\tnew.py"}
    assert git_name_status_entry_from_dict(payload) == entry


def test_git_query_wire_to_json_dict_handles_lists() -> None:
    entries = [
        GitNameStatusEntryWire(status="A", path="a.py"),
        GitNameStatusEntryWire(status="M", path="b.py"),
    ]
    payload = git_query_wire_to_json_dict(entries)
    assert payload == [
        {"status": "A", "path": "a.py"},
        {"status": "M", "path": "b.py"},
    ]
