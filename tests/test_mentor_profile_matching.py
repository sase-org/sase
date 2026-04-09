"""Tests for the mentor_profile_matching module."""

from typing import Any
from unittest.mock import MagicMock

from sase.ace.changespec import (
    CommitEntry,
    MentorEntry,
)
from sase.ace.scheduler.mentor_profile_matching import (
    _extract_changed_files_from_diff,
    _get_commits_since_last_mentors,
    _get_matching_profiles_for_entry,
    get_profiles_registered_for_entry,
    profile_matches_any_commit,
)
from sase.config.mentor import MentorProfileConfig
from test_utils import build_changespec, make_mentor_config


# Tests for _extract_changed_files_from_diff


def test_extract_changed_files_from_diff_git_format() -> None:
    """Test extracting files from git diff format."""
    diff_content = """diff --git a/src/main.py b/src/main.py
index 123456..789abc 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
 def main():
     pass
+    return 0
diff --git a/tests/test_main.py b/tests/test_main.py
index aaaaaa..bbbbbb 100644
--- a/tests/test_main.py
+++ b/tests/test_main.py
@@ -1 +1,2 @@
 def test_main(): pass
+def test_other(): pass
"""
    files = _extract_changed_files_from_diff(diff_content)
    assert files == ["src/main.py", "tests/test_main.py"]


def test_extract_changed_files_from_diff_hg_format() -> None:
    """Test extracting files from hg diff format."""
    diff_content = """diff -r abc123 src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
 def main():
     pass
+    return 0
diff -r abc123 tests/test_main.py
--- a/tests/test_main.py
+++ b/tests/test_main.py
@@ -1 +1,2 @@
 def test_main(): pass
"""
    files = _extract_changed_files_from_diff(diff_content)
    assert files == ["src/main.py", "tests/test_main.py"]


def test_extract_changed_files_from_diff_hg_changeset_format() -> None:
    """Test extracting files from hg changeset diff format (double -r)."""
    diff_content = """diff -r abc123 -r def456 src/main.dart
--- a/src/main.dart
+++ b/src/main.dart
@@ -1,3 +1,4 @@
 void main() {
+  print('hello');
 }
diff -r abc123 -r def456 tests/main_test.dart
--- a/tests/main_test.dart
+++ b/tests/main_test.dart
@@ -1 +1,2 @@
 void testMain() {}
+void testOther() {}
"""
    files = _extract_changed_files_from_diff(diff_content)
    assert files == ["src/main.dart", "tests/main_test.dart"]


def test_extract_changed_files_from_diff_hg_non_hex_revision_tokens() -> None:
    """Test hg diff parsing with non-hex revision tokens."""
    diff_content = """diff -r 123:ABCDEF+ -r tip src/feature.py
--- a/src/feature.py
+++ b/src/feature.py
@@ -1 +1,2 @@
 def feature(): pass
+def other(): pass
diff -r 123:ABCDEF+ -r tip tests/test_feature.py
--- a/tests/test_feature.py
+++ b/tests/test_feature.py
@@ -1 +1,2 @@
 def test_feature(): pass
+def test_other(): pass
"""
    files = _extract_changed_files_from_diff(diff_content)
    assert files == ["src/feature.py", "tests/test_feature.py"]


# Tests for _get_commits_since_last_mentors


def test_get_commits_since_last_mentors_excludes_earlier() -> None:
    """Test that commits before last mentor entry are excluded."""
    cs = build_changespec(
        commits=[
            CommitEntry(number=1, note="First"),
            CommitEntry(number=2, note="Second"),
            CommitEntry(number=3, note="Third"),
        ],
        mentors=[
            MentorEntry(entry_id="2", profiles=["code"], status_lines=None),
        ],
    )
    result = _get_commits_since_last_mentors(cs)
    # Should include commits 2 and 3, exclude commit 1
    assert len(result) == 2
    assert result[0].display_number == "2"
    assert result[1].display_number == "3"


def test_get_commits_since_last_mentors_skips_proposals() -> None:
    """Test that proposals (entries like 1a, 2b) are skipped."""
    cs = build_changespec(
        commits=[
            CommitEntry(number=1, note="First"),
            CommitEntry(number=1, proposal_letter="a", note="Fix from hook"),
            CommitEntry(number=1, proposal_letter="b", note="Another fix"),
        ],
        mentors=None,
    )
    result = _get_commits_since_last_mentors(cs)
    # Should only include commit 1, not 1a or 1b
    assert len(result) == 1
    assert result[0].display_number == "1"


