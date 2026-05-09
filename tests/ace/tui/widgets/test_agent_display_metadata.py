"""Tests for agent display header, bead, and artifact metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.models.agent_bead import derive_agent_bead_id
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_header_text,
    get_phase_label,
)
from sase.bead.model import BeadTier, Issue, IssueType
from tests.ace.tui.widgets._agent_display_helpers import (
    FakePromptPanel,
    make_agent,
    plain_of,
)


class TestGetPhaseLabel:
    def test_plan(self) -> None:
        agent = make_agent(role_suffix=".plan")
        assert get_phase_label(agent) == "PLANNER"

    def test_code(self) -> None:
        agent = make_agent(role_suffix=".code")
        assert get_phase_label(agent) == "CODER"

    def test_questions(self) -> None:
        agent = make_agent(role_suffix=".q")
        assert get_phase_label(agent) == "QUESTIONS"

    def test_epic(self) -> None:
        agent = make_agent(role_suffix=".epic")
        assert get_phase_label(agent) == "EPIC"

    def test_feedback_round_2(self) -> None:
        agent = make_agent(role_suffix=".2")
        assert get_phase_label(agent) == "PLANNER (round 2)"

    def test_feedback_round_10(self) -> None:
        agent = make_agent(role_suffix=".10")
        assert get_phase_label(agent) == "PLANNER (round 10)"

    def test_no_suffix(self) -> None:
        agent = make_agent(role_suffix=None)
        assert get_phase_label(agent) == "AGENT"

    def test_unknown_suffix(self) -> None:
        agent = make_agent(role_suffix=".xyz")
        assert get_phase_label(agent) == "AGENT"


# -- derive_agent_bead_id / header metadata ----------------------------------


class TestAgentBeadMetadata:
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

        header, _ = build_header_text(agent, cheap=False)

        assert "Name: @sase-x.3\nBead: sase-x.3 - First line second line\n" in (
            header.plain
        )

    def test_full_header_passes_agent_project_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(
            agent_name="zorg-4.3.6",
            project_file="/home/me/.sase/projects/zorg/zorg.gp",
        )
        seen_project_names: list[str | None] = []

        def lookup(bead_id: str, *, project_name: str | None = None) -> Issue | None:
            seen_project_names.append(project_name)
            return Issue(
                id=bead_id,
                title="Phase 6: count() MVP And Final Epic Hardening",
                description="",
            )

        monkeypatch.setattr("sase.agent.bead_display._lookup_bead_issue", lookup)

        header, _ = build_header_text(agent, cheap=False)

        assert seen_project_names == ["zorg"]
        assert (
            "Name: @zorg-4.3.6\n"
            "Bead: zorg-4.3.6 - Phase 6: count() MVP And Final Epic Hardening\n"
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

        header, _ = build_header_text(agent, cheap=False)

        assert "Name: @sase-x.3\nBead: sase-x.3 - Phase title\n" in header.plain

    def test_full_header_falls_back_for_missing_bead(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = make_agent(agent_name="sase-x.3")

        monkeypatch.setattr(
            "sase.agent.bead_display._lookup_bead_issue",
            lambda bead_id, **_: None,
        )

        header, _ = build_header_text(agent, cheap=False)

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

        header, _ = build_header_text(agent, cheap=False)

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

        header, _ = build_header_text(agent, cheap=False)

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

        header, _ = build_header_text(agent, cheap=False)

        assert (
            "Name: @sase-x.land\nBead: sase-x - Use the explicit plan description\n"
        ) in header.plain


class TestAgentArtifactMetadata:
    def test_full_header_renders_artifact_paths_after_deltas(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        artifacts_dir = (
            tmp_path
            / ".sase"
            / "projects"
            / "proj"
            / "artifacts"
            / "ace-run"
            / "20260507120000"
        )
        artifacts_dir.mkdir(parents=True)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        plan = home / ".sase" / "plans" / "202605" / "approved_plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# Plan", encoding="utf-8")
        chat = tmp_path / "chat.md"
        image = tmp_path / "image.png"
        prompt_image = workspace / "screenshots" / "prompt.jpg"
        explicit_source = tmp_path / "notes.md"
        generated_pdf = artifacts_dir / "markdown_pdfs" / "approved_plan.pdf"
        explicit_pdf_source = tmp_path / "manual_artifact.pdf"
        diff_path = tmp_path / "agent.diff"
        chat.write_text("chat", encoding="utf-8")
        image.write_bytes(b"png")
        prompt_image.parent.mkdir(parents=True)
        prompt_image.write_bytes(b"jpg")
        explicit_source.write_text("notes", encoding="utf-8")
        generated_pdf.parent.mkdir(parents=True)
        generated_pdf.write_bytes(b"pdf")
        explicit_pdf_source.write_bytes(b"pdf")
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
        from sase.core.agent_artifact_facade import store_explicit_agent_artifact

        explicit = store_explicit_agent_artifact(explicit_source, artifacts_dir)
        store_explicit_agent_artifact(
            explicit_pdf_source,
            artifacts_dir,
            kind="pdf",
        )
        (artifacts_dir / "done.json").write_text(
            json.dumps(
                {
                    "response_path": str(chat),
                    "workspace_dir": str(workspace),
                    "image_paths": [str(image)],
                    "markdown_pdf_paths": [str(generated_pdf)],
                }
            ),
            encoding="utf-8",
        )
        (artifacts_dir / "raw_xprompt.md").write_text(
            "Compare this prompt image: screenshots/prompt.jpg\n",
            encoding="utf-8",
        )
        (artifacts_dir / "plan_path.json").write_text(
            json.dumps({"plan_path": str(plan)}),
            encoding="utf-8",
        )
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps({"plan_path": str(plan), "plan_committed": False}),
            encoding="utf-8",
        )
        agent = make_agent(
            status="DONE",
            artifacts_dir=str(artifacts_dir),
            workspace_dir=str(workspace),
            diff_path=str(diff_path),
        )

        header, _ = build_header_text(agent, cheap=False)

        assert header.plain.index("DELTAS:\n") < header.plain.index("ARTIFACTS:\n")
        assert "ARTIFACTS: 2" not in header.plain
        assert "(chat, image)" not in header.plain
        assert "  • ~/.sase/plans/202605/approved_plan.md\n" in header.plain
        assert "~/.sase/plans/202605/approved_plan.md" in header.plain
        assert explicit.path.replace(str(home), "~") in header.plain
        assert "chat.md" not in header.plain
        assert "image.png" in header.plain
        assert "screenshots/prompt.jpg" in header.plain
        assert "approved_plan.pdf" not in header.plain
        assert "manual_artifact" not in header.plain

    def test_cheap_header_omits_artifact_summary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        agent = make_agent(status="DONE", artifacts_dir="/tmp/artifacts")

        def fail_get_artifacts_dir() -> str | None:
            raise AssertionError("cheap header must not inspect artifacts")

        monkeypatch.setattr(agent, "get_artifacts_dir", fail_get_artifacts_dir)

        header, _ = build_header_text(agent, cheap=True)

        assert "ARTIFACTS:" not in header.plain

    def test_uncommitted_plan_prefers_archived_plan_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        artifacts_dir = tmp_path / "artifacts"
        workspace = tmp_path / "workspace"
        archived_plan = home / ".sase" / "plans" / "202605" / "plan.md"
        sdd_plan = workspace / "sdd" / "tales" / "202605" / "plan.md"
        artifacts_dir.mkdir()
        archived_plan.parent.mkdir(parents=True)
        sdd_plan.parent.mkdir(parents=True)
        archived_plan.write_text("# Archived", encoding="utf-8")
        sdd_plan.write_text("# SDD", encoding="utf-8")
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps(
                {
                    "plan_path": str(archived_plan),
                    "sdd_plan_path": str(sdd_plan),
                    "plan_committed": False,
                }
            ),
            encoding="utf-8",
        )
        agent = make_agent(
            status="DONE",
            artifacts_dir=str(artifacts_dir),
            workspace_dir=str(workspace),
        )

        header, _ = build_header_text(agent, cheap=False)

        assert "~/.sase/plans/202605/plan.md" in header.plain
        assert "sdd/tales/202605/plan.md" not in header.plain

    def test_committed_plan_uses_workspace_relative_path_and_hint_mapping(
        self,
        tmp_path: Path,
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        workspace = tmp_path / "workspace"
        archived_plan = tmp_path / "home" / ".sase" / "plans" / "202605" / "plan.md"
        sdd_plan = workspace / "sdd" / "tales" / "202605" / "plan.md"
        artifacts_dir.mkdir()
        archived_plan.parent.mkdir(parents=True)
        sdd_plan.parent.mkdir(parents=True)
        archived_plan.write_text("# Archived", encoding="utf-8")
        sdd_plan.write_text("# SDD", encoding="utf-8")
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps(
                {
                    "plan_path": str(archived_plan),
                    "sdd_plan_path": str(sdd_plan),
                    "plan_committed": True,
                }
            ),
            encoding="utf-8",
        )
        agent = make_agent(
            status="DONE",
            artifacts_dir=str(artifacts_dir),
            workspace_dir=str(workspace),
        )
        panel = FakePromptPanel()

        mappings = panel.update_display_with_hints(agent)

        plain = plain_of(panel.captured[-1])
        assert "ARTIFACTS:\n  • [1] sdd/tales/202605/plan.md\n" in plain
        assert mappings[1] == str(sdd_plan)


# -- agent list bead badge ----------------------------------------------------
