"""Authored-prompt glossary/repo highlighting for the agent metadata panel."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rich.console import Group
from rich.text import Text

from sase.ace.tui.util.lazy_syntax import CachedRenderable
from sase.ace.tui.util.xprompt_syntax import XPROMPT_TOKEN_STYLES
from sase.ace.tui.widgets.prompt_panel._agent_display_header_renderable import (
    AgentHeaderRenderable,
)
from sase.ace.tui.models.agent import AttemptRecord
from sase.ace.tui.widgets.prompt_panel._agent_xprompt_highlighting import (
    _agent_project_and_workspace,
    agent_prompt_highlight_context,
)
from sase.ace.tui.widgets.prompt_panel._workflow_render import (
    build_workflow_detail_renderable,
)
from sase.ace.tui.widgets.prompt_panel._workflow_types import WorkflowDetailSnapshot
from tests.ace.tui.widgets._agent_display_family_helpers import make_family
from tests.ace.tui.widgets._agent_display_helpers import (
    FakePromptPanel,
    make_agent,
    make_artifact_agent,
    plain_of,
)
from tests.ace.tui.widgets._agent_prompt_semantic_helpers import install_panel_semantics
from tests.ace.tui.widgets._prompt_glossary_helpers import dynamic_catalog_for_term
from tests.ace.tui.widgets._prompt_repo_mention_helpers import (
    dynamic_catalog_for_identifier,
)


def _unwrap(renderable: object) -> object:
    if isinstance(renderable, CachedRenderable):
        return renderable.renderable
    return renderable


def _header_text(renderable: object) -> Text | AgentHeaderRenderable:
    renderable = _unwrap(renderable)
    if isinstance(renderable, (Text, AgentHeaderRenderable)):
        return renderable
    assert isinstance(renderable, Group)
    header = renderable.renderables[0]
    assert isinstance(header, (Text, AgentHeaderRenderable))
    return header


def _styles_at(
    text: Text | AgentHeaderRenderable,
    needle: str,
    *,
    offset: int = 0,
) -> set[str]:
    position = text.plain.index(needle) + offset
    return {
        str(span.style)
        for span in text.spans
        if span.start <= position < span.end and span.style is not None
    }


def _has_role_underline(styles: set[str]) -> bool:
    return any(
        "underline" in style and "not underline" not in style for style in styles
    )


def _prompt_body(renderable: object) -> Text:
    renderable = _unwrap(renderable)
    assert isinstance(renderable, Group)
    for child in renderable.renderables[1:]:
        if isinstance(child, Text) and "Agent Clan" in child.plain:
            return child
    raise AssertionError("authored prompt body not found")


def test_resolves_project_from_vcs_tag_then_project_file(
    tmp_path: Path,
) -> None:
    agent = make_artifact_agent(
        tmp_path,
        status="DONE",
        raw_xprompt="#git:sase inspect",
        workspace_dir=str(tmp_path / "ws"),
    )
    project, workspace = _agent_project_and_workspace(
        agent,
        agent.get_raw_xprompt_content() or "",
    )
    assert project == "sase"
    assert workspace == str(tmp_path / "ws")

    tagged = make_agent(
        project_file="/tmp/projects/widgets/widgets.sase",
        workspace_dir=None,
    )
    project, workspace = _agent_project_and_workspace(tagged, "plain prompt")
    assert project == "widgets"
    assert workspace is None


def test_context_schedules_cold_catalogs_and_fingerprints_warm_state(
    tmp_path: Path,
) -> None:
    panel = FakePromptPanel()
    agent = make_artifact_agent(tmp_path, status="DONE", raw_xprompt="#git:sase")
    calls: list[str] = []
    install_panel_semantics(
        panel,
        glossary_warm=False,
        repo_warm=False,
        warm_calls=calls,
    )

    cold = agent_prompt_highlight_context(
        panel,
        agent,
        "#git:sase",
        schedule=True,
    )
    assert cold.glossary_catalog is None
    assert cold.repo_catalog is None
    assert not cold.has_semantic_catalogs
    assert calls == ["glossary", "repo"]
    assert any("cold" in str(part) for part in cold.fingerprint)

    glossary = dynamic_catalog_for_term(tmp_path, "Agent Clan")
    repo = dynamic_catalog_for_identifier(tmp_path, "sase-core")
    install_panel_semantics(panel, glossary=glossary, repo=repo)
    warm = agent_prompt_highlight_context(panel, agent, "#git:sase")
    assert warm.has_semantic_catalogs
    assert warm.fingerprint != cold.fingerprint
    assert warm.styles is not None


def test_agent_xprompt_and_prompt_receive_roles_replies_do_not(
    tmp_path: Path,
) -> None:
    panel = FakePromptPanel()
    source = "Ask Agent Clan to inspect sase-core; run `checks`"
    glossary = dynamic_catalog_for_term(tmp_path, "Agent Clan")
    repo = dynamic_catalog_for_identifier(tmp_path, "sase-core")
    install_panel_semantics(panel, glossary=glossary, repo=repo)
    agent = make_artifact_agent(
        tmp_path,
        status="DONE",
        raw_xprompt="#git:sase %auto Ask Agent Clan to inspect sase-core",
    )
    Path(agent.artifacts_dir, "01_prompt.md").write_text(
        source + "\n", encoding="utf-8"
    )
    Path(agent.response_path).write_text(
        "Reply repeats Agent Clan and sase-core.\n",
        encoding="utf-8",
    )

    panel.update_display(agent)
    rendered = panel.captured[-1]
    header = _header_text(rendered)
    assert XPROMPT_TOKEN_STYLES["invocation"] in _styles_at(header, "#git")
    assert _has_role_underline(_styles_at(header, "Agent Clan"))
    assert _has_role_underline(_styles_at(header, "sase-core"))

    prompt_body = _prompt_body(rendered)
    assert _has_role_underline(_styles_at(prompt_body, "Agent Clan"))
    inline = _styles_at(prompt_body, "`checks`", offset=1)
    assert not _has_role_underline(inline)

    reply = None
    assert isinstance(rendered, Group)
    for child in rendered.renderables:
        if isinstance(child, Text) and "Reply repeats" in child.plain:
            reply = child
            break
        code = getattr(child, "plain", "")
        if "Reply repeats" in str(code):
            reply = child
            break
    assert reply is not None
    if isinstance(reply, Text):
        assert not any(
            "underline" in str(span.style)
            for span in reply.spans
            if span.style is not None
        )


def test_hint_mode_restores_file_hints_after_semantics(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    panel = FakePromptPanel()
    raw = "#work(@src/raw.py) Ask Agent Clan about sase-core"
    glossary = dynamic_catalog_for_term(tmp_path, "Agent Clan")
    repo = dynamic_catalog_for_identifier(tmp_path, "sase-core")
    install_panel_semantics(panel, glossary=glossary, repo=repo)
    agent = make_artifact_agent(
        tmp_path,
        status="DONE",
        workspace_dir=str(workspace),
        raw_xprompt=raw,
    )
    Path(agent.artifacts_dir, "01_prompt.md").write_text(
        "Ask Agent Clan to inspect sase-core\n",
        encoding="utf-8",
    )

    result = panel.update_display_with_hints(agent)
    rendered = _header_text(panel.captured[-1])
    assert "[1] @src/raw.py" in rendered.plain
    assert result.file_hints[1] == str(workspace / "src/raw.py")
    assert XPROMPT_TOKEN_STYLES["invocation"] in _styles_at(rendered, "#work")
    assert "bold #FFFF00" in _styles_at(rendered, "[1]")
    assert _has_role_underline(_styles_at(rendered, "Agent Clan"))


def test_family_pinned_and_workflow_authored_prompt_paths(
    tmp_path: Path,
) -> None:
    panel = FakePromptPanel()
    source = "Ask Agent Clan to inspect sase-core"
    glossary = dynamic_catalog_for_term(tmp_path, "Agent Clan")
    repo = dynamic_catalog_for_identifier(tmp_path, "sase-core")
    install_panel_semantics(panel, glossary=glossary, repo=repo)

    root, _child = make_family(tmp_path)
    Path(root.artifacts_dir, "raw_xprompt.md").write_text(
        "#git:sase Ask Agent Clan\n",
        encoding="utf-8",
    )
    Path(root.artifacts_dir, "01_prompt.md").write_text(source + "\n", encoding="utf-8")
    panel.update_display(root)
    family_plain = plain_of(panel.captured[-1])
    assert "AGENT XPROMPT" in family_plain
    assert "Agent Clan" in family_plain
    family_header = _header_text(panel.captured[-1])
    assert _has_role_underline(_styles_at(family_header, "Agent Clan"))

    pinned = FakePromptPanel()
    install_panel_semantics(pinned, glossary=glossary, repo=repo)
    agent = make_artifact_agent(tmp_path, status="FAILED")
    Path(agent.artifacts_dir, "01_prompt.md").write_text(
        source + "\n", encoding="utf-8"
    )

    agent.attempt_history = [
        AttemptRecord(
            attempt_number=1,
            status="failed",
            start_epoch=1.0,
            end_epoch=2.0,
            model=None,
            used_fallback=False,
            error_snippet="err",
            error_full="",
            live_reply_path="/nonexistent.md",
            timestamps_path="/nonexistent.jsonl",
        )
    ]
    pinned.attempt_pinned_number = 1
    pinned._render_attempt_pinned(agent, 1)
    pinned_plain = plain_of(pinned.captured[-1])
    assert "AGENT PROMPT" in pinned_plain
    assert "Agent Clan" in pinned_plain

    snapshot = WorkflowDetailSnapshot(
        artifacts_path=None,
        workflow_state=None,
        inputs=None,
        meta_raw=None,
        meta_fields=[],
        steps=[],
        error=None,
        traceback=None,
        prompt_content=source,
        embedded_markers={},
        embedded_meta={},
    )
    workflow = make_agent()
    renderable = build_workflow_detail_renderable(
        workflow,
        snapshot,
        render_prompt=lambda content: panel._render_agent_prompt(workflow, content),
    )
    workflow_plain = plain_of(renderable)
    assert "AGENT PROMPT" in workflow_plain
    assert "Agent Clan" in workflow_plain


def test_cache_reuses_unchanged_text_and_misses_after_catalog_or_theme(
    tmp_path: Path,
) -> None:
    panel = FakePromptPanel()
    source = "Ask Agent Clan to inspect sase-core"
    glossary = dynamic_catalog_for_term(tmp_path, "Agent Clan")
    repo = dynamic_catalog_for_identifier(tmp_path, "sase-core")
    install_panel_semantics(panel, glossary=glossary, repo=repo)
    agent = make_artifact_agent(
        tmp_path,
        status="DONE",
        raw_xprompt="#git:sase Ask Agent Clan to inspect sase-core",
    )
    Path(agent.artifacts_dir, "01_prompt.md").write_text(
        source + "\n", encoding="utf-8"
    )

    first = panel._render_xprompt(
        agent,
        agent.get_raw_xprompt_content() or "",
        "#git:sase Ask Agent Clan to inspect sase-core",
    )
    second = panel._render_xprompt(
        agent,
        agent.get_raw_xprompt_content() or "",
        "#git:sase Ask Agent Clan to inspect sase-core",
    )
    assert first is second

    panel.app.current_theme = SimpleNamespace(
        primary="#00FF00",
        accent="#0000FF",
        foreground="#000000",
        background="#FFFFFF",
    )
    third = panel._render_xprompt(
        agent,
        agent.get_raw_xprompt_content() or "",
        "#git:sase Ask Agent Clan to inspect sase-core",
    )
    assert third is not first
