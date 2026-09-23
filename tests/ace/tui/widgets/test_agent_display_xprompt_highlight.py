"""Tests for terminal agent xprompt syntax highlighting and caching."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rich.text import Text

from sase import project_display_names as pdn
from sase.ace.tui.util.artifact_ref_syntax import artifact_ref_style_palette_from_theme
from sase.ace.tui.util.xprompt_syntax import XPROMPT_TOKEN_STYLES

from tests.ace.tui.widgets._agent_display_helpers import (
    FakePromptPanel,
    make_artifact_agent,
    plain_of,
)
from tests.ace.tui.widgets._agent_display_xprompt_helpers import (
    _header_text,
    _last_style_at,
    _styles_at,
)


class TestAgentXPromptHighlighting:
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

    def test_agent_xprompt_body_renders_project_tags_with_accents(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        from sase.project_tags.catalog import ProjectTagCatalog, ProjectTagTarget

        monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})
        monkeypatch.setattr(
            pdn,
            "_project_display_name_map_cached",
            lambda *_args, **_kwargs: {"gh_acme__widgets": "widgets"},
        )
        monkeypatch.setattr(
            "sase.project_tags.catalog.peek_project_tag_catalog",
            lambda: ProjectTagCatalog(
                targets=(
                    ProjectTagTarget(
                        key="gh_acme__widgets",
                        name="widgets",
                        tag="+widgets",
                        workflow_type="gh",
                        accent="#C75A31",
                    ),
                ),
                accent_palette=(),
                signature="tag-test",
            ),
        )
        panel = FakePromptPanel()
        agent = make_artifact_agent(
            tmp_path,
            status="DONE",
            raw_xprompt="#gh:gh_acme__widgets fix the bug",
        )
        agent.project_file = "/tmp/projects/gh_acme__widgets/gh_acme__widgets.sase"
        agent.project_display_name = "widgets"

        panel.update_display(agent)

        plain = plain_of(panel.captured[-1])
        assert "+widgets fix the bug" in plain
        assert "#gh:gh_acme__widgets" not in plain

        header = _header_text(panel.captured[-1])
        assert "dim #C75A31" in _styles_at(header, "+widgets")
        assert "bold #C75A31" in _styles_at(header, "widgets")

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
