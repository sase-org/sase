"""Detachable identity headers in prompt-panel documents."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.text import Text

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.util.lazy_syntax import CachedRenderable
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_display_attempts import (
    AgentAttemptDisplayMixin,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_header_renderable import (
    AgentHeaderRenderable,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    DetailHeaderSummary,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe import (
    build_tribe_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._identity_header import (
    IdentityHeader,
    find_identity_header,
    identity_kind_for_agent,
    strip_leading_document_chrome,
)
from sase.ace.tui.widgets.prompt_panel._workflow_render import (
    build_workflow_detail_renderable,
)
from sase.ace.tui.widgets.prompt_panel._workflow_types import WorkflowDetailSnapshot
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent
from tests.ace.tui.widgets._agent_display_family_helpers import make_family
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_tribe_helpers import make_tribe_snapshot
from tests.ace.tui.widgets._prompt_panel_section_navigation_helpers import (
    _MetadataNavigationApp,
)


def _render_lines(renderable: object, *, width: int) -> list[str]:
    output = StringIO()
    Console(file=output, width=width, color_system=None).print(renderable, end="")
    return output.getvalue().splitlines()


def _detached(agent: Agent, **kwargs: Any) -> IdentityHeader:
    document, _ = build_header_text(agent, detach_identity=True, **kwargs)
    assert isinstance(document, AgentHeaderRenderable)
    identity = find_identity_header(document)
    assert identity is not None
    return identity


def test_identity_kinds_cover_every_node_kind(tmp_path: Path) -> None:
    root, child = make_family(tmp_path)
    cases = [
        (make_agent(agent_name="solo"), "AGENT SHELL", "#FFD700"),
        (root, "FAMILY", "#00AFFF"),
        (child, "AGENT SHELL", "#FFD700"),
        (
            make_agent(agent_name="proc", agent_type=AgentType.PROC_SHELL),
            "PROC SHELL",
            "#5FD7FF",
        ),
        (
            make_agent(
                agent_name="alpha--gate",
                agent_family_role="gate",
                role_suffix="--gate",
                gate_id="g123abc456def",
            ),
            "GATE",
            "#0BCDEC",
        ),
        (
            make_agent(
                agent_name="alpha--mon",
                agent_family_role="monitor",
                role_suffix="--mon",
            ),
            "MONITOR",
            "#FFAF5F",
        ),
        (
            make_agent(
                agent_type=AgentType.WORKFLOW,
                workflow="demo",
                parent_workflow="demo",
                step_name="setup",
                step_type="bash",
            ),
            "STEP",
            "#FFAF5F",
        ),
        (
            make_agent(agent_type=AgentType.WORKFLOW, workflow="demo"),
            "WORKFLOW",
            "#AF87D7",
        ),
    ]
    for agent, label, accent in cases:
        assert identity_kind_for_agent(agent) == (label, accent)


def test_strip_leading_document_chrome() -> None:
    sample = Text("\n\n" + "─" * 50 + "\n\n\nbody here\n")
    stripped, removed = strip_leading_document_chrome(sample)
    assert stripped.plain == "body here\n"
    assert removed == len("\n\n" + "─" * 50 + "\n\n\n")

    heavy = Text("━" * 50 + "\nbody\n")
    kept, removed_heavy = strip_leading_document_chrome(heavy)
    assert removed_heavy == 0
    assert kept.plain == heavy.plain

    plain = Text("body\n")
    same, removed_plain = strip_leading_document_chrome(plain)
    assert removed_plain == 0
    assert same.plain == "body\n"


def test_strip_preserves_body_styles() -> None:
    sample = Text()
    sample.append("\n")
    sample.append("─" * 50 + "\n", style="dim")
    sample.append("\n")
    sample.append("Name: ", style="bold #87D7FF")
    sample.append("solo\n", style="#FFD700")
    stripped, _ = strip_leading_document_chrome(sample)
    assert stripped.plain == "Name: solo\n"
    assert stripped.spans[0].style == "bold #87D7FF"


def test_find_identity_header_searches_groups_and_wrappers() -> None:
    agent = make_agent(agent_name="solo")
    document, _ = build_header_text(agent, cheap=True, detach_identity=True)
    assert isinstance(document, AgentHeaderRenderable)
    identity = find_identity_header(document)
    assert identity is not None
    assert find_identity_header(Group(document, Text("tail\n"))) is identity
    assert find_identity_header(Group(Text("head\n"), document)) is identity
    assert find_identity_header(CachedRenderable(document, "doc")) is identity
    assert find_identity_header(Text("plain\n")) is None
    assert find_identity_header(Group(Text("a\n"), Text("b\n"))) is None


def test_detached_body_excludes_identity_lines() -> None:
    agent = make_agent(agent_name="solo")
    plain, _ = build_header_text(agent, cheap=True)
    document, _ = build_header_text(agent, cheap=True, detach_identity=True)
    assert isinstance(document, AgentHeaderRenderable)
    assert "AGENT SHELL" not in document.plain
    assert "Name:" not in document.plain
    assert "Timestamps:" not in document.plain
    assert not document.plain.startswith("\n")
    assert not document.plain.startswith("─" * 50)


def test_detached_expanded_matches_inline_region() -> None:
    agent = make_agent(agent_name="solo")
    plain, _ = build_header_text(agent, cheap=False)
    identity = _detached(agent, cheap=False)
    for line in identity.expanded.plain.splitlines():
        assert line in plain.plain
    plain_spans = {span.style for span in plain.spans}
    for span in identity.expanded.spans:
        assert span.style in plain_spans


def test_compact_form_is_two_truncating_lines() -> None:
    identity = _detached(make_agent(agent_name="solo"), cheap=True)
    assert len(identity.compact.plain.splitlines()) == 2
    assert identity.compact.no_wrap is True
    assert identity.compact.overflow == "ellipsis"
    first, second = identity.compact.plain.splitlines()
    assert first.startswith("solo")
    assert " · " in second or second.strip()


def test_xprompts_render_on_cheap_detached_path() -> None:
    summary = DetailHeaderSummary(xprompts_used=[{"kind": "part", "name": "review"}])
    agent = make_agent(agent_name="solo")
    cheap_plain, _ = build_header_text(agent, cheap=True, summary=summary)
    assert "Xprompts:" not in cheap_plain.plain
    identity = _detached(agent, cheap=True, summary=summary)
    assert "Xprompts:" in identity.expanded.plain
    assert "#review" in identity.compact.plain


def test_responsive_lanes_render_at_widths_in_identity_and_body() -> None:
    summary = DetailHeaderSummary(agent_page_url="https://example.com/agent")
    agent = make_agent(agent_name="solo")
    identity = _detached(agent, cheap=True, summary=summary)
    assert "example.com" in identity.expanded.plain
    for width in (40, 80, 120):
        identity_lines = _render_lines(identity.expanded, width=width)
        assert any("example.com" in line for line in identity_lines)
        body_lines = _render_lines(
            build_header_text(agent, cheap=True, summary=summary, detach_identity=True)[
                0
            ],
            width=width,
        )
        assert body_lines == [] or all(len(line) <= width + 1 for line in body_lines)


def test_family_fold_line_moves_into_identity(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    plain, _ = build_header_text(root, cheap=True, lane_fold_level=FoldLevel.COLLAPSED)
    assert "Fold:" in plain.plain
    document, _ = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
        detach_identity=True,
    )
    assert isinstance(document, AgentHeaderRenderable)
    assert "Fold:" not in document.plain
    identity = find_identity_header(document)
    assert identity is not None
    assert "Fold:" in identity.expanded.plain
    assert "1/2" in identity.compact.plain


def test_proc_shell_compact_rows(tmp_path: Path) -> None:
    del tmp_path
    agent = make_agent(
        agent_type=AgentType.PROC_SHELL,
        agent_name="shell-1",
        cl_name="demo",
        monitor_cwd="/tmp/work/checkout",
        activity="idling",
    )
    identity = _detached(agent, cheap=True)
    assert (identity.kind_label, identity.accent) == ("PROC SHELL", "#5FD7FF")
    first, second = identity.compact.plain.splitlines()
    assert "shell-1" in first
    assert "checkout" in second
    assert "idling" in second


def test_workflow_document_detaches_identity() -> None:
    agent = make_agent(
        agent_type=AgentType.WORKFLOW,
        workflow="demo",
        status="RUNNING",
        start_time=datetime(2024, 1, 1, 14, 23, 45),
    )
    snapshot = WorkflowDetailSnapshot(
        artifacts_path=None,
        workflow_state=None,
        steps=[],
        embedded_markers={},
        embedded_meta={},
        meta_raw=None,
        meta_fields=[],
        inputs=None,
        prompt_content=None,
        error=None,
        traceback=None,
    )
    plain = build_workflow_detail_renderable(agent, snapshot)
    detached = build_workflow_detail_renderable(agent, snapshot, detach_identity=True)
    identity = find_identity_header(detached)
    assert identity is not None
    assert (identity.kind_label, identity.accent) == ("WORKFLOW", "#AF87D7")
    detached_lines = _render_lines(detached, width=200)
    rendered = "\n".join(detached_lines)
    assert "WORKFLOW DETAILS" not in rendered
    assert "WORKFLOW STEPS" in rendered
    plain_rendered = "\n".join(_render_lines(plain, width=200))
    for line in identity.expanded.plain.splitlines():
        assert line in plain_rendered
    first, second = identity.compact.plain.splitlines()
    assert "demo" in first
    assert "RUNNING" in second


def test_tribe_documents_detach_cheap_and_full() -> None:
    snapshot = make_tribe_snapshot()
    cheap = build_tribe_detail_text(snapshot, cheap=True)
    detached_cheap = build_tribe_detail_text(snapshot, cheap=True, detach_identity=True)
    identity = find_identity_header(detached_cheap)
    assert identity is not None
    assert identity.kind_label == "TRIBE"
    assert identity.accent
    assert "TRIBE" not in detached_cheap.plain
    assert "Name:" not in detached_cheap.plain
    assert len(identity.compact.plain.splitlines()) == 2

    full = build_tribe_detail_text(snapshot, cheap=False)
    detached_full = build_tribe_detail_text(snapshot, cheap=False, detach_identity=True)
    full_identity = find_identity_header(detached_full)
    assert full_identity is not None
    for line in full_identity.expanded.plain.splitlines():
        assert line in full.plain
    assert "Name:" not in detached_full.plain
    assert cheap.plain  # cheap non-detached still renders the header inline


def test_tribe_cheap_empty_body_renders_loading_line() -> None:
    snapshot = dataclasses.replace(make_tribe_snapshot(), description="")
    detached = build_tribe_detail_text(snapshot, cheap=True, detach_identity=True)
    assert "⋯ loading…" in detached.plain


def test_attempt_pinned_document_carries_identity() -> None:
    from sase.ace.tui.models.agent import AttemptRecord

    agent = make_agent(agent_name="solo")
    agent.attempt_history = (
        AttemptRecord(
            attempt_number=1,
            status="failed",
            start_epoch=1745337600.0,
            end_epoch=1745337660.0,
            model=None,
            used_fallback=False,
            error_snippet="err-1",
            error_full="Traceback: boom",
            live_reply_path="/nonexistent/reply.md",
            timestamps_path="/nonexistent/stamps.jsonl",
        ),
    )

    class _PinnedPanel(AgentAttemptDisplayMixin):
        def __init__(self) -> None:
            self.captured: list[object] = []

        def update(self, renderable: object) -> None:
            self.captured.append(renderable)

    panel = _PinnedPanel()
    panel._render_attempt_pinned(agent, 1, True)
    assert panel.captured
    assert find_identity_header(panel.captured[0]) is not None


def test_clan_documents_carry_no_identity() -> None:
    member = make_clan_agent(
        "clan-test",
        status="RUNNING",
        start=datetime(2024, 1, 1, 14, 0, 0),
    )
    container = project_clan_tree([member])[0]
    assert container.is_clan_container
    document, _ = build_header_text(container, detach_identity=True)
    assert find_identity_header(document) is None


def test_non_detached_builders_publish_no_identity() -> None:
    agent = make_agent(agent_name="solo")
    plain, _ = build_header_text(agent, cheap=True)
    assert find_identity_header(plain) is None
    snapshot = make_tribe_snapshot()
    assert find_identity_header(build_tribe_detail_text(snapshot)) is None


async def test_panel_sink_receives_identity_before_digest_return() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(60, 20)):
        panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
        received: list[IdentityHeader | None] = []
        assert panel.detaches_identity_header is False
        panel.attach_identity_header_sink(received.append)
        assert panel.detaches_identity_header is True

        agent = make_agent(agent_name="solo")
        document, _ = build_header_text(agent, cheap=True, detach_identity=True)
        panel.update(document)
        assert len(received) == 1
        identity = received[0]
        assert identity is not None
        assert identity.kind_label == "AGENT SHELL"

        panel.update(document)
        assert len(received) == 2
        assert received[1] is identity

        inline = panel.inline_document_renderable()
        assert isinstance(inline, Group)
        inline_lines = _render_lines(inline, width=60)
        assert inline_lines[0] == "AGENT SHELL"

        panel.update(Text("No agent selected", style="dim italic"))
        assert received[-1] is None

        panel.attach_identity_header_sink(None)
        assert panel.detaches_identity_header is False
