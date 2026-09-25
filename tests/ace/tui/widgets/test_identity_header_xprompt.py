"""XPROMPT attachment to detached prompt-panel identities."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console
from rich.text import Text

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_xprompt import (
    _agent_may_show_xprompt,
)
from sase.ace.tui.widgets.prompt_panel._identity_header import find_identity_header

from tests.ace.tui.widgets._agent_display_agent_session_helpers import (
    make_agent_session,
)
from tests.ace.tui.widgets._agent_display_helpers import (
    FakePromptPanel,
    make_agent,
    make_artifact_agent,
    plain_of,
)


class _DetachedPanel(FakePromptPanel):
    @property
    def detaches_identity_header(self) -> bool:
        return True

    @property
    def detaches_xprompt(self) -> bool:
        return True


def test_identity_xprompt_is_inline_after_expanded_fields() -> None:
    agent = make_agent(agent_name="solo")
    document, _ = build_header_text(agent, detach_identity=True)
    identity = find_identity_header(document)
    assert identity is not None

    source = Text("Review #plan  \n\n", style="#AF87FF")
    attached = identity.with_xprompt(source)
    source.append(" changed")

    assert identity.xprompt is None
    assert attached.xprompt is not None
    assert attached.xprompt.plain == "Review #plan  "
    assert attached.xprompt.style == "#AF87FF"

    output = StringIO()
    Console(file=output, width=80, color_system=None).print(
        attached.inline_renderable(), end=""
    )
    plain = output.getvalue()
    assert plain.index("AGENT SHELL") < plain.index("Name:")
    assert plain.index("Name:") < plain.index("AGENT XPROMPT")
    assert plain.index("AGENT XPROMPT") < plain.index("Review #plan")
    assert plain.index("Review #plan") < plain.index("─" * 50)


def test_expanded_renderable_separates_fields_and_xprompt_by_one_blank_row() -> None:
    agent = make_agent(agent_name="solo")
    document, _ = build_header_text(agent, detach_identity=True)
    identity = find_identity_header(document)
    assert identity is not None
    attached = identity.with_xprompt(Text("Review #plan"))

    output = StringIO()
    Console(file=output, width=80, color_system=None).print(
        attached.expanded_renderable(), end=""
    )
    lines = output.getvalue().splitlines()
    heading = lines.index("AGENT XPROMPT")
    assert lines[heading - 1] == ""
    assert lines[heading - 2].strip() != ""
    assert lines[heading + 1] == "Review #plan"


def test_standard_xprompt_moves_to_identity_when_detached(tmp_path: Path) -> None:
    panel = _DetachedPanel()
    agent = make_artifact_agent(
        tmp_path,
        status="DONE",
        raw_xprompt="#review @src/example.py\n",
    )

    panel.update_display(agent)

    document = panel.captured[-1]
    identity = find_identity_header(document)
    assert identity is not None
    assert identity.xprompt is not None
    assert identity.xprompt.plain == "#review @src/example.py"
    assert "AGENT XPROMPT" not in plain_of(document)
    assert "AGENT PROMPT" in plain_of(document)


def test_hinted_xprompt_moves_to_identity_and_keeps_its_markers(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    panel = _DetachedPanel()
    agent = make_artifact_agent(
        tmp_path,
        status="DONE",
        workspace_dir=str(workspace),
        raw_xprompt="Read @src/example.py",
    )

    result = panel.update_display_with_hints(agent)

    identity = find_identity_header(panel.captured[-1])
    assert identity is not None
    assert identity.xprompt is not None
    assert identity.xprompt.plain == "Read [1] @src/example.py"
    assert identity.has_hints is True
    assert result.file_hints == {1: str(workspace / "src/example.py")}
    assert "AGENT XPROMPT" not in plain_of(panel.captured[-1])


def test_family_xprompt_moves_to_identity_when_detached(tmp_path: Path) -> None:
    root, _child = make_agent_session(tmp_path)
    panel = _DetachedPanel()
    header, error = build_header_text(root, detach_identity=True)

    panel._update_family_display(
        root,
        header,
        error,
        panel_level=object(),
        section_fold_overrides={},
    )

    identity = find_identity_header(panel.captured[-1])
    assert identity is not None
    assert identity.xprompt is not None
    assert "plan xprompt line 1" in identity.xprompt.plain
    assert "AGENT XPROMPT" not in plain_of(panel.captured[-1])


def test_header_only_uses_xprompt_memo_or_pending_state(tmp_path: Path) -> None:
    panel = _DetachedPanel()
    visited = make_artifact_agent(tmp_path, status="DONE", raw_xprompt="Remember me")
    panel.update_display(visited)
    panel.update_header_only(visited)

    identity = find_identity_header(panel.captured[-1])
    assert identity is not None
    assert identity.xprompt is not None
    assert identity.xprompt.plain == "Remember me"
    assert identity.xprompt_pending is False

    unvisited = make_agent(agent_name="unvisited", cl_name="other-cl")
    panel.update_header_only(unvisited)
    pending = find_identity_header(panel.captured[-1])
    assert pending is not None
    assert pending.xprompt is None
    assert pending.xprompt_pending is True


def test_agent_may_show_xprompt_excludes_non_prompt_kinds() -> None:
    assert _agent_may_show_xprompt(make_agent()) is True
    assert _agent_may_show_xprompt(make_agent(agent_type=AgentType.PROC_SHELL)) is False
    assert (
        _agent_may_show_xprompt(
            make_agent(
                agent_type=AgentType.WORKFLOW,
                parent_workflow="workflow",
                step_type="bash",
            )
        )
        is False
    )
    assert _agent_may_show_xprompt(make_agent(agent_type=AgentType.WORKFLOW)) is False
