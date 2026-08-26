"""Rendered marker contracts for prompt panel section navigation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import cast
from unittest.mock import patch

from rich.console import Group, RenderableType
from rich.style import Style as RichStyle
from rich.text import Text

from sase.ace.tui.models._agent_clan_sections import (
    ClanSectionSnapshot,
    aggregate_clan_in_memory,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe import (
    build_tribe_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    SECTION_FOLD_ONLY_META_KEY,
    SECTION_MARKER_META_KEY,
)
from sase.ace.tui.widgets.prompt_panel._workflow_render import (
    build_workflow_detail_renderable,
)
from sase.ace.tui.widgets.prompt_panel._workflow_types import WorkflowDetailSnapshot
from tests.ace.tui.widgets._agent_display_family_helpers import make_family
from tests.ace.tui.widgets._agent_display_helpers import (
    FakePromptPanel,
    make_artifact_agent,
)
from tests.ace.tui.widgets._agent_display_tribe_helpers import make_tribe_snapshot
from tests.ace.tui.widgets._prompt_panel_section_navigation_helpers import (
    rendered_section_ids,
    section,
)


def test_section_marker_preserves_text_and_ignores_user_matching_content() -> None:
    text = section("AGENT PROMPT", "AGENT REPLY\n", section_id="agent-prompt")

    assert text.plain == "AGENT PROMPT\nAGENT REPLY\n"
    marked_ranges: list[tuple[int, int, object]] = []
    for span in text.spans:
        style = span.style
        if isinstance(style, RichStyle) and SECTION_MARKER_META_KEY in style.meta:
            marked_ranges.append(
                (span.start, span.end, style.meta[SECTION_MARKER_META_KEY])
            )
    assert marked_ranges == [(0, len("AGENT PROMPT"), "agent-prompt")]


def test_regular_agent_and_workflow_render_paths_mark_real_sections(
    tmp_path: Path,
) -> None:
    regular = make_artifact_agent(tmp_path, status="DONE")
    panel = AgentPromptPanel.__new__(AgentPromptPanel)
    with patch.object(panel, "update") as update:
        panel._update_display_impl(regular)  # noqa: SLF001
    assert rendered_section_ids(update.call_args.args[0]) == [
        "agent-xprompt",
        "agent-prompt",
        "agent-chat",
    ]

    workflow = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="demo",
        project_file="/tmp/demo.sase",
        status="FAILED",
        start_time=datetime(2026, 7, 16, 12, 0, 0),
        workflow="demo_workflow",
        error_message="boom",
    )
    snapshot = WorkflowDetailSnapshot(
        artifacts_path=None,
        workflow_state=None,
        inputs={"target": "tests"},
        meta_raw=None,
        meta_fields=[("Result", "failed")],
        steps=[],
        error=None,
        traceback=None,
        prompt_content="Run the workflow",
        embedded_markers={},
        embedded_meta={},
    )
    workflow_renderable = build_workflow_detail_renderable(workflow, snapshot)
    assert rendered_section_ids(workflow_renderable) == [
        "workflow-details",
        "error",
        "workflow-variables",
        "inputs",
        "workflow-steps",
        "agent-prompt",
    ]


def _resolve_span_style(style: object) -> RichStyle | None:
    if isinstance(style, str):
        return RichStyle.parse(style)
    return style if isinstance(style, RichStyle) else None


def _marked_spans(renderable: object) -> list[tuple[str, bool, str]]:
    """Return ``(identity, fold_only, underlined_text)`` for every marked span.

    Walks ``Text.spans`` directly rather than through Console rendering, so a
    title's underlined text is never fragmented by line wrapping at some
    particular render width. The marked span for a heading built from several
    ``Text.append`` calls (a fold glyph, the label, a dim dot-count suffix) may
    legitimately include non-underlined text on either side of the
    underlined label, so this scopes the extracted text to the underlined
    sub-spans only.
    """
    results: list[tuple[str, bool, str]] = []

    def visit(node: object) -> None:
        if isinstance(node, Text):
            marker_spans: list[tuple[int, int, str, bool]] = []
            for span in node.spans:
                style = _resolve_span_style(span.style)
                if style is None or not style.meta:
                    continue
                identity = style.meta.get(SECTION_MARKER_META_KEY)
                if isinstance(identity, str) and identity:
                    fold_only = bool(style.meta.get(SECTION_FOLD_ONLY_META_KEY))
                    marker_spans.append((span.start, span.end, identity, fold_only))
            for start, end, identity, fold_only in marker_spans:
                underlined = ""
                for span in node.spans:
                    style = _resolve_span_style(span.style)
                    if style is None or not style.underline:
                        continue
                    ustart, uend = max(span.start, start), min(span.end, end)
                    if ustart < uend:
                        underlined += node.plain[ustart:uend]
                results.append((identity, fold_only, underlined))
        elif isinstance(node, Group):
            for child in node.renderables:
                visit(child)

    visit(renderable)
    return results


def test_only_title_anchors_carry_nonempty_all_caps_underlined_text(
    tmp_path: Path,
) -> None:
    family, _child = make_family(tmp_path)
    family_header, _ = build_header_text(
        family, cheap=True, lane_fold_level=FoldLevel.EXPANDED
    )

    clan_container = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="research",
        project_file="/tmp/demo.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 16, 12, 0, 0),
        agent_clan="research",
        agent_clan_generation="20260716120000",
        is_clan_container=True,
    )
    clan_container.runtime_children = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="research.member",
            project_file="/tmp/demo.sase",
            status="WAITING",
            start_time=datetime(2026, 7, 16, 12, 1, 0),
            raw_suffix="20260716120100",
            agent_name="research.member",
            agent_clan="research",
            agent_clan_generation="20260716120000",
        )
    ]
    clan_snapshot = ClanSectionSnapshot(
        in_memory=aggregate_clan_in_memory(clan_container)
    )
    clan_header, _ = build_header_text(
        clan_container,
        cheap=True,
        clan_snapshot=clan_snapshot,
        clan_fold_level=FoldLevel.EXPANDED,
    )

    tribe_detail = build_tribe_detail_text(
        make_tribe_snapshot(),
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    regular = make_artifact_agent(tmp_path, status="DONE")
    panel = AgentPromptPanel.__new__(AgentPromptPanel)
    with patch.object(panel, "update") as update:
        panel._update_display_impl(regular)  # noqa: SLF001
    regular_renderable = update.call_args.args[0]

    workflow = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="demo",
        project_file="/tmp/demo.sase",
        status="FAILED",
        start_time=datetime(2026, 7, 16, 12, 0, 0),
        workflow="demo_workflow",
        error_message="boom",
    )
    workflow_snapshot = WorkflowDetailSnapshot(
        artifacts_path=None,
        workflow_state=None,
        inputs={"target": "tests"},
        meta_raw=None,
        meta_fields=[("Result", "failed")],
        steps=[],
        error=None,
        traceback=None,
        prompt_content="Run the workflow",
        embedded_markers={},
        embedded_meta={},
    )
    workflow_renderable = build_workflow_detail_renderable(workflow, workflow_snapshot)

    documents = [
        family_header,
        clan_header,
        tribe_detail,
        regular_renderable,
        workflow_renderable,
    ]

    saw_fold_only = False
    for document in documents:
        for identity, fold_only, underlined in _marked_spans(document):
            if fold_only:
                saw_fold_only = True
                continue
            stripped = underlined.strip()
            assert stripped, f"title {identity!r} has no underlined text"
            assert stripped == stripped.upper(), (
                f"title {identity!r} underlined text is not upper: {stripped!r}"
            )
    assert saw_fold_only, "expected at least one fold-only anchor (a roster row)"


def test_family_conversation_headings_remain_navigation_targets(
    tmp_path: Path,
) -> None:
    family, _child = make_family(tmp_path)
    header, error = build_header_text(
        family,
        cheap=True,
        lane_fold_level=FoldLevel.EXPANDED,
    )
    prompt_panel = FakePromptPanel()
    prompt_panel._update_family_display(
        family,
        header,
        error,
        panel_level=FoldLevel.EXPANDED,
        section_fold_overrides={},
    )

    identities = rendered_section_ids(cast(RenderableType, prompt_panel.captured[-1]))
    conversation_ids = [
        identity
        for identity in identities
        if identity in {"agent-xprompt", "agent-prompt", "agent-reply"}
    ]
    assert conversation_ids == ["agent-xprompt", "agent-prompt", "agent-reply"]
    assert "family" not in identities
    assert "agent-shell" not in identities
    assert identities[0] == "members"


def test_family_kind_header_is_not_a_section_title(tmp_path: Path) -> None:
    family, _child = make_family(tmp_path)
    header, _ = build_header_text(
        family,
        cheap=True,
        lane_fold_level=FoldLevel.EXPANDED,
    )

    identities = rendered_section_ids(header, width=80)

    assert family.is_family_container_row is True
    assert header.plain.startswith("FAMILY\n")
    assert "family" not in identities
    assert identities[0] == "members"


def test_agent_shell_kind_header_is_not_a_section_title(tmp_path: Path) -> None:
    _root, child = make_family(tmp_path)
    header, _ = build_header_text(child, cheap=True, lane_fold_level=FoldLevel.EXPANDED)

    identities = rendered_section_ids(header, width=80)

    assert header.plain.startswith("AGENT SHELL\n")
    assert "agent-shell" not in identities
    assert "family" not in identities
    assert identities[0] == "members"
