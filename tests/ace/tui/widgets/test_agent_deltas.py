"""Tests for agent metadata DELTAS rendering."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text

from sase.ace.changespec.models import DeltaEntry, DeltaLineStats
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel._agent_deltas import (
    _parse_unified_diff_deltas,
)
from sase.ace.tui.widgets.prompt_panel._agent_display import AgentDisplayMixin
from sase.ace.tui.widgets.prompt_panel._agent_display_hints import (
    AgentHintsDisplayMixin,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_detail_header_summary,
    build_header_text,
)


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/test.sase",
        "status": "DONE",
        "start_time": datetime(2024, 1, 1, 14, 23, 45),
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _FakePromptPanel(AgentDisplayMixin, AgentHintsDisplayMixin):
    def __init__(self) -> None:
        self.captured: list[object] = []

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)


def _plain_of(renderable: object) -> str:
    if isinstance(renderable, Text):
        return renderable.plain
    if isinstance(renderable, Syntax):
        return str(renderable.code)
    if isinstance(renderable, Group):
        return "\n".join(_plain_of(child) for child in renderable.renderables)
    return str(renderable)


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
    agent = _make_agent(diff_path=str(diff_path))

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))

    assert "Deltas:\n" in header.plain
    assert "DELTAS:\n" not in header.plain
    assert "~ src/foo.py  +1 ~1" in header.plain


def test_completed_agent_without_diff_path_omits_deltas() -> None:
    agent = _make_agent(diff_path=None)

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
    agent = _make_agent(diff_path=str(diff_path))

    header, _ = build_header_text(agent, cheap=True)

    assert "Deltas:" not in header.plain
    assert "DELTAS:" not in header.plain


def test_agent_hint_mode_includes_deltas_paths(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "01_prompt.md").write_text("Prompt body\n", encoding="utf-8")
    (artifacts_dir / "response.md").write_text("Done\n", encoding="utf-8")
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
    agent = _make_agent(
        artifacts_dir=str(artifacts_dir),
        response_path=str(artifacts_dir / "response.md"),
        diff_path=str(diff_path),
        workspace_dir=str(workspace_dir),
    )
    panel = _FakePromptPanel()

    mappings = panel.update_display_with_hints(agent)

    plain = _plain_of(panel.captured[-1])
    assert "Deltas:\n  ~ [1] src/foo.py  ~1\n" in plain
    assert "DELTAS:" not in plain
    assert mappings[1] == str(workspace_dir / "src/foo.py")