def test_get_commits_since_last_mentors_no_commits() -> None:
    """Test with no commits returns empty list."""
    cs = build_changespec(commits=None)
    result = _get_commits_since_last_mentors(cs)
    assert result == []


# Tests for get_profiles_registered_for_entry


def testget_profiles_registered_for_entry_no_mentors() -> None:
    """Test with no MENTORS returns empty set."""
    cs = build_changespec(mentors=None)
    result = get_profiles_registered_for_entry(cs, "1")
    assert result == set()


# Tests for _get_matching_profiles_for_entry


def test_get_matching_profiles_for_entry_excludes_old_mentored_commits(
    monkeypatch: Any,
) -> None:
    """Test that commits with existing MENTORS entries don't trigger new profiles.

    This is a regression test for the bug where old commits (e.g., commit 3 with
    note "[mentor:complete]") would trigger the feature profile to be added to
    a newer entry (e.g., entry 5) even though commits 4 and 5 don't match.
    """
    # Create a mock profile that matches "[mentor:complete]" in amend note
    mock_profile = MagicMock()
    mock_profile.profile_name = "feature"
    mock_profile.mentors = [make_mentor_config(mentor_name="complete")]
    mock_profile.file_globs = []
    mock_profile.diff_regexes = []
    mock_profile.amend_note_regexes = [r"\[mentor:complete\]"]
    mock_profile.projects = None

    # Mock get_all_mentor_profiles to return our test profile
    monkeypatch.setattr(
        "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
        lambda: [mock_profile],
    )

    # Scenario: commits 3, 4, 5 exist, MENTORS entry for 3 exists
    # Commit 3 has note that matches "[mentor:complete]"
    # Commits 4 and 5 do NOT match
    cs = build_changespec(
        commits=[
            CommitEntry(number=3, note="[mentor:complete] Added feature"),
            CommitEntry(number=4, note="[fix-hook] Fixed lint"),
            CommitEntry(number=5, note="[mentor:vision] Reduced visibility"),
        ],
        mentors=[
            MentorEntry(entry_id="3", profiles=["code", "feature"], status_lines=None),
        ],
    )

    # The bug: without the fix, commit 3 would be included in commits_to_check
    # and the feature profile would match (due to "[mentor:complete]" in note)
    # The fix: commit 3 should be excluded because it has a MENTORS entry
    result = _get_matching_profiles_for_entry(cs)

    # Should return empty - only commits 4 and 5 are checked, neither matches
    assert result == []


def test_get_matching_profiles_for_entry_includes_latest_with_partial_coverage(
    monkeypatch: Any,
) -> None:
    """Test that latest commit with partial coverage is still checked.

    This ensures the fix from fe712c83 still works - we should still detect
    additional profiles for the current commit even if it has a MENTORS entry.
    """
    # Create two mock profiles
    mock_profile_code = MagicMock()
    mock_profile_code.profile_name = "code"
    mock_profile_code.mentors = [make_mentor_config(mentor_name="vision")]
    mock_profile_code.file_globs = []
    mock_profile_code.diff_regexes = []
    mock_profile_code.amend_note_regexes = [r"Initial Commit"]
    mock_profile_code.projects = None

    mock_profile_feature = MagicMock()
    mock_profile_feature.profile_name = "feature"
    mock_profile_feature.mentors = [make_mentor_config(mentor_name="complete")]
    mock_profile_feature.file_globs = []
    mock_profile_feature.diff_regexes = []
    mock_profile_feature.amend_note_regexes = [r"Initial Commit"]
    mock_profile_feature.projects = None

    monkeypatch.setattr(
        "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
        lambda: [mock_profile_code, mock_profile_feature],
    )

    # Scenario: single commit 1 with "Initial Commit" note
    # MENTORS entry exists with only "code" profile (partial coverage)
    # "feature" profile should still be detected
    cs = build_changespec(
        commits=[
            CommitEntry(number=1, note="Initial Commit"),
        ],
        mentors=[
            MentorEntry(entry_id="1", profiles=["code"], status_lines=None),
        ],
    )

    result = _get_matching_profiles_for_entry(cs)

    # Should return feature profile - commit 1 is latest so still checked
    assert len(result) == 1
    assert result[0][0] == "1"  # entry_id
    assert result[0][1].profile_name == "feature"  # profile


