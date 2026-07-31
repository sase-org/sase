"""Tests for completed-agent DELTAS rendering."""

from pathlib import Path

import pytest

from sase.ace.tui.models.agent import LinkedRepoMetadata
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_detail_header_summary,
    build_header_text,
)
from tests.ace.tui.widgets._agent_deltas_helpers import (
    clear_linked_delta_caches,
    make_agent,
)


@pytest.fixture(autouse=True)
def _clear_linked_delta_caches() -> None:
    clear_linked_delta_caches()


def test_completed_agent_with_diff_path_renders_deltas(tmp_path: Path) -> None:
    diff_path = tmp_path / "agent.diff"
    diff_path.write_text(
        """diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1 +1,2 @@
-old
+new
+extra
""",
        encoding="utf-8",
    )
    agent = make_agent(diff_path=str(diff_path))

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))

    assert "Deltas:\n" in header.plain
    assert "DELTAS:\n" not in header.plain
    assert "~ src/foo.py  +1 ~1" in header.plain


def test_completed_agent_merges_primary_deltas_from_all_commit_diffs(
    tmp_path: Path,
) -> None:
    first_diff = tmp_path / "001.diff"
    first_diff.write_text(
        """diff --git a/src/foo.py b/src/foo.py
new file mode 100644
--- /dev/null
+++ b/src/foo.py
@@ -0,0 +1,2 @@
+one
+two
""",
        encoding="utf-8",
    )
    second_diff = tmp_path / "002.diff"
    second_diff.write_text(
        """diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1 +1 @@
-one
+ONE
diff --git a/src/bar.py b/src/bar.py
deleted file mode 100644
--- a/src/bar.py
+++ /dev/null
@@ -1 +0,0 @@
-old
""",
        encoding="utf-8",
    )
    agent = make_agent(
        workspace_dir=str(tmp_path / "sase_7"),
        step_output={
            "meta_commits": [
                {
                    "message": "feat: add foo",
                    "sha": "111111111111aaaa",
                    "cwd": str(tmp_path / "sase_7"),
                    "diff_path": str(first_diff),
                },
                {
                    "message": "fix: revise foo",
                    "sha": "222222222222bbbb",
                    "cwd": str(tmp_path / "sase_7" / "src"),
                    "diff_path": str(second_diff),
                },
            ],
        },
    )

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))

    assert "Deltas:\n" in header.plain
    assert "  - src/bar.py  -1\n" in header.plain
    assert "  ~ src/foo.py  +2 ~1\n" in header.plain


def test_completed_agent_filters_root_commit_message_from_commit_diffs(
    tmp_path: Path,
) -> None:
    diff_path = tmp_path / "001.diff"
    diff_path.write_text(
        """diff --git a/commit_message.md b/commit_message.md
new file mode 100644
--- /dev/null
+++ b/commit_message.md
@@ -0,0 +1 @@
+temporary message
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1 +1,2 @@
 old
+new
""",
        encoding="utf-8",
    )
    agent = make_agent(
        workspace_dir=str(tmp_path / "sase_7"),
        step_output={
            "meta_commits": [
                {
                    "message": "feat: update foo",
                    "sha": "111111111111aaaa",
                    "cwd": str(tmp_path / "sase_7"),
                    "diff_path": str(diff_path),
                },
            ],
        },
    )

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))

    assert "Deltas:\n" in header.plain
    assert "commit_message.md" not in header.plain
    assert "  ~ src/foo.py  +1\n" in header.plain


def test_completed_agent_filters_dot_sase_commit_message_from_commit_diffs(
    tmp_path: Path,
) -> None:
    diff_path = tmp_path / "001.diff"
    diff_path.write_text(
        """diff --git a/.sase/commit_message.md b/.sase/commit_message.md
new file mode 100644
--- /dev/null
+++ b/.sase/commit_message.md
@@ -0,0 +1 @@
+temporary message
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1 +1,2 @@
 old
+new
""",
        encoding="utf-8",
    )
    agent = make_agent(
        workspace_dir=str(tmp_path / "sase_7"),
        step_output={
            "meta_commits": [
                {
                    "message": "feat: update foo",
                    "sha": "111111111111aaaa",
                    "cwd": str(tmp_path / "sase_7"),
                    "diff_path": str(diff_path),
                },
            ],
        },
    )

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))

    assert "Deltas:\n" in header.plain
    assert ".sase/commit_message.md" not in header.plain
    assert "  ~ src/foo.py  +1\n" in header.plain


def test_completed_agent_omits_deltas_when_only_commit_message_diff(
    tmp_path: Path,
) -> None:
    diff_path = tmp_path / "001.diff"
    diff_path.write_text(
        """diff --git a/commit_message.md b/commit_message.md
new file mode 100644
--- /dev/null
+++ b/commit_message.md
@@ -0,0 +1 @@
+temporary message
""",
        encoding="utf-8",
    )
    agent = make_agent(
        workspace_dir=str(tmp_path / "sase_7"),
        step_output={
            "meta_commits": [
                {
                    "message": "chore: finalize",
                    "sha": "111111111111aaaa",
                    "cwd": str(tmp_path / "sase_7"),
                    "diff_path": str(diff_path),
                },
            ],
        },
    )

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))

    assert "Deltas:" not in header.plain
    assert "commit_message.md" not in header.plain


def test_completed_agent_builds_linked_deltas_from_commit_diffs(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase_7"
    linked = tmp_path / "sase-core_7"
    linked_diff = tmp_path / "linked.diff"
    linked_diff.write_text(
        """diff --git a/crates/core/src/lib.rs b/crates/core/src/lib.rs
new file mode 100644
--- /dev/null
+++ b/crates/core/src/lib.rs
@@ -0,0 +1,3 @@
+pub fn one() {}
+pub fn two() {}
+pub fn three() {}
""",
        encoding="utf-8",
    )
    agent = make_agent(
        workspace_dir=str(primary),
        linked_repos=(
            LinkedRepoMetadata(
                name="sase-core",
                workspace_dir=str(linked),
            ),
        ),
        step_output={
            "meta_commits": [
                {
                    "message": "feat: linked core",
                    "sha": "222222222222bbbb",
                    "cwd": str(linked),
                    "diff_path": str(linked_diff),
                },
            ],
        },
    )

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))

    assert "Deltas:\n" in header.plain
    assert "  ▣ sase-core\n" in header.plain
    assert "    + crates/core/src/lib.rs  +3\n" in header.plain


def test_completed_agent_without_diff_path_omits_deltas() -> None:
    agent = make_agent(diff_path=None)

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))

    assert "Deltas:" not in header.plain
    assert "DELTAS:" not in header.plain


def test_cheap_header_omits_deltas(tmp_path: Path) -> None:
    diff_path = tmp_path / "agent.diff"
    diff_path.write_text(
        """diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1 +1 @@
-old
+new
""",
        encoding="utf-8",
    )
    agent = make_agent(diff_path=str(diff_path))

    header, _ = build_header_text(agent, cheap=True)

    assert "Deltas:" not in header.plain
    assert "DELTAS:" not in header.plain
