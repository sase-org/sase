"""Tests for agent display commit metadata rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.models.agent import LinkedRepoMetadata
from sase.ace.tui.widgets.prompt_panel._agent_commits import agent_commit_diffs
from sase.ace.tui.widgets.prompt_panel._agent_deltas import (
    agent_commit_linked_delta_groups,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    build_header_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    MAJOR_SECTION_RULE,
    assert_dim_divider_before,
)


class TestCommitMetadataHeader:
    def test_commit_meta_renders_in_commits_section(self) -> None:
        agent = make_agent(
            step_output={
                "meta_commit_message": "fix: align",
                "meta_new_commit": "96a895335",
            }
        )

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())

        assert "  Commits:\n" in header.plain
        assert "    ▣ test\n" in header.plain
        assert "      96a895335 fix: align\n" in header.plain
        assert "WORKFLOW VARIABLES\n" not in header.plain
        assert "Commit Message:" not in header.plain
        assert "New Commit:" not in header.plain
        assert "Commit Cwd:" not in header.plain
        assert_dim_divider_before(header, "SASE CONTEXT\n")
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

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())

        assert "  Commits:\n" in header.plain
        assert "    ▣ test\n" in header.plain
        assert "      1234567890ab feat: add primary\n" in header.plain

    def test_commit_primary_repo_label_uses_project_display_name(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.ace.tui.widgets.prompt_panel._agent_commits.project_display_name_for",
            lambda key: "widgets" if key == "gh_acme__widgets" else key,
        )
        project_dir = tmp_path / "gh_acme__widgets"
        workspace = tmp_path / "gh_acme__widgets_7"
        agent = make_agent(
            project_file=str(project_dir / "gh_acme__widgets.sase"),
            workspace_dir=str(workspace),
            step_output={
                "meta_commit_message": "feat: display project\n",
                "meta_new_commit": "1234567890abcdef",
                "meta_commit_cwd": str(workspace),
            },
        )

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())
        commit_diffs = agent_commit_diffs(
            make_agent(
                project_file=str(project_dir / "gh_acme__widgets.sase"),
                workspace_dir=str(workspace),
                step_output={
                    "meta_commits": [
                        {
                            "message": "feat: display project",
                            "sha": "1234567890abcdef",
                            "cwd": str(workspace),
                            "diff_path": str(tmp_path / "001.diff"),
                        }
                    ],
                },
            )
        )

        assert "    ▣ widgets\n" in header.plain
        assert "gh_acme__widgets" not in header.plain
        assert [diff.repo_name for diff in commit_diffs] == ["widgets"]

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
                ),
            ),
        )

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())

        assert "  Commits:\n" in header.plain
        assert "    ▣ test\n" not in header.plain
        assert "    ▣ sase-core\n" in header.plain
        assert "      9f8e7d6c5b4a feat: linked core\n" in header.plain

    def test_commit_cwd_matching_nested_linked_workspace_is_not_primary(
        self,
        tmp_path: Path,
    ) -> None:
        primary = tmp_path / "bob-cli_10"
        linked = primary / "sase" / "repos" / "linked" / "bob-plugins"
        agent = make_agent(
            workspace_dir=str(primary),
            step_output={
                "meta_commit_message": "fix: linked plugin",
                "meta_new_commit": "9f8e7d6c5b4a3",
                "meta_commit_cwd": str(linked),
            },
            linked_repos=(
                LinkedRepoMetadata(
                    name="bob-plugins",
                    workspace_dir=str(linked),
                ),
            ),
        )
        hint_state = HeaderHintState(1, {}, str(primary), {})

        header, _ = build_header_text(
            agent,
            summary=DetailHeaderSummary(),
            hint_state=hint_state,
        )

        assert "    ▣ bob-plugins\n" in header.plain
        assert "    ▣ test\n" not in header.plain
        assert "      [1] 9f8e7d6c5b4a fix: linked plugin\n" in header.plain
        assert hint_state.commit_views[1].repo_name == "bob-plugins"
        assert hint_state.commit_views[1].is_primary is False

    def test_meta_commits_render_primary_group_first_then_linked(
        self,
        tmp_path: Path,
    ) -> None:
        primary = tmp_path / "sase_7"
        linked = tmp_path / "sase-core_7"
        agent = make_agent(
            workspace_dir=str(primary),
            step_output={
                "meta_commit_message": "feat: linked core",
                "meta_new_commit": "222222222222bbbb",
                "meta_commit_cwd": str(linked),
                "meta_commits": [
                    {
                        "message": "feat: linked core",
                        "sha": "222222222222bbbb",
                        "cwd": str(linked / "crates" / "core"),
                    },
                    {
                        "message": "feat: primary workspace",
                        "sha": "111111111111aaaa",
                        "cwd": str(primary / "src"),
                    },
                ],
            },
            linked_repos=(
                LinkedRepoMetadata(
                    name="sase-core",
                    workspace_dir=str(linked),
                ),
            ),
        )

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())

        assert "  Commits:\n" in header.plain
        assert header.plain.index("    ▣ test\n") < header.plain.index(
            "    ▣ sase-core\n"
        )
        assert "      111111111111 feat: primary workspace\n" in header.plain
        assert "      222222222222 feat: linked core\n" in header.plain

    def test_meta_commits_attribute_nested_linked_and_primary_workspaces(
        self,
        tmp_path: Path,
    ) -> None:
        primary = tmp_path / "bob-cli_10"
        linked = primary / "sase" / "repos" / "linked" / "bob-plugins"
        agent = make_agent(
            workspace_dir=str(primary),
            step_output={
                "meta_commits": [
                    {
                        "message": "fix: linked plugin",
                        "sha": "222222222222bbbb",
                        "cwd": str(linked),
                    },
                    {
                        "message": "feat: primary workspace",
                        "sha": "111111111111aaaa",
                        "cwd": str(primary),
                    },
                ],
            },
            linked_repos=(
                LinkedRepoMetadata(
                    name="bob-plugins",
                    workspace_dir=str(linked),
                ),
            ),
        )

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())

        assert header.plain.index("    ▣ test\n") < header.plain.index(
            "    ▣ bob-plugins\n"
        )
        assert "      111111111111 feat: primary workspace\n" in header.plain
        assert "      222222222222 fix: linked plugin\n" in header.plain

    def test_meta_commits_same_cwd_render_one_group_with_multiple_rows(
        self,
        tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "sase_8"
        agent = make_agent(
            workspace_dir=str(workspace),
            step_output={
                "meta_commits": [
                    {
                        "message": "feat: first primary",
                        "sha": "aaaaaaaaaaa111",
                        "cwd": str(workspace),
                    },
                    {
                        "message": "fix: second primary",
                        "sha": "bbbbbbbbbbb222",
                        "cwd": str(workspace / "src"),
                    },
                ],
            },
        )

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())

        assert header.plain.count("    ▣ test\n") == 1
        assert "      aaaaaaaaaaa1 feat: first primary\n" in header.plain
        assert "      bbbbbbbbbbb2 fix: second primary\n" in header.plain

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

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())

        assert "  Commits:\n" in header.plain
        assert "    ▣ sase-core\n" in header.plain
        assert "      abcdef123456 fix: linked without metadata\n" in header.plain

    def test_meta_commits_unmatched_cwd_renders_basename_group(
        self,
        tmp_path: Path,
    ) -> None:
        commit_cwd = tmp_path / "sase-core_18"
        agent = make_agent(
            workspace_dir=str(tmp_path / "sase_18"),
            step_output={
                "meta_commits": [
                    {
                        "message": "fix: linked without metadata",
                        "sha": "abcdef123456",
                        "cwd": str(commit_cwd),
                    }
                ],
            },
        )

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())

        assert "  Commits:\n" in header.plain
        assert "    ▣ sase-core\n" in header.plain
        assert "      abcdef123456 fix: linked without metadata\n" in header.plain

    def test_meta_commits_record_repo_name_overrides_cwd_group(
        self,
        tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "sase_18"
        agent = make_agent(
            workspace_dir=str(workspace),
            step_output={
                "meta_commits": [
                    {
                        "message": "Archive approved plan demo",
                        "sha": "abcdef123456",
                        "cwd": str(workspace / ".sase" / "sdd"),
                        "repo_name": "sase-org/sase--sdd",
                        "diff_path": str(tmp_path / "sdd.diff"),
                    }
                ],
            },
        )

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())
        commit_diffs = agent_commit_diffs(agent)

        assert "  Commits:\n" in header.plain
        assert "    ▣ sase-org/sase--sdd\n" in header.plain
        assert "    ▣ test\n" not in header.plain
        assert "      abcdef123456 Archive approved plan demo\n" in header.plain
        assert [(diff.repo_name, diff.is_primary) for diff in commit_diffs] == [
            ("sase-org/sase--sdd", False)
        ]

    def test_meta_commits_legacy_sdd_name_uses_sidecar_cwd_role(
        self,
        tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "sase_18"
        sidecar = workspace / "sase" / "repos" / "beads"
        diff_path = tmp_path / "beads.diff"
        diff_path.write_text(
            """diff --git a/issues.jsonl b/issues.jsonl