def test_get_matching_profiles_for_entry_falls_back_to_vcs_diff(
    monkeypatch: Any,
) -> None:
    """Test missing DIFF file still matches via VCS fallback for latest commit."""
    mock_profile = MagicMock()
    mock_profile.profile_name = "code"
    mock_profile.mentors = [make_mentor_config(mentor_name="vision")]
    mock_profile.file_globs = None
    mock_profile.diff_regexes = [r"YieldParameterDtoConverter"]
    mock_profile.amend_note_regexes = None
    mock_profile.projects = None
    mock_profile.first_commit = False

    mock_provider = MagicMock()
    mock_provider.resolve_revision.return_value = "resolved-rev"
    mock_provider.diff_revision.return_value = (
        True,
        "diff --git a/src/a.py b/src/a.py\n+YieldParameterDtoConverter\n",
    )

    monkeypatch.setattr(
        "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
        lambda: [mock_profile],
    )
    monkeypatch.setattr(
        "sase.ace.scheduler.mentor_profile_matching.get_workspace_directory",
        lambda _project, _workspace_num=1: "/tmp/ws",
    )
    monkeypatch.setattr(
        "sase.ace.scheduler.mentor_profile_matching.get_vcs_provider",
        lambda _cwd: mock_provider,
    )

    cs = build_changespec(
        file_path="/home/user/.sase/projects/sase/sase.gp",
        commits=[
            CommitEntry(
                number=1,
                note="Initial commit",
                diff="~/.sase/diffs/does-not-exist.diff",
            ),
        ],
    )

    result = _get_matching_profiles_for_entry(cs)

    assert len(result) == 1
    assert result[0][0] == "1"
    assert result[0][1].profile_name == "code"
    mock_provider.diff_revision.assert_called_once_with("resolved-rev", "/tmp/ws")


def test_profile_fallback_applies_only_to_latest_commit(monkeypatch: Any) -> None:
    """Test VCS fallback is not applied to older commits in the candidate set."""
    profile = MentorProfileConfig(
        profile_name="feature",
        mentors=[make_mentor_config(mentor_name="complete")],
        diff_regexes=[r"legacy-only-token"],
    )

    mock_provider = MagicMock()
    mock_provider.resolve_revision.return_value = "resolved-rev"
    mock_provider.diff_revision.return_value = (
        True,
        "diff --git a/src/new.py b/src/new.py\n+modern-token\n",
    )

    monkeypatch.setattr(
        "sase.ace.scheduler.mentor_profile_matching.get_workspace_directory",
        lambda _project, _workspace_num=1: "/tmp/ws",
    )
    monkeypatch.setattr(
        "sase.ace.scheduler.mentor_profile_matching.get_vcs_provider",
        lambda _cwd: mock_provider,
    )

    cs = build_changespec(
        file_path="/home/user/.sase/projects/sase/sase.gp",
    )
    commits = [
        CommitEntry(number=1, note="old", diff="~/.sase/diffs/missing-old.diff"),
        CommitEntry(number=2, note="latest", diff="~/.sase/diffs/missing-new.diff"),
    ]

    matched = profile_matches_any_commit(profile, commits, cs)

    assert matched is False
    mock_provider.diff_revision.assert_called_once_with("resolved-rev", "/tmp/ws")


# Tests for first_commit matching


def test_first_commit_matches_on_commit_1() -> None:
    """Test that first_commit profile matches when commit 1 is in the list."""
    profile = MentorProfileConfig(
        profile_name="complete",
        mentors=[make_mentor_config(mentor_name="complete")],
        first_commit=True,
        amend_note_regexes=[r"\[mentor:complete\]"],
    )
    commits = [CommitEntry(number=1, note="Initial commit")]
    assert profile_matches_any_commit(profile, commits) is True


def test_first_commit_does_not_match_on_later_commits() -> None:
    """Test that first_commit profile does NOT match when commit 1 is filtered out."""
    profile = MentorProfileConfig(
        profile_name="complete",
        mentors=[make_mentor_config(mentor_name="complete")],
        first_commit=True,
        amend_note_regexes=[r"\[mentor:complete\]"],
    )
    # Only later commits remain (commit 1 already has MENTORS entry, filtered out)
    commits = [
        CommitEntry(number=2, note="Second commit"),
        CommitEntry(number=3, note="Third commit"),
    ]
    assert profile_matches_any_commit(profile, commits) is False


def test_first_commit_matches_later_via_amend_note_regexes() -> None:
    """Test that first_commit profile matches later commits via amend_note_regexes."""
    profile = MentorProfileConfig(
        profile_name="complete",
        mentors=[make_mentor_config(mentor_name="complete")],
        first_commit=True,
        amend_note_regexes=[r"\[mentor:complete\]"],
    )
    # Commit 1 filtered out, but commit 2 has amend note that matches
    commits = [CommitEntry(number=2, note="[mentor:complete] Review complete")]
    assert profile_matches_any_commit(profile, commits) is True


