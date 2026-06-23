"""Tests for agent display workflow variables."""

from __future__ import annotations

import pytest

from sase.ace.tui.models.agent import LinkedRepoMetadata
from sase.ace.tui.widgets.file_panel import _linked_commits as linked_commits_mod
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    MAJOR_SECTION_RULE,
    assert_dim_divider_before,
)


@pytest.fixture(autouse=True)
def _clear_linked_commit_caches() -> None:
    linked_commits_mod._linked_commit_cache.clear()
    linked_commits_mod._selected_agent_linked_commit_cache.clear()
    linked_commits_mod._selected_agent_cache_monotonic.clear()


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
        assert_dim_divider_before(header, "COMMITS:\n")
        assert header.plain.count(MAJOR_SECTION_RULE) == 2

    def test_commits_section_renders_primary_and_cached_linked_groups(self) -> None:
        agent = make_agent(
            step_output={
                "meta_commit_message": "feat: add primary\n\nbody omitted",
                "meta_new_commit": "1234567890abcdef",
            },
            linked_repos=(
                LinkedRepoMetadata(
                    name="sase-core",
                    workspace_dir="/tmp/sase-core",
                    workspace_strategy="suffix",
                ),
            ),
        )
        linked_commits_mod._selected_agent_linked_commit_cache[agent.identity] = (
            linked_commits_mod.LinkedCommitGroup(
                repo_name="sase-core",
                workspace_dir="/tmp/sase-core",
                commits=(
                    linked_commits_mod.CommitInfo(
                        short_sha="9f8e7d6",
                        subject="feat: linked core",
                    ),
                    linked_commits_mod.CommitInfo(
                        short_sha="4c3b2a1",
                        subject="test: cover linked core",
                    ),
                ),
            ),
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "COMMITS:\n" in header.plain
        assert "  ▣ test\n" in header.plain
        assert "    1234567890ab feat: add primary\n" in header.plain
        assert "  ▣ sase-core\n" in header.plain
        assert "    9f8e7d6 feat: linked core\n" in header.plain
        assert "    4c3b2a1 test: cover linked core\n" in header.plain

    def test_workflow_variables_keep_non_commit_meta_fields(self) -> None:
        agent = make_agent(
            step_output={
                "meta_commit_message": "fix: align",
                "meta_new_commit": "96a895335",
                "meta_result": "ready",
            }
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "COMMITS:\n" in header.plain
        assert "WORKFLOW VARIABLES\n" in header.plain
        assert "Result: ready\n" in header.plain
        assert "Commit Message:" not in header.plain
        assert "New Commit:" not in header.plain

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
