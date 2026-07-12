"""Tests for agent metadata DELTAS rendering."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text

from sase.ace.changespec.models import DeltaEntry, DeltaLineStats
from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata
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
from sase.ace.tui.widgets.file_panel import _diff as diff_mod
from sase.ace.tui.widgets.file_panel import _linked_deltas as linked_deltas_mod
from sase.ace.tui.widgets.file_panel._linked_deltas import LinkedDeltaGroup


@pytest.fixture(autouse=True)
def _clear_linked_delta_caches() -> None:
    linked_deltas_mod._linked_diff_text_cache.clear()
    linked_deltas_mod._linked_delta_cache.clear()
    linked_deltas_mod._selected_agent_linked_delta_cache.clear()
    linked_deltas_mod._selected_agent_cache_monotonic.clear()


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


class _WorkspaceDiffProvider:
    def __init__(self, diff_by_workspace: dict[str, str]) -> None:
        self.diff_by_workspace = diff_by_workspace

    def diff_with_untracked(self, cwd: str, *, timeout: int = 10):  # type: ignore[no-untyped-def]
        return (True, self.diff_by_workspace[Path(cwd).name])


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
    agent = _make_agent(
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
    agent = _make_agent(
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
    agent = _make_agent(
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
    agent = _make_agent(
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


def test_root_plan_agent_renders_deltas_from_active_coder_followup(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    (tmp_path / "myproj_1").mkdir()
    (tmp_path / "myproj_2").mkdir()
    root = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my-feature",
        project_file="/tmp/projects/myproj/myproj.sase",
        status="PLAN APPROVED",
        workspace_num=1,
        workflow="ace(plan)-202604010000",
        raw_suffix="202604010000",
        role_suffix="-plan",
        plan_chain_root=True,
    )
    coder = _make_agent(
        cl_name="my-feature-code",
        project_file="/tmp/projects/myproj/myproj.sase",
        status="PLAN APPROVED",
        start_time=datetime(2024, 1, 1, 15, 0),
        workspace_num=2,
        workspace_dir=str(tmp_path / "myproj_2"),
        workflow="ace(run)-202604010000-code",
        raw_suffix="202604010000-code",
        parent_timestamp="202604010000",
        role_suffix="-code",
    )
    root.followup_agents.append(coder)
    provider = _WorkspaceDiffProvider(
        {
            "myproj_1": """diff --git a/src/planner.py b/src/planner.py
--- a/src/planner.py
+++ b/src/planner.py
@@ -1 +1 @@
-old
+planner
""",
            "myproj_2": """diff --git a/src/coder.py b/src/coder.py
--- a/src/coder.py
+++ b/src/coder.py
@@ -1 +1 @@
-old
+coder
""",
        }
    )

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch(
            "sase.running_field.get_workspace_directory",
            side_effect=AssertionError("workspace materialization was called"),
        ):
            with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
                header, _ = build_header_text(
                    root,
                    summary=build_detail_header_summary(root),
                )

    assert "Deltas:\n" in header.plain
    assert "~ src/coder.py  ~1" in header.plain
    assert "src/planner.py" not in header.plain


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

    result = panel.update_display_with_hints(agent)

    plain = _plain_of(panel.captured[-1])
    assert "Deltas:\n  ~ [1] src/foo.py  ~1\n" in plain
    assert "DELTAS:" not in plain
    assert result.file_hints[1] == str(workspace_dir / "src/foo.py")


def test_agent_deltas_render_cached_linked_groups(tmp_path: Path) -> None:
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
    linked_workspace = tmp_path / "sase-core"
    linked_workspace.mkdir()
    agent = _make_agent(
        status="RUNNING",
        diff_path=str(diff_path),
        linked_repos=(
            LinkedRepoMetadata(
                name="sase-core",
                workspace_dir=str(linked_workspace),
            ),
        ),
    )
    linked_deltas_mod._selected_agent_linked_delta_cache[agent.identity] = (
        LinkedDeltaGroup(
            repo_name="sase-core",
            workspace_dir=str(linked_workspace),
            entries=(
                DeltaEntry(
                    path="crates/core/src/lib.rs",
                    change_type="A",
                    line_stats=DeltaLineStats(added=3),
                ),
            ),
        ),
    )

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))

    assert "Deltas:\n" in header.plain
    assert "  ~ src/foo.py  ~1\n" in header.plain
    assert "  ▣ sase-core\n" in header.plain
    assert "    + crates/core/src/lib.rs  +3\n" in header.plain


def test_active_primary_deltas_win_over_latest_companion_commit(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    primary = tmp_path / "sase_7"
    linked = tmp_path / "sase-core_7"
    (primary / ".git").mkdir(parents=True)
    (primary / ".git" / "index").write_bytes(b"\x00" * 16)
    linked.mkdir()
    companion_diff = tmp_path / "companion.diff"
    companion_diff.write_text(
        """diff --git a/crates/core/src/lib.rs b/crates/core/src/lib.rs
new file mode 100644
--- /dev/null
+++ b/crates/core/src/lib.rs
@@ -0,0 +1 @@
+pub fn live() {}
""",
        encoding="utf-8",
    )
    live_diff = """diff --git a/src/live.py b/src/live.py
--- a/src/live.py
+++ b/src/live.py
@@ -1 +1 @@
-old
+new
"""
    agent = _make_agent(
        status="RUNNING",
        workspace_dir=str(primary),
        diff_path=str(companion_diff),
        linked_repos=(LinkedRepoMetadata(name="sase-core", workspace_dir=str(linked)),),
        step_output={
            "meta_commits": [
                {
                    "message": "docs: companion plan",
                    "sha": "222222222222bbbb",
                    "cwd": str(linked),
                    "diff_path": str(companion_diff),
                },
            ],
        },
    )
    provider = _WorkspaceDiffProvider({primary.name: live_diff})

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            header, _ = build_header_text(
                agent,
                summary=build_detail_header_summary(agent),
            )

    assert "  ~ src/live.py  ~1\n" in header.plain
    assert "  ▣ sase-core\n" in header.plain
    assert "    + crates/core/src/lib.rs  +1\n" in header.plain
    assert "\n  + crates/core/src/lib.rs" not in header.plain


def test_agent_deltas_render_path_uses_linked_cache_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    linked_workspace = tmp_path / "sase-core"
    linked_workspace.mkdir()
    agent = _make_agent(
        status="RUNNING",
        linked_repos=(
            LinkedRepoMetadata(
                name="sase-core",
                workspace_dir=str(linked_workspace),
            ),
        ),
    )
    linked_deltas_mod._selected_agent_linked_delta_cache[agent.identity] = (
        LinkedDeltaGroup(
            repo_name="sase-core",
            workspace_dir=str(linked_workspace),
            entries=(DeltaEntry(path="src/lib.rs", change_type="M"),),
        ),
    )

    def fail_compute(_agent: Agent) -> tuple[LinkedDeltaGroup, ...]:
        raise AssertionError("render path computed linked deltas")

    monkeypatch.setattr(
        linked_deltas_mod,
        "compute_linked_delta_groups",
        fail_compute,
    )

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))

    assert "▣ sase-core" in header.plain
