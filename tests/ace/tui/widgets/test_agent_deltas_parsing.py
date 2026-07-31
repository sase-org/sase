"""Tests for parsing unified diffs into agent DELTAS."""

from sase.ace.changespec.models import DeltaEntry, DeltaLineStats
from sase.ace.tui.widgets.prompt_panel._agent_deltas import (
    _parse_unified_diff_deltas,
)


def test_parse_added_file_with_only_added_lines() -> None:
    diff = """diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+one
+two
"""

    assert _parse_unified_diff_deltas(diff) == [
        DeltaEntry(path="new.py", change_type="A", line_stats=DeltaLineStats(added=2))
    ]


def test_parse_deleted_file_with_only_removed_lines() -> None:
    diff = """diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-one
-two
"""

    assert _parse_unified_diff_deltas(diff) == [
        DeltaEntry(path="old.py", change_type="D", line_stats=DeltaLineStats(removed=2))
    ]


def test_parse_modified_file_pairs_adds_and_removes_as_modified() -> None:
    diff = """diff --git a/edit.py b/edit.py
--- a/edit.py
+++ b/edit.py
@@ -1,2 +1,2 @@
-old one
-old two
+new one
+new two
"""

    assert _parse_unified_diff_deltas(diff) == [
        DeltaEntry(
            path="edit.py", change_type="M", line_stats=DeltaLineStats(modified=2)
        )
    ]


def test_parse_mixed_modification_stats() -> None:
    diff = """diff --git a/edit.py b/edit.py
--- a/edit.py
+++ b/edit.py
@@ -1,4 +1,5 @@
-old one
-old two
-removed only
+new one
+new two
+added only
+added also
 context
"""

    assert _parse_unified_diff_deltas(diff) == [
        DeltaEntry(
            path="edit.py",
            change_type="M",
            line_stats=DeltaLineStats(added=1, modified=3),
        )
    ]


def test_parse_rename_displays_target_path() -> None:
    diff = """diff --git a/old.py b/new.py
similarity index 100%
rename from old.py
rename to new.py
--- a/old.py
+++ b/new.py
"""

    assert _parse_unified_diff_deltas(diff) == [
        DeltaEntry(path="new.py", change_type="M", line_stats=DeltaLineStats())
    ]


def test_parse_binary_diff() -> None:
    diff = """diff --git a/image.bin b/image.bin
index 123..456 100644
Binary files a/image.bin and b/image.bin differ
"""

    assert _parse_unified_diff_deltas(diff) == [
        DeltaEntry(
            path="image.bin",
            change_type="M",
            line_stats=DeltaLineStats(binary=True),
        )
    ]
