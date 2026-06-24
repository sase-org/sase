"""Tests for agent display workflow variables."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.models.agent import LinkedRepoMetadata
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    MAJOR_SECTION_RULE,
    assert_dim_divider_before,
)


class TestWorkflowVariablesHeader:
    def test_commit_meta_renders_in_commits_section(self) -> None:
        agent = make_agent(
            step_output={
                "meta_commit_message": "fix: align",
                "meta_new_commit": "96a895335",
            }
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "COMMITS:\n" in header.plain
        assert "  ▣ test\n" in header.plain
        assert "    96a895335 fix: align\n" in header.plain
        assert "WORKFLOW VARIABLES\n" not in header.plain
        assert "Commit Message:" not in header.plain
        assert "New Commit:" not in header.plain
        assert "Commit Cwd:" not in header.plain
        assert_dim_divider_before(header, "COMMITS:\n")
        assert header.plain.count(MAJOR_SECTION_RULE) == 2

    def test_commit_cwd_matching_primary_workspace_renders_primary_group(
        self,
        tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "sase_7"
        agent = make_agent(
            workspace_dir=str(workspace),
            step_output={
                "meta_commit_message": "feat: add primary\n\nbody omitted",
                "meta_new_commit": "1234567890abcdef",
                "meta_commit_cwd": str(workspace / "src"),
            },
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "COMMITS:\n" in header.plain
        assert "  ▣ test\n" in header.plain
        assert "    1234567890ab feat: add primary\n" in header.plain

    def test_commit_cwd_matching_linked_workspace_renders_linked_group(
        self,
        tmp_path: Path,
    ) -> None:
        primary = tmp_path / "sase_7"
        linked = tmp_path / "sase-core_7"
        agent = make_agent(
            workspace_dir=str(primary),
            step_output={
                "meta_commit_message": "feat: linked core\n\nbody omitted",
                "meta_new_commit": "9f8e7d6c5b4a3",
                "meta_commit_cwd": str(linked / "crates" / "core"),
            },
            linked_repos=(
                LinkedRepoMetadata(
                    name="sase-core",
                    workspace_dir=str(linked),
                    workspace_strategy="suffix",
                ),
            ),
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "COMMITS:\n" in header.plain
        assert "  ▣ test\n" not in header.plain
        assert "  ▣ sase-core\n" in header.plain
        assert "    9f8e7d6c5b4a feat: linked core\n" in header.plain

    def test_commit_cwd_unmatched_renders_basename_group(
        self,
        tmp_path: Path,
    ) -> None:
        commit_cwd = tmp_path / "sase-core_18"
        agent = make_agent(
            workspace_dir=str(tmp_path / "sase_18"),
            step_output={
                "meta_commit_message": "fix: linked without metadata",
                "meta_new_commit": "abcdef123456",
                "meta_commit_cwd": str(commit_cwd),
            },
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "COMMITS:\n" in header.plain
        assert "  ▣ sase-core\n" in header.plain
        assert "    abcdef123456 fix: linked without metadata\n" in header.plain

    def test_workflow_variables_keep_non_commit_meta_fields(self) -> None:
        agent = make_agent(
            step_output={
                "meta_commit_message": "fix: align",
                "meta_new_commit": "96a895335",
                "meta_commit_cwd": "/tmp/sase-core_4",
                "meta_result": "ready",
            }
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "COMMITS:\n" in header.plain
        assert "WORKFLOW VARIABLES\n" in header.plain
        assert "Result: ready\n" in header.plain
        assert "Commit Message:" not in header.plain
        assert "New Commit:" not in header.plain
        assert "Commit Cwd:" not in header.plain

    def test_header_absent_when_no_meta_fields(self) -> None:
        agent = make_agent(step_output={"status": "ok"})

        header, _ = build_header_text(agent, cheap=True)

        assert "WORKFLOW VARIABLES" not in header.plain
        assert "COMMITS:" not in header.plain
        assert header.plain.count(MAJOR_SECTION_RULE) == 1

    def test_header_absent_when_no_step_output(self) -> None:
        agent = make_agent()

        header, _ = build_header_text(agent, cheap=True)

        assert "WORKFLOW VARIABLES" not in header.plain
        assert "COMMITS:" not in header.plain
        assert header.plain.count(MAJOR_SECTION_RULE) == 1
