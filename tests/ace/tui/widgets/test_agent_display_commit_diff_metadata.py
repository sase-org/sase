"""Tests for agent display commit metadata views and diffs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.ace.tui.models.agent import LinkedRepoMetadata
from sase.ace.tui.widgets.prompt_panel._agent_commits import (
    agent_commit_diffs,
    load_commit_created_at,
    load_commit_diff_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    build_header_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    CommitViewSpec,
    HeaderHintState,
)
from sase.core.vcs_log_wire import VcsCommitWire
from tests.ace.tui.widgets._agent_display_helpers import make_agent


class TestCommitMetadataViewsAndDiffs:
    def test_meta_commits_register_view_hints(
        self,
        tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "sase_8"
        diff_path = tmp_path / "001.diff"
        agent = make_agent(
            workspace_dir=str(workspace),
            step_output={
                "meta_commits": [
                    {
                        "message": (
                            "feat: first primary\n\nbody line\n\n"
                            "SASE_PLAN=202607/agent-plan.md"
                        ),
                        "sha": "aaaaaaaaaaa111ffff",
                        "cwd": str(workspace),
                        "diff_path": str(diff_path),
                    },
                    {
                        "message": "fix: second primary",
                        "sha": "bbbbbbbbbbb222eeee",
                        "cwd": str(workspace / "src"),
                    },
                ],
            },
        )
        hint_state = HeaderHintState(
            hint_counter=3,
            hint_mappings={},
            workspace_dir=str(workspace),
            tool_call_reports={},
        )

        header, _ = build_header_text(
            agent,
            summary=DetailHeaderSummary(),
            hint_state=hint_state,
        )

        assert "      [3] aaaaaaaaaaa1 feat: first primary\n" in header.plain
        assert "      [4] bbbbbbbbbbb2 fix: second primary\n" in header.plain
        assert hint_state.hint_counter == 5
        assert hint_state.hint_mappings == {}
        assert hint_state.commit_views[3].sha == "aaaaaaaaaaa111ffff"
        assert hint_state.commit_views[3].message == (
            "feat: first primary\n\nbody line\n\nSASE_PLAN=202607/agent-plan.md"
        )
        assert hint_state.commit_views[3].diff_path == str(diff_path)
        assert hint_state.commit_views[3].plan_workspaces[0].workspace_dir == str(
            workspace
        )
        assert hint_state.commit_views[4].diff_path is None

    def test_agent_commit_diffs_order_primary_first_and_dedups_legacy_paths(
        self,
        tmp_path: Path,
    ) -> None:
        primary = tmp_path / "sase_7"
        linked = tmp_path / "sase-core_7"
        shared_legacy_diff = tmp_path / "commit_diff.diff"
        primary_diff = tmp_path / "001.diff"
        linked_diff = tmp_path / "002.diff"
        agent = make_agent(
            workspace_dir=str(primary),
            step_output={
                "meta_commits": [
                    {
                        "message": "feat: linked core",
                        "sha": "222222222222bbbb",
                        "cwd": str(linked),
                        "diff_path": str(linked_diff),
                    },
                    {
                        "message": "feat: primary workspace",
                        "sha": "111111111111aaaa",
                        "cwd": str(primary / "src"),
                        "diff_path": str(primary_diff),
                    },
                    {
                        "message": "fix: legacy first",
                        "sha": "333333333333cccc",
                        "cwd": str(primary),
                        "diff_path": str(shared_legacy_diff),
                    },
                    {
                        "message": "fix: legacy duplicate",
                        "sha": "444444444444dddd",
                        "cwd": str(primary),
                        "diff_path": str(shared_legacy_diff),
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

        commit_diffs = agent_commit_diffs(agent)

        assert [
            (info.repo_name, info.short_sha, info.diff_path, info.is_primary)
            for info in commit_diffs
        ] == [
            ("test", "111111111111", str(primary_diff), True),
            ("test", "333333333333", str(shared_legacy_diff), True),
            ("sase-core", "222222222222", str(linked_diff), False),
        ]

    def test_agent_commit_diffs_attribute_nested_linked_workspace(
        self,
        tmp_path: Path,
    ) -> None:
        primary = tmp_path / "bob-cli_10"
        linked = primary / "sase" / "repos" / "linked" / "bob-plugins"
        linked_diff = tmp_path / "linked.diff"
        agent = make_agent(
            workspace_dir=str(primary),
            step_output={
                "meta_commits": [
                    {
                        "message": "fix: linked plugin",
                        "sha": "222222222222bbbb",
                        "cwd": str(linked),
                        "diff_path": str(linked_diff),
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

        commit_diffs = agent_commit_diffs(agent)

        assert [(diff.repo_name, diff.is_primary) for diff in commit_diffs] == [
            ("bob-plugins", False)
        ]

    def test_load_commit_diff_text_reads_persisted_file(self, tmp_path: Path) -> None:
        diff_path = tmp_path / "commit.diff"
        diff_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")
        agent = make_agent(
            step_output={
                "meta_commits": [
                    {
                        "message": "feat: file diff",
                        "sha": "abc123",
                        "cwd": str(tmp_path),
                        "diff_path": str(diff_path),
                    }
                ]
            },
        )
        hint_state = HeaderHintState(1, {}, str(tmp_path), {})
        build_header_text(
            agent,
            summary=DetailHeaderSummary(),
            hint_state=hint_state,
        )

        assert (
            load_commit_diff_text(hint_state.commit_views[1])
            == "diff --git a/a.txt b/a.txt\n"
        )

    def test_load_commit_diff_text_falls_back_to_vcs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class Provider:
            def show_revision(self, revision: str, cwd: str) -> tuple[bool, str | None]:
                assert revision == "abc123"
                assert cwd == str(tmp_path)
                return True, "diff --git a/f b/f\n"

        monkeypatch.setattr(
            "sase.vcs_provider.get_vcs_provider",
            lambda _cwd: Provider(),
        )
        agent = make_agent(
            step_output={
                "meta_commits": [
                    {
                        "message": "feat: fallback",
                        "sha": "abc123",
                        "cwd": str(tmp_path),
                    }
                ]
            },
        )
        hint_state = HeaderHintState(1, {}, str(tmp_path), {})
        build_header_text(
            agent,
            summary=DetailHeaderSummary(),
            hint_state=hint_state,
        )

        assert load_commit_diff_text(hint_state.commit_views[1]) == (
            "diff --git a/f b/f\n"
        )

    def _spec(self, **overrides: object) -> CommitViewSpec:
        base = CommitViewSpec(
            short_sha="abc1234",
            sha="abc1234567890",
            repo_name="sase",
            cwd="/workspace/sase",
            subject="feat: x",
            message="feat: x",
            diff_path=None,
            is_primary=True,
        )
        return replace(base, **overrides)

    def test_load_commit_created_at_returns_none_without_sha_or_cwd(self) -> None:
        assert load_commit_created_at(self._spec(sha="")) is None
        assert load_commit_created_at(self._spec(cwd=None)) is None

    def test_load_commit_created_at_skips_lookup_when_already_known(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail_if_called(_cwd: str) -> None:
            raise AssertionError("get_vcs_provider should not be called")

        monkeypatch.setattr("sase.vcs_provider.get_vcs_provider", fail_if_called)

        assert load_commit_created_at(self._spec(created_at=1_700_000_000)) is None

    def test_load_commit_created_at_returns_none_when_provider_raises(
        self,
    ) -> None:
        def boom(_cwd: str) -> None:
            raise RuntimeError("provider unavailable")

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr("sase.vcs_provider.get_vcs_provider", boom)
            assert load_commit_created_at(self._spec()) is None

    def test_load_commit_created_at_rejects_mismatched_no_merges_ancestor(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class Provider:
            def log(
                self, cwd: str, limit: int, *, revs: tuple[str, ...], **_kwargs: object
            ) -> list[VcsCommitWire]:
                assert revs == ("abc1234567890",)
                return [
                    VcsCommitWire(
                        full_id="deadbeef00000000",
                        short_id="deadbeef",
                        author_name="bryan",
                        author_email="b@x",
                        timestamp=1_700_000_000,
                        subject="unrelated ancestor",
                        body="",
                    )
                ]

        monkeypatch.setattr(
            "sase.vcs_provider.get_vcs_provider",
            lambda _cwd: Provider(),
        )

        assert load_commit_created_at(self._spec()) is None

    def test_load_commit_created_at_resolves_matching_commit(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class Provider:
            def log(
                self, cwd: str, limit: int, *, revs: tuple[str, ...], **_kwargs: object
            ) -> list[VcsCommitWire]:
                return [
                    VcsCommitWire(
                        full_id="abc1234567890",
                        short_id="abc1234",
                        author_name="bryan",
                        author_email="b@x",
                        timestamp=1_700_000_000,
                        subject="feat: x",
                        body="",
                    )
                ]

        monkeypatch.setattr(
            "sase.vcs_provider.get_vcs_provider",
            lambda _cwd: Provider(),
        )

        assert load_commit_created_at(self._spec()) == 1_700_000_000