# Tests for project scoping


def test_get_matching_profiles_skips_wrong_project(monkeypatch: Any) -> None:
    """Test that profiles scoped to a project skip changespecs from other projects."""
    mock_profile = MagicMock()
    mock_profile.profile_name = "gotchas"
    mock_profile.mentors = [make_mentor_config(mentor_name="gotcha")]
    mock_profile.file_globs = []
    mock_profile.diff_regexes = []
    mock_profile.amend_note_regexes = [r".*"]
    mock_profile.projects = ["sase"]  # Scoped to sase project
    mock_profile.first_commit = False

    monkeypatch.setattr(
        "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
        lambda: [mock_profile],
    )

    # ChangeSpec from the "bug" project
    cs = build_changespec(
        file_path="/home/user/.sase/projects/bug/bug.gp",
        commits=[CommitEntry(number=1, note="Fix something")],
    )

    result = _get_matching_profiles_for_entry(cs)
    assert result == []


def test_get_matching_profiles_matches_correct_project(monkeypatch: Any) -> None:
    """Test that profiles scoped to a project match changespecs from that project."""
    mock_profile = MagicMock()
    mock_profile.profile_name = "gotchas"
    mock_profile.mentors = [make_mentor_config(mentor_name="gotcha")]
    mock_profile.file_globs = []
    mock_profile.diff_regexes = []
    mock_profile.amend_note_regexes = [r".*"]
    mock_profile.projects = ["sase"]
    mock_profile.first_commit = False

    monkeypatch.setattr(
        "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
        lambda: [mock_profile],
    )

    # ChangeSpec from the "sase" project
    cs = build_changespec(
        file_path="/home/user/.sase/projects/sase/sase.gp",
        commits=[CommitEntry(number=1, note="Add feature")],
    )

    result = _get_matching_profiles_for_entry(cs)
    assert len(result) == 1
    assert result[0][1].profile_name == "gotchas"


def test_get_matching_profiles_none_projects_matches_any(monkeypatch: Any) -> None:
    """Test that profiles with projects=None match any changespec (backwards compat)."""
    mock_profile = MagicMock()
    mock_profile.profile_name = "universal"
    mock_profile.mentors = [make_mentor_config(mentor_name="checker")]
    mock_profile.file_globs = []
    mock_profile.diff_regexes = []
    mock_profile.amend_note_regexes = [r".*"]
    mock_profile.projects = None
    mock_profile.first_commit = False

    monkeypatch.setattr(
        "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
        lambda: [mock_profile],
    )

    cs = build_changespec(
        file_path="/home/user/.sase/projects/bug/bug.gp",
        commits=[CommitEntry(number=1, note="Fix bug")],
    )

    result = _get_matching_profiles_for_entry(cs)
    assert len(result) == 1


def test_get_matching_profiles_reads_diff_once_per_invocation(
    monkeypatch: Any,
) -> None:
    """Test diff files are read once per commit, not once per profile."""
    profile_one = MentorProfileConfig(
        profile_name="diff-a",
        mentors=[make_mentor_config(mentor_name="a")],
        diff_regexes=[r"match-token"],
    )
    profile_two = MentorProfileConfig(
        profile_name="diff-b",
        mentors=[make_mentor_config(mentor_name="b")],
        diff_regexes=[r"match-token"],
    )
    read_paths: list[str | None] = []

    def _read_diff(diff_path: str | None) -> str | None:
        read_paths.append(diff_path)
        return "diff --git a/src/x.py b/src/x.py\n+match-token\n"

    monkeypatch.setattr(
        "sase.ace.scheduler.mentor_profile_matching.get_all_mentor_profiles",
        lambda: [profile_one, profile_two],
    )
    monkeypatch.setattr(
        "sase.ace.scheduler.mentor_profile_matching._read_diff_content",
        _read_diff,
    )
    monkeypatch.setattr(
        "sase.ace.scheduler.mentor_profile_matching.preload_vcs_fallback_diff",
        lambda _changespec, _commits: None,
    )

    cs = build_changespec(
        commits=[CommitEntry(number=1, note="n", diff="~/.sase/diffs/sample.diff")]
    )

    result = _get_matching_profiles_for_entry(cs)

    assert len(result) == 2
    assert read_paths == ["~/.sase/diffs/sample.diff"]
