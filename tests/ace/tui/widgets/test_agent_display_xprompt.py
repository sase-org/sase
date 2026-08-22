"""Tests for terminal agent xprompt rendering."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from rich.console import Group
from rich.text import Text

from sase import project_display_names as pdn
from sase.ace.tui.util.lazy_syntax import (
    MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES,
    CachedRenderable,
)
from sase.ace.tui.util.artifact_ref_syntax import artifact_ref_style_palette_from_theme
from sase.ace.tui.util.xprompt_syntax import XPROMPT_TOKEN_STYLES
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from sase.ace.tui.widgets.prompt_panel._hint_caps import HintContentBudget

from tests.ace.tui.widgets._agent_display_helpers import (
    FakePromptPanel,
    make_artifact_agent,
    plain_of,
)
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_logical_section_is_compact,
    assert_rendered_section_is_compact,
)


def _header_text(renderable: object) -> Text:
    if isinstance(renderable, CachedRenderable):
        renderable = renderable.renderable
    if isinstance(renderable, Text):
        return renderable
    assert isinstance(renderable, Group)
    header = renderable.renderables[0]
    assert isinstance(header, Text)
    return header


def _styles_at(text: Text, needle: str, *, offset: int = 0) -> set[str]:
    position = text.plain.index(needle) + offset
    return {
        str(span.style)
        for span in text.spans
        if span.start <= position < span.end and span.style is not None
    }


def _last_style_at(text: Text, needle: str, *, offset: int = 0) -> str | None:
    position = text.plain.index(needle) + offset
    styles = [
        str(span.style)
        for span in text.spans
        if span.start <= position < span.end and span.style is not None
    ]
    return styles[-1] if styles else None


class TestAgentXPromptRendering:
    def test_done_agent_renders_raw_xprompt(self, tmp_path: Path) -> None:
        panel = FakePromptPanel()
        agent = make_artifact_agent(tmp_path, status="DONE")

        panel.update_display(agent)

        plain = plain_of(panel.captured[-1])
        assert "AGENT XPROMPT" in plain
        assert "Launch from @src/raw.py" in plain
        assert "AGENT PROMPT" in plain
        assert "AGENT CHAT" in plain
        rendered = panel.captured[-1]
        assert_rendered_section_is_compact(
            rendered,
            "AGENT XPROMPT",
            "Launch from @src/raw.py",
        )
        assert_rendered_section_is_compact(
            rendered,
            "AGENT PROMPT",
            "Expanded prompt body",
        )
        assert_rendered_section_is_compact(
            rendered,
            "AGENT CHAT",
            "Final response body",
        )

    def test_failed_agent_renders_raw_xprompt(self, tmp_path: Path) -> None:
        panel = FakePromptPanel()
        agent = make_artifact_agent(tmp_path, status="FAILED")

        panel.update_display(agent)

        plain = plain_of(panel.captured[-1])
        assert "AGENT XPROMPT" in plain
        assert "Launch from @src/raw.py" in plain
        assert "AGENT PROMPT" in plain
        assert "AGENT CHAT" in plain

    def test_agent_xprompt_body_uses_logical_project_name(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})
        monkeypatch.setattr(
            pdn,
            "_project_display_name_map_cached",
            lambda *_args, **_kwargs: {"gh_acme__widgets": "widgets"},
        )
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            raw_xprompt=(
                "#gh:gh_acme__widgets fix\n"
                "#gh(gh_acme__widgets) inspect\n"
                "path: /tmp/gh_acme__widgets/file"
            ),
        )
        agent.project_file = "/tmp/projects/gh_acme__widgets/gh_acme__widgets.sase"
        agent.project_display_name = "widgets"

        panel.update_display(agent)

        plain = plain_of(panel.captured[-1])
        assert "#gh:widgets fix" in plain
        assert "#gh(widgets) inspect" in plain
        assert "path: /tmp/gh_acme__widgets/file" in plain
        assert "#gh:gh_acme__widgets fix" not in plain

        header = _header_text(panel.captured[-1])
        assert XPROMPT_TOKEN_STYLES["invocation"] in _styles_at(
            header,
            "#gh:widgets",
        )

    def test_agent_xprompt_highlights_warm_catalog_skills(
        self,
        tmp_path: Path,
    ) -> None:
        calls: list[tuple[str | None, bool]] = []

        def _entries(
            project: str | None,
            *,
            schedule: bool,
        ) -> list[SimpleNamespace]:
            calls.append((project, schedule))
            return [
                SimpleNamespace(
                    name="skill/sase_plan",
                    skill_name="sase_plan",
                    is_skill=True,
                )
            ]

        panel = FakePromptPanel()
        panel.app = SimpleNamespace(get_prompt_catalog_assist_entries=_entries)
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            raw_xprompt="#git:sase Use /sase_plan",
        )

        panel.update_display(agent)

        header = _header_text(panel.captured[-1])
        assert XPROMPT_TOKEN_STYLES["skill"] in _styles_at(header, "/sase_plan")
        assert calls == [("sase", True)]

    def test_agent_xprompt_highlights_inline_code_after_humanizing(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})
        monkeypatch.setattr(
            pdn,
            "_project_display_name_map_cached",
            lambda *_args, **_kwargs: {"gh_acme__widgets": "widgets"},
        )
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            raw_xprompt="#gh:gh_acme__widgets Run `pytest`",
        )
        agent.project_file = "/tmp/projects/gh_acme__widgets/gh_acme__widgets.sase"
        agent.project_display_name = "widgets"

        panel.update_display(agent)

        header = _header_text(panel.captured[-1])
        assert "AGENT XPROMPT\n#gh:widgets Run `pytest`" in header.plain
        assert any("#e6db74" in style for style in _styles_at(header, "pytest"))

    def test_agent_xprompt_highlights_artifact_refs_after_xprompt_args(
        self,
        tmp_path: Path,
    ) -> None:
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            raw_xprompt=("#work(@plans:202608/design.md#L12) and `@plans:literal.md`"),
        )

        panel.update_display(agent)

        header = _header_text(panel.captured[-1])
        palette = artifact_ref_style_palette_from_theme(None)
        assert XPROMPT_TOKEN_STYLES["invocation"] in _styles_at(header, "#work")
        assert _last_style_at(header, "plans") == str(palette.style_for_key("kind"))
        assert _last_style_at(header, "202608/design.md") == str(
            palette.style_for_key("payload")
        )
        assert _last_style_at(header, "#L12") == str(palette.style_for_key("fragment"))
        literal_offset = header.plain.index("literal")
        assert str(palette.style_for_key("payload")) not in {
            str(span.style)
            for span in header.spans
            if span.start <= literal_offset < span.end and span.style is not None
        }

    def test_xprompt_highlight_cache_invalidates_when_ref_theme_changes(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from sase.ace.tui.widgets.prompt_panel import _agent_display_render

        original = _agent_display_render.highlight_prompt_text
        calls = 0

        def _counted(
            text: str,
            *,
            known_skills: frozenset[str] = frozenset(),
            **kwargs: object,
        ) -> Text:
            nonlocal calls
            calls += 1
            return original(text, known_skills=known_skills, **kwargs)

        panel = FakePromptPanel()
        panel.app = SimpleNamespace(
            current_theme=SimpleNamespace(
                secondary="#335577",
                success="#00aa66",
                accent="#9955cc",
                error="#cc3344",
                foreground="#ffffff",
                background="#000000",
            )
        )
        monkeypatch.setattr(
            _agent_display_render,
            "highlight_prompt_text",
            _counted,
        )
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            raw_xprompt="@plans:202608/design.md",
        )

        panel.update_display(agent)
        panel.update_display(agent)
        assert calls == 1

        panel.app.current_theme = SimpleNamespace(
            secondary="#335577",
            success="#00aa66",
            accent="#9955cc",
            error="#cc3344",
            foreground="#000000",
            background="#ffffff",
        )
        panel.update_display(agent)
        assert calls == 2

    def test_agent_prompt_and_chat_use_logical_project_name(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})
        monkeypatch.setattr(
            pdn,
            "_project_display_name_map_cached",
            lambda *_args, **_kwargs: {"gh_acme__widgets": "widgets"},
        )
        panel = FakePromptPanel()
        agent = make_artifact_agent(tmp_path, status="DONE")
        Path(agent.artifacts_dir, "01_prompt.md").write_text(
            "Prompt says #gh:gh_acme__widgets inspect.\n",
            encoding="utf-8",
        )
        Path(agent.response_path).write_text(
            "Response echoes #gh:gh_acme__widgets now.\n",
            encoding="utf-8",
        )

        panel.update_display(agent)

        plain = plain_of(panel.captured[-1])
        assert "Prompt says #gh:widgets inspect." in plain
        assert "Response echoes #gh:widgets now." in plain
        assert "#gh:gh_acme__widgets" not in plain

    def test_hint_mode_prompt_and_chat_use_logical_project_name(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})
        monkeypatch.setattr(
            pdn,
            "_project_display_name_map_cached",
            lambda *_args, **_kwargs: {"gh_acme__widgets": "widgets"},
        )
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            raw_xprompt="#gh:gh_acme__widgets raw",
        )
        Path(agent.artifacts_dir, "01_prompt.md").write_text(
            "#gh:gh_acme__widgets prompt\n",
            encoding="utf-8",
        )
        Path(agent.response_path).write_text(
            "#gh:gh_acme__widgets response\n",
            encoding="utf-8",
        )

        panel.update_display_with_hints(agent)

        plain = plain_of(panel.captured[-1])
        assert "#gh:widgets raw" in plain
        assert "#gh:widgets prompt" in plain
        assert "#gh:widgets response" in plain
        assert "#gh:gh_acme__widgets" not in plain

    def test_custom_family_reply_summaries_include_member_ids(
        self,
        tmp_path: Path,
    ) -> None:
        root_base = tmp_path / "root"
        followup_base = tmp_path / "followup"
        root_base.mkdir()
        followup_base.mkdir()
        root = make_artifact_agent(root_base, status="DONE")
        followup = make_artifact_agent(followup_base, status="DONE")
        root.role_suffix = "--0"
        root.agent_family_role = "root"
        root.plan_chain_root = False
        root.raw_suffix = "20240101142345-root"
        followup.role_suffix = "--bar"
        followup.agent_family_role = "bar"
        followup.raw_suffix = "20240101142345-bar"
        followup.parent_timestamp = root.raw_suffix
        root.followup_agents = [followup]

        panel = FakePromptPanel()
        panel.update_display(root)
        plain = plain_of(panel.captured[-1])

        assert "AGENT REPLY · 2" in plain
        assert "▾ AGENT REPLY" not in plain
        assert "AGENT (0) · ✓ DONE" in plain
        assert "AGENT (bar) · ✓ DONE" in plain
        assert "AGENT (q)" not in plain

    def test_hint_mode_custom_family_reply_summaries_include_member_ids(
        self,
        tmp_path: Path,
    ) -> None:
        root_base = tmp_path / "root"
        followup_base = tmp_path / "followup"
        root_base.mkdir()
        followup_base.mkdir()
        root = make_artifact_agent(root_base, status="DONE")
        followup = make_artifact_agent(followup_base, status="DONE")
        root.role_suffix = "--0"
        root.agent_family_role = "root"
        root.plan_chain_root = False
        root.raw_suffix = "20240101142345-root"
        followup.role_suffix = "--bar"
        followup.agent_family_role = "bar"
        followup.raw_suffix = "20240101142345-bar"
        followup.parent_timestamp = root.raw_suffix
        root.followup_agents = [followup]

        panel = FakePromptPanel()
        panel.update_display_with_hints(root)
        plain = plain_of(panel.captured[-1])

        assert "AGENT REPLY · 2" in plain
        assert "▾ AGENT REPLY" not in plain
        assert "AGENT (0) · ✓ DONE" in plain
        assert "AGENT (bar) · ✓ DONE" in plain
        assert "AGENT (q)" not in plain

    def test_running_reply_placeholders_are_compact(self, tmp_path: Path) -> None:
        panel = FakePromptPanel()
        agent = make_artifact_agent(tmp_path, status="RUNNING")

        panel.update_display(agent)
        assert_rendered_section_is_compact(
            panel.captured[-1],
            "AGENT REPLY",
            "Waiting for agent response...",
        )

        panel.update_display_with_hints(agent)
        assert_logical_section_is_compact(
            panel.captured[-1],
            "AGENT REPLY",
            "Waiting for agent response...",
        )
        assert_rendered_section_is_compact(
            panel.captured[-1],
            "AGENT REPLY",
            "Waiting for agent response...",
        )

    def test_hint_mode_renders_raw_xprompt_for_terminal_agent(
        self,
        tmp_path: Path,
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            workspace_dir=str(workspace_dir),
        )

        result = panel.update_display_with_hints(agent)

        rendered = panel.captured[-1]
        plain = plain_of(rendered)
        assert "AGENT XPROMPT" in plain
        assert "[1] @src/raw.py" in plain
        assert result.file_hints[1] == str(workspace_dir / "src/raw.py")
        assert_logical_section_is_compact(
            rendered,
            "AGENT XPROMPT",
            "Launch from [1] @src/raw.py",
        )
        assert_logical_section_is_compact(
            rendered,
            "AGENT PROMPT",
            "Expanded prompt body",
        )
        assert_logical_section_is_compact(
            rendered,
            "AGENT CHAT",
            "Final response body",
        )
        assert_rendered_section_is_compact(
            rendered,
            "AGENT CHAT",
            "Final response body",
        )

    def test_hint_mode_preserves_hints_and_adds_xprompt_overlays(
        self,
        tmp_path: Path,
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            workspace_dir=str(workspace_dir),
            raw_xprompt="#work(@src/raw.py) %auto",
        )

        result = panel.update_display_with_hints(agent)

        rendered = _header_text(panel.captured[-1])
        assert "#work([1] @src/raw.py) %auto" in rendered.plain
        assert result.file_hints[1] == str(workspace_dir / "src/raw.py")
        assert XPROMPT_TOKEN_STYLES["invocation"] in _styles_at(rendered, "#work")
        assert XPROMPT_TOKEN_STYLES["directive"] in _styles_at(rendered, "%auto")
        assert "bold #FFFF00" in _styles_at(rendered, "[1]")
        assert "#87AFFF" in _styles_at(rendered, "@src/raw.py")
        assert_logical_section_is_compact(
            rendered,
            "AGENT XPROMPT",
            "#work([1] @src/raw.py) %auto",
        )

    def test_hint_mode_keeps_typed_artifact_refs_semantic(
        self,
        tmp_path: Path,
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            workspace_dir=str(workspace_dir),
            raw_xprompt="#work(@plans:202608/design.md#L12) and @src/raw.py",
        )

        result = panel.update_display_with_hints(agent)

        rendered = _header_text(panel.captured[-1])
        assert "#work(@plans:202608/design.md#L12) and [1] @src/raw.py" in (
            rendered.plain
        )
        assert result.file_hints == {1: str(workspace_dir / "src/raw.py")}
        assert "[1] 202608/design.md" not in rendered.plain
        assert _last_style_at(rendered, "plans") == str(
            artifact_ref_style_palette_from_theme(None).style_for_key("kind")
        )

    def test_family_hint_xprompt_keeps_typed_artifact_refs_semantic(
        self,
        tmp_path: Path,
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            workspace_dir=str(workspace_dir),
            raw_xprompt="#work(@plans:202608/design.md#L12) and @src/raw.py",
        )
        hint_state = HeaderHintState(
            hint_counter=1,
            hint_mappings={},
            workspace_dir=str(workspace_dir),
            tool_call_reports={},
        )

        text = panel._family_text_with_hints(
            "#work(@plans:202608/design.md#L12) and @src/raw.py",
            hint_state,
            workspace_dir=str(workspace_dir),
            budget=HintContentBudget(),
            xprompt_agent=agent,
            raw_xprompt=agent.get_raw_xprompt_content(),
        )

        assert text.plain == "#work(@plans:202608/design.md#L12) and [1] @src/raw.py"
        assert hint_state.hint_mappings == {1: str(workspace_dir / "src/raw.py")}
        assert _last_style_at(text, "plans") == str(
            artifact_ref_style_palette_from_theme(None).style_for_key("kind")
        )

    def test_hint_mode_skips_paths_inside_http_urls(
        self,
        tmp_path: Path,
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        url = (
            "https://github.com/sase-org/sase--beads/blob/main/pages/sase-d9/README.md"
        )
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            workspace_dir=str(workspace_dir),
            raw_xprompt="Review the linked bead",
        )
        Path(agent.response_path).write_text(
            f"Read {url}, then open docs/local.md.\n",
            encoding="utf-8",
        )

        result = panel.update_display_with_hints(agent)
        plain = plain_of(panel.captured[-1])

        assert url in plain
        assert result.file_hints == {1: str(workspace_dir / "docs/local.md")}
        assert f"Read {url}, then open [1] docs/local.md." in plain

    def test_oversized_xprompt_falls_back_to_plain_text(
        self,
        tmp_path: Path,
    ) -> None:
        panel = FakePromptPanel()
        raw_xprompt = "#foo " + "x" * MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            raw_xprompt=raw_xprompt,
        )

        panel.update_display(agent)

        header = _header_text(panel.captured[-1])
        assert raw_xprompt in header.plain
        assert XPROMPT_TOKEN_STYLES["invocation"] not in _styles_at(header, "#foo")

    def test_xprompt_highlight_cache_reuses_content_and_resets_for_new_agent(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from sase.ace.tui.widgets.prompt_panel import _agent_display_render

        original = _agent_display_render.highlight_prompt_text
        calls = 0

        def _counted(
            text: str,
            *,
            known_skills: frozenset[str] = frozenset(),
            **kwargs: object,
        ) -> Text:
            nonlocal calls
            calls += 1
            return original(text, known_skills=known_skills, **kwargs)

        monkeypatch.setattr(
            _agent_display_render,
            "highlight_prompt_text",
            _counted,
        )
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            raw_xprompt="#foo %auto",
        )

        panel.update_display(agent)
        panel.update_display(agent)
        assert calls == 1

        agent.cl_name = "new-agent-identity"
        panel.update_display(agent)
        assert calls == 2

    def test_hint_mode_renders_timestamp_file_hints_before_body_hints(
        self,
        tmp_path: Path,
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            workspace_dir=str(workspace_dir),
        )
        Path(agent.artifacts_dir, "01_prompt.md").write_text(
            "Expanded prompt mentions src/prompt.py\n",
            encoding="utf-8",
        )
        feedback_time = datetime(2024, 1, 1, 14, 25, 0)
        rejected_plan_path = (
            Path.home() / ".sase" / "plans" / "202605" / "wait_requires_success.md"
        )
        expected_hint_path = os.path.expanduser(
            "~/.sase/plans/202605/wait_requires_success.md"
        )
        agent.feedback_times = [feedback_time]
        agent.feedback_plan_paths = {feedback_time: str(rejected_plan_path)}

        result = panel.update_display_with_hints(agent)

        plain = plain_of(panel.captured[-1])
        assert "[1] ~/.sase/plans/202605/wait_requires_success.md" in plain
        assert "[2] @src/raw.py" in plain
        assert "[3] src/prompt.py" in plain
        assert result.file_hints[1] == expected_hint_path
        assert result.file_hints[2] == str(workspace_dir / "src/raw.py")
        assert result.file_hints[3] == str(workspace_dir / "src/prompt.py")


# -- _get_phase_label ---------------------------------------------------------
