"""Tests for agent display artifact metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.models._loaders._meta_enrichment import enrich_agent_from_meta
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_detail_header_summary,
    build_header_text,
    cache_detail_header_summary,
)
from tests.ace.tui.widgets._agent_display_helpers import (
    FakePromptPanel,
    make_agent,
    plain_of,
)


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
        enrich_agent_from_meta(agent, str(artifacts_dir))

        header, _ = build_header_text(
            agent,
            cheap=False,
            summary=build_detail_header_summary(agent),
        )

        assert header.plain.index("SASE CONTEXT") < header.plain.index("▸ PLAN")
        assert header.plain.index("▸ PLAN") < header.plain.index("▸ ARTIFACTS")
        assert header.plain.index("▸ ARTIFACTS") < header.plain.index("Deltas:\n")
        assert header.plain.index("Deltas:\n") < header.plain.index("Artifacts:\n")
        assert "SASE PLAN" not in header.plain
        assert "DELTAS:" not in header.plain
        assert "ARTIFACTS:" not in header.plain
        assert "Artifacts: 2" not in header.plain
        assert "ARTIFACTS: 2" not in header.plain
        assert "(chat, image)" not in header.plain
        assert "Path: ~/.sase/plans/202605/approved_plan.md" in header.plain
        assert "  ▤ ~/.sase/plans/202605/approved_plan.md\n" not in header.plain
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

        assert "Artifacts:" not in header.plain
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
        sdd_plan = workspace / "sdd" / "plans" / "202605" / "plan.md"
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
        enrich_agent_from_meta(agent, str(artifacts_dir))

        header, _ = build_header_text(
            agent,
            cheap=False,
            summary=build_detail_header_summary(agent),
        )

        assert "SASE CONTEXT" in header.plain
        assert "▸ PLAN" in header.plain
        assert "SASE PLAN" not in header.plain
        assert "Path: ~/.sase/plans/202605/plan.md" in header.plain
        assert "sdd/plans/202605/plan.md" not in header.plain

    def test_committed_plan_uses_workspace_relative_path_and_hint_mapping(
        self,
        tmp_path: Path,
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        workspace = tmp_path / "workspace"
        archived_plan = tmp_path / "home" / ".sase" / "plans" / "202605" / "plan.md"
        sdd_plan = workspace / "sdd" / "plans" / "202605" / "plan.md"
        artifacts_dir.mkdir()
        archived_plan.parent.mkdir(parents=True)
        sdd_plan.parent.mkdir(parents=True)
        archived_plan.write_text("# Archived", encoding="utf-8")
        sdd_plan.write_text("# SDD", encoding="utf-8")
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
            diff_path=str(diff_path),
        )
        enrich_agent_from_meta(agent, str(artifacts_dir))
        panel = FakePromptPanel()
        cache_detail_header_summary(
            panel,
            agent,
            build_detail_header_summary(agent),
        )

        result = panel.update_display_with_hints(agent)

        plain = plain_of(panel.captured[-1])
        assert "SASE CONTEXT" in plain
        assert "▸ PLAN" in plain
        assert "SASE PLAN" not in plain
        assert "Path: [1] sdd/plans/202605/plan.md\n" in plain
        assert "  Deltas:\n    ~ [2] src/foo.py  ~1\n" in plain
        assert "Artifacts:" not in plain
        assert "ARTIFACTS:" not in plain
        assert result.file_hints[1] == str(sdd_plan)
        assert result.file_hints[2] == str(workspace / "src/foo.py")
