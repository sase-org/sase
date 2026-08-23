"""Family detail-panel section rendering tests."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from rich.console import Group
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_header import (
    AgentHeaderRenderable,
    build_header_text,
)
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    SECTION_MARKER_META_KEY,
)
from tests.ace.tui.widgets._agent_display_family_helpers import make_family
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel, plain_of

_CONVERSATION_SECTION_IDS = (
    "agent-xprompt",
    "agent-prompt",
    "agent-reply",
)


def _render_family(
    tmp_path: Path,
    *,
    level: FoldLevel,
    overrides: dict[str, FoldLevel] | None = None,
) -> object:
    tmp_path.mkdir(parents=True, exist_ok=True)
    root, _child = make_family(tmp_path)
    overrides = overrides or {}
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        lane_fold_level=level,
        lane_section_fold_overrides=overrides,
    )
    panel._update_family_display(
        root,
        header,
        error,
        panel_level=level,
        section_fold_overrides=overrides,
    )
    return panel.captured[-1]


def _conversation_document(renderable: object) -> str:
    plain = plain_of(renderable)
    return plain[plain.index("AGENT XPROMPT") :]


def _section_ids(renderable: object) -> list[str]:
    identities: list[str] = []

    def _visit(candidate: object) -> None:
        if isinstance(candidate, Group):
            for child in candidate.renderables:
                _visit(child)
            return
        if not isinstance(candidate, (Text, AgentHeaderRenderable)):
            return
        for span in candidate.spans:
            meta = getattr(span.style, "meta", None)
            identity = meta.get(SECTION_MARKER_META_KEY) if meta else None
            if isinstance(identity, str) and identity not in identities:
                identities.append(identity)

    _visit(renderable)
    return identities


@pytest.mark.parametrize(
    ("level", "overrides"),
    [
        (FoldLevel.COLLAPSED, {}),
        (FoldLevel.EXPANDED, {}),
        (FoldLevel.FULLY_EXPANDED, {}),
        (FoldLevel.EXHAUSTIVE, {}),
        (
            FoldLevel.EXPANDED,
            {
                "agent-xprompt": FoldLevel.COLLAPSED,
                "agent-prompt": FoldLevel.EXPANDED,
                "agent-reply": FoldLevel.FULLY_EXPANDED,
            },
        ),
    ],
)
def test_family_conversation_sections_are_always_full(
    tmp_path: Path,
    level: FoldLevel,
    overrides: dict[str, FoldLevel],
) -> None:
    renderable = _render_family(
        tmp_path,
        level=level,
        overrides=overrides,
    )
    plain = plain_of(renderable)

    assert "AGENT XPROMPT\n" in plain
    assert "AGENT PROMPT\n" in plain
    assert "AGENT REPLY · 2\n" in plain
    assert "plan xprompt line 15" in plain
    assert "plan prompt line 15" in plain
    assert "plan reply line 1" in plain
    assert "code reply line 1" in plain
    assert "more lines" not in plain
    assert "earlier lines" not in plain
    assert not any(
        f"{glyph} {heading}" in plain
        for glyph in ("▸", "▾", "▼", "◆")
        for heading in ("AGENT XPROMPT", "AGENT PROMPT", "AGENT REPLY")
    )
    assert [
        identity
        for identity in _section_ids(renderable)
        if identity in _CONVERSATION_SECTION_IDS
    ] == list(_CONVERSATION_SECTION_IDS)


def test_family_conversation_document_is_identical_across_fold_state(
    tmp_path: Path,
) -> None:
    root = tmp_path / "cases"
    documents = [
        _conversation_document(
            _render_family(
                root / str(index),
                level=level,
                overrides=overrides,
            )
        )
        for index, (level, overrides) in enumerate(
            (
                (FoldLevel.COLLAPSED, {}),
                (FoldLevel.EXPANDED, {}),
                (FoldLevel.FULLY_EXPANDED, {}),
                (
                    FoldLevel.EXPANDED,
                    {
                        "agent-xprompt": FoldLevel.FULLY_EXPANDED,
                        "agent-prompt": FoldLevel.COLLAPSED,
                        "agent-reply": FoldLevel.EXPANDED,
                    },
                ),
            )
        )
    ]

    assert documents == [documents[0]] * len(documents)


def test_family_omits_empty_xprompt_and_prompt_sections(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    artifacts_dir = Path(root.artifacts_dir or "")
    (artifacts_dir / "raw_xprompt.md").unlink()
    (artifacts_dir / "01_prompt.md").unlink()
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
    )

    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.COLLAPSED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "AGENT XPROMPT" not in plain
    assert "No xprompt file found." not in plain
    assert "AGENT PROMPT" not in plain
    assert "No prompt file found." not in plain
    assert "AGENT REPLY · 2\n" in plain
    assert "▾ AGENT REPLY" not in plain


@pytest.mark.parametrize("level", [FoldLevel.EXPANDED, FoldLevel.FULLY_EXPANDED])
def test_family_keeps_pending_reply_state(
    tmp_path: Path,
    level: FoldLevel,
) -> None:
    root, child = make_family(tmp_path)
    Path(root.response_path or "").unlink()
    Path(child.response_path or "").unlink()
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        lane_fold_level=level,
    )

    panel._update_family_display(
        root,
        header,
        error,
        panel_level=level,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "AGENT REPLY · 2\n" in plain
    assert plain.count("No response content yet.") == 2


def test_root_monitor_phase_follows_planner_step_divider(tmp_path: Path) -> None:
    root, child = make_family(tmp_path)
    planner = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file=root.project_file,
        status="DONE",
        start_time=root.start_time,
        stop_time=root.stop_time,
        raw_suffix=root.raw_suffix,
        artifacts_dir=root.artifacts_dir,
        response_path=root.response_path,
        parent_workflow="ace-run",
        step_type="agent",
        step_index=0,
        parent_step_index=None,
        agent_name="alpha--plan",
        agent_family=root.agent_family,
        agent_family_role="plan",
        role_suffix="--plan",
        model=root.model,
    )
    started = root.start_time
    assert started is not None
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="family-monitor",
        project_file=root.project_file,
        status="MONITORED",
        status_bucket="Done",
        start_time=started + timedelta(minutes=1),
        stop_time=started + timedelta(minutes=2),
        raw_suffix="20260718120100",
        parent_timestamp=root.raw_suffix,
        agent_name="alpha--mon",
        agent_family=root.agent_family,
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id="m-root",
        monitor_state="completed",
        monitor_command="just check-full",
    )
    root.runtime_children = [planner]
    root.followup_agents = [child, monitor]
    child.family_container = root
    monitor.family_container = root

    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.EXPANDED,
    )
    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.EXPANDED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "AGENT REPLY · 3\n" in plain
    assert plain.index("AGENT (plan)") < plain.index("⚙ MONITOR")