new file mode 100644
--- /dev/null
+++ b/issues.jsonl
@@ -0,0 +1 @@
+{"id":"sase-1"}
""",
            encoding="utf-8",
        )
        agent = make_agent(
            workspace_dir=str(workspace),
            step_output={
                "meta_commits": [
                    {
                        "message": "chore(beads): update state",
                        "sha": "abcdef123456",
                        "cwd": str(sidecar),
                        "repo_name": "sdd",
                        "diff_path": str(diff_path),
                    }
                ],
            },
        )

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())
        commit_diffs = agent_commit_diffs(agent)
        delta_groups = agent_commit_linked_delta_groups(agent)

        assert "    ▣ beads\n" in header.plain
        assert "    ▣ sdd\n" not in header.plain
        assert [(diff.repo_name, diff.is_primary) for diff in commit_diffs] == [
            ("beads", False)
        ]
        assert [group.repo_name for group in delta_groups] == ["beads"]

    def test_meta_commits_sdd_cwd_without_repo_name_falls_back_to_sdd(
        self,
        tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "sase_18"
        agent = make_agent(
            workspace_dir=str(tmp_path / "other_18"),
            step_output={
                "meta_commits": [
                    {
                        "message": "Archive approved plan demo",
                        "sha": "abcdef123456",
                        "cwd": str(workspace / ".sase" / "sdd"),
                    }
                ],
            },
        )

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())

        assert "  Commits:\n" in header.plain
        assert "    ▣ sdd\n" in header.plain
        assert "      abcdef123456 Archive approved plan demo\n" in header.plain

    def test_sidecar_cwd_without_repo_name_is_non_primary(
        self,
        tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "sase_18"
        sidecar = workspace / "sase" / "repos" / "designs"
        agent = make_agent(
            workspace_dir=str(workspace),
            step_output={
                "meta_commits": [
                    {
                        "message": "docs(designs): update system notes",
                        "sha": "abcdef123456",
                        "cwd": str(sidecar),
                        "diff_path": str(tmp_path / "designs.diff"),
                    }
                ],
            },
        )

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())
        commit_diffs = agent_commit_diffs(agent)

        assert "    ▣ designs\n" in header.plain
        assert [(diff.repo_name, diff.is_primary) for diff in commit_diffs] == [
            ("designs", False)
        ]


def test_external_commit_is_attributed_from_nested_clone_path(tmp_path: Path) -> None:
    primary = tmp_path / "sase_7"
    external = primary / "sase" / "repos" / "external" / "gh" / "pallets" / "click"
    diff_path = tmp_path / "external.diff"
    agent = make_agent(
        workspace_dir=str(primary),
        step_output={
            "meta_commits": [
                {
                    "message": "fix: external parser",
                    "sha": "eeeeeeeeeeeeffff",
                    "cwd": str(external / "src"),
                    "diff_path": str(diff_path),
                }
            ],
        },
    )

    header, _ = build_header_text(agent, summary=DetailHeaderSummary())
    commit_diffs = agent_commit_diffs(agent)

    assert "    ◆ gh:pallets/click\n" in header.plain
    assert [
        (diff.repo_name, diff.repo_kind, diff.is_primary, diff.workspace_dir)
        for diff in commit_diffs
    ] == [("gh:pallets/click", "external", False, str(external))]
