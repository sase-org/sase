"""Tests for shared diff path extraction."""

from __future__ import annotations

from sase.diff_paths import changed_files_from_diff


def test_changed_files_from_diff_extracts_git_rename_and_index_paths() -> None:
    diff_text = """diff --git a/src/old.py b/src/new.py
similarity index 98%
rename from src/old.py
rename to src/new.py
--- a/src/old.py
+++ b/src/new.py
Index: docs/guide.md
===================================================================
--- a/docs/guide.md
+++ b/docs/guide.md
"""

    assert changed_files_from_diff(diff_text) == ["docs/guide.md", "src/new.py"]


def test_changed_files_from_diff_extracts_mercurial_paths() -> None:
    diff_text = """diff -r 123:ABCDEF+ -r tip src/feature.py
--- a/src/feature.py
+++ b/src/feature.py
diff -r abc123 tests/test_feature.py
--- a/tests/test_feature.py
+++ b/tests/test_feature.py
"""

    assert changed_files_from_diff(diff_text) == [
        "src/feature.py",
        "tests/test_feature.py",
    ]


def test_changed_files_from_diff_ignores_dev_null() -> None:
    diff_text = """--- a/deleted.py
+++ /dev/null
"""

    assert changed_files_from_diff(diff_text) == []
