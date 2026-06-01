"""Tests for agent display bead metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.models.agent_bead import derive_agent_bead_id
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_detail_header_summary,
    build_header_text,
)
from sase.bead.model import BeadTier, Issue, IssueType
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_metadata_prefix,
)


class TestAgentBeadMetadata:
    def test_bead_rows_are_first_metadata_rows_in_cheap_and_full_headers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")

        cheap_header, _ = build_header_text(agent, cheap=True)
        assert_metadata_prefix(
            cheap_header,
            "Name: @sase-x.3",
            "Bead: sase-x.3",
        )

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: Issue(
                id=bead_id,
                title="Phase title",
                description="First line",
            ),
        )

        full_header, _ = build_header_text(
            agent,
            cheap=False,
            summary=build_detail_header_summary(agent),
        )
        assert_metadata_prefix(
            full_header,
            "Name: @sase-x.3",
            "Bead: sase-x.3 - First line",
        )

    def test_phase_agent_name_renders_bead(self) -> None:
        agent = make_agent(agent_name="sase-x.3")

        assert derive_agent_bead_id(agent) == "sase-x.3"
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @sase-x.3\nBead: sase-x.3\n" in header.plain

    def test_land_agent_name_renders_epic_bead(self) -> None:
        agent = make_agent(agent_name="sase-x.land")

        assert derive_agent_bead_id(agent) == "sase-x"
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @sase-x.land\nBead: sase-x\n" in header.plain

    def test_exact_epic_agent_name_renders_epic_bead(self) -> None:
        agent = make_agent(agent_name="sase-x")

        assert derive_agent_bead_id(agent) == "sase-x"
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @sase-x\nBead: sase-x\n" in header.plain

    def test_dismissed_phase_agent_name_uses_underlying_bead(self) -> None:
        agent = make_agent(agent_name="260428.sase-x.3")

        assert derive_agent_bead_id(agent) == "sase-x.3"
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @260428.sase-x.3\nBead: sase-x.3\n" in header.plain

    def test_ordinary_agent_name_omits_bead(self) -> None:
        agent = make_agent(agent_name="reviewer")

        assert derive_agent_bead_id(agent) is None
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @reviewer\n" in header.plain
        assert "Bead:" not in header.plain

    def test_dotted_ordinary_agent_name_omits_bead(self) -> None:
        agent = make_agent(agent_name="aij.2")

        assert derive_agent_bead_id(agent) is None
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @aij.2\n" in header.plain
        assert "Bead:" not in header.plain

    def test_full_header_renders_bead_description(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: Issue(
                id=bead_id,
                title="Phase title",
                description="First line\n\n second\tline ",
            ),
        )

        header, _ = build_header_text(
            agent,
            cheap=False,
            summary=build_detail_header_summary(agent),
        )

        assert "Name: @sase-x.3\nBead: sase-x.3 - First line second line\n" in (
            header.plain
        )

    def test_full_header_passes_agent_project_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(
            agent_name="zorg-4.3.6",
            project_file="/home/me/.sase/projects/zorg/zorg.sase",
        )
        seen_project_names: list[str | None] = []

        def lookup(
            bead_id: str,
            *,
            project_name: str | None = None,
            workspace_dir: str | None = None,
        ) -> Issue | None:
            del workspace_dir
            seen_project_names.append(project_name)
            return Issue(
                id=bead_id,
                title="Phase 6: count() MVP And Final Epic Hardening",
                description="",
            )

        monkeypatch.setattr("sase.agent.bead_display._lookup_bead_issue", lookup)

        header, _ = build_header_text(
            agent,
            cheap=False,
            summary=build_detail_header_summary(agent),
        )

        assert seen_project_names == ["zorg"]
        assert (
            "Name: @zorg-4.3.6\n"
            "Bead: zorg-4.3.6 - Phase 6: count() MVP And Final Epic Hardening\n"
        ) in header.plain

    def test_full_header_uses_agent_workspace_before_project_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = tmp_path / "sase"
        agent_workspace = tmp_path / "bob-cli"
        project_dir = tmp_path / ".sase" / "projects" / "home"
        (current / "sdd/beads").mkdir(parents=True)
        (agent_workspace / "sdd/beads").mkdir(parents=True)
        project_dir.mkdir(parents=True)
        _write_issues(
            current / "sdd/beads",
            [
                _issue(
                    "bob-cli-1.4",
                    "Wrong current project title",
                    "2026-06-01T00:00:00Z",
                )
            ],
        )
        _write_issues(
            agent_workspace / "sdd/beads",
            [
                _issue(
                    "bob-cli-1.4",
                    "Workspace phase title",
                    "2026-06-01T00:00:01Z",
                )
            ],
        )
        monkeypatch.chdir(current)
        agent = make_agent(
            agent_name="bob-cli-1.4",
            project_file=str(project_dir / "home.sase"),
            workspace_dir=str(agent_workspace),
        )

        header, _ = build_header_text(
            agent,
            cheap=False,
            summary=build_detail_header_summary(agent),
        )

        assert (
            "Name: @bob-cli-1.4\nBead: bob-cli-1.4 - Workspace phase title\n"
        ) in header.plain

    def test_full_header_falls_back_for_empty_bead_description(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: Issue(
                id=bead_id,
                title="Phase title",
                description=" \n\t ",
            ),
        )

        header, _ = build_header_text(
            agent,
            cheap=False,
            summary=build_detail_header_summary(agent),
        )

        assert "Name: @sase-x.3\nBead: sase-x.3 - Phase title\n" in header.plain

    def test_full_header_falls_back_for_missing_bead(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: None,
        )

        header, _ = build_header_text(
            agent,
            cheap=False,
            summary=build_detail_header_summary(agent),
        )

        assert "Name: @sase-x.3\nBead: sase-x.3\n" in header.plain

    def test_cheap_header_does_not_lookup_bead_description(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")

        def fail_lookup(bead_id: str) -> Issue | None:
            raise AssertionError("cheap header must not touch bead storage")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            fail_lookup,
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @sase-x.3\nBead: sase-x.3\n" in header.plain

    def test_full_land_header_uses_plan_title_when_description_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.land")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: Issue(
                id=bead_id,
                title=" Make `sase bead` Fast With `sase-core` ",
                description=" \n\t ",
            ),
        )

        header, _ = build_header_text(
            agent,
            cheap=False,
            summary=build_detail_header_summary(agent),
        )

        assert (
            "Name: @sase-x.land\n"
            "Bead: sase-x - Land epic: Make `sase bead` Fast With `sase-core`\n"
        ) in header.plain

    def test_full_exact_land_header_uses_epic_title_when_description_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: Issue(
                id=bead_id,
                title=" Make `sase bead` Fast With `sase-core` ",
                issue_type=IssueType.PLAN,
                tier=BeadTier.EPIC,
                description=" \n\t ",
            ),
        )

        header, _ = build_header_text(
            agent,
            cheap=False,
            summary=build_detail_header_summary(agent),
        )

        assert (
            "Name: @sase-x\n"
            "Bead: sase-x - Land epic: Make `sase bead` Fast With `sase-core`\n"
        ) in header.plain

    def test_full_land_header_prefers_explicit_plan_description(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.land")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: Issue(
                id=bead_id,
                title="Plan title",
                description="Use the explicit plan description",
            ),
        )

        header, _ = build_header_text(
            agent,
            cheap=False,
            summary=build_detail_header_summary(agent),
        )

        assert (
            "Name: @sase-x.land\nBead: sase-x - Use the explicit plan description\n"
        ) in header.plain


def _write_issues(beads_dir: Path, issues: list[dict[str, object]]) -> None:
    text = "".join(json.dumps(issue, separators=(",", ":")) + "\n" for issue in issues)
    (beads_dir / "issues.jsonl").write_text(text, encoding="utf-8")


def _issue(issue_id: str, title: str, updated_at: str) -> dict[str, object]:
    return {
        "id": issue_id,
        "title": title,
        "status": "open",
        "issue_type": "plan",
        "parent_id": None,
        "owner": "",
        "assignee": "",
        "created_at": updated_at,
        "created_by": "",
        "updated_at": updated_at,
        "closed_at": None,
        "close_reason": None,
        "description": "",
        "notes": "",
        "design": "",
        "is_ready_to_work": False,
        "changespec_name": "",
        "changespec_bug_id": "",
        "dependencies": [],
    }
