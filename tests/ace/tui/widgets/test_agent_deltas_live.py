"""Tests for live and cached agent DELTAS rendering."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.changespec.models import DeltaEntry, DeltaLineStats
from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_detail_header_summary,
    build_header_text,
    cache_detail_header_summary,
)
from sase.ace.tui.widgets.file_panel import _diff as diff_mod
from sase.ace.tui.widgets.file_panel import _linked_deltas as linked_deltas_mod
from sase.ace.tui.widgets.file_panel._linked_deltas import LinkedDeltaGroup
from tests.ace.tui.widgets._agent_deltas_helpers import (
    FakePromptPanel,
    WorkspaceDiffProvider,
    clear_linked_delta_caches,
    make_agent,
    plain_of,
)


@pytest.fixture(autouse=True)
def _clear_linked_delta_caches() -> None:
    clear_linked_delta_caches()


def test_root_plan_agent_renders_deltas_from_active_coder_followup(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    (tmp_path / "myproj_1").mkdir()
    (tmp_path / "myproj_2").mkdir()
    root = make_agent(
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
    coder = make_agent(
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
    provider = WorkspaceDiffProvider(
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
    agent = make_agent(
        artifacts_dir=str(artifacts_dir),
        response_path=str(artifacts_dir / "response.md"),
        diff_path=str(diff_path),
        workspace_dir=str(workspace_dir),
    )
    panel = FakePromptPanel()
    cache_detail_header_summary(
        panel,
        agent,
        build_detail_header_summary(agent),
    )

    result = panel.update_display_with_hints(agent)

    plain = plain_of(panel.captured[-1])
    assert "  Deltas:\n    ~ [1] src/foo.py  ~1\n" in plain
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
    agent = make_agent(
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


def test_active_primary_deltas_win_over_latest_sidecar_commit(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    primary = tmp_path / "sase_7"
    linked = tmp_path / "sase-core_7"
    (primary / ".git").mkdir(parents=True)
    (primary / ".git" / "index").write_bytes(b"\x00" * 16)
    linked.mkdir()
    sidecar_diff = tmp_path / "sidecar.diff"
    sidecar_diff.write_text(
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
    agent = make_agent(
        status="RUNNING",
        workspace_dir=str(primary),
        diff_path=str(sidecar_diff),
        linked_repos=(LinkedRepoMetadata(name="sase-core", workspace_dir=str(linked)),),
        step_output={
            "meta_commits": [
                {
                    "message": "docs: sidecar plan",
                    "sha": "222222222222bbbb",
                    "cwd": str(linked),
                    "diff_path": str(sidecar_diff),
                },
            ],
        },
    )
    provider = WorkspaceDiffProvider({primary.name: live_diff})

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
    agent = make_agent(
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


def test_agent_deltas_render_external_groups_after_linked_groups() -> None:
    agent = make_agent(status="RUNNING")
    linked_deltas_mod._selected_agent_linked_delta_cache[agent.identity] = (
        LinkedDeltaGroup(
            repo_name="gh:pallets/click",
            workspace_dir="/workspace/external/gh/pallets/click",
            entries=(DeltaEntry(path="src/core.py", change_type="M"),),
            kind="external",
        ),
        LinkedDeltaGroup(
            repo_name="sase-core",
            workspace_dir="/workspace/sase-core",
            entries=(DeltaEntry(path="src/lib.rs", change_type="M"),),
        ),
    )

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))

    assert "  ▣ sase-core\n" in header.plain
    assert "  ◆ gh:pallets/click\n" in header.plain
    assert header.plain.index("▣ sase-core") < header.plain.index("◆ gh:pallets/click")
