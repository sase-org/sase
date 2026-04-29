"""Tests for command palette applicability predicates (Phase 1).

Each test constructs a focused :class:`CommandContext` and asserts a
single representative command is correctly visible / hidden. Coverage
mirrors the acceptance list in ``plans/202604/tui_command_palette.md``:

- CL: no CL selected, submitted/reverted CL, CL without ``cl`` number.
- Agents: group banner focus, done/failed/running/waiting-input agent.
- Axe: parent row vs. background command row, done bgcmd row with
  re-run available.
"""

from __future__ import annotations

from typing import Any

from sase.ace.changespec import ChangeSpec, CommitEntry
from sase.ace.tui.commands import (
    CommandContext,
    CommandSpec,
    build_command_catalog,
    is_command_available,
)
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.bgcmd_list import (
    AxeParentItem,
    BgCmdItem,
    LumberjackItem,
)


def _catalog_by_id() -> dict[str, CommandSpec]:
    return {c.id: c for c in build_command_catalog(load_keymap_registry({}))}


def _make_changespec(
    *,
    cl: str | None = "12345",
    status: str = "Ready",
    commits: list[CommitEntry] | None = None,
    **kwargs: Any,
) -> ChangeSpec:
    return ChangeSpec(
        name=kwargs.get("name", "test_cl"),
        description="test",
        parent=None,
        cl=cl,
        status=status,
        test_targets=None,
        kickstart=None,
        bug=kwargs.get("bug"),
        commits=commits,
        hooks=None,
        comments=None,
        mentors=None,
        file_path="/tmp/test.gp",
        line_number=1,
    )


def _make_agent(*, status: str = "RUNNING", **kwargs: Any) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=kwargs.get("cl_name", "my_feature"),
        project_file="/tmp/test.gp",
        status=status,
        start_time=None,
        workspace_num=kwargs.get("workspace_num"),
        response_path=kwargs.get("response_path"),
        attempt_history=kwargs.get("attempt_history", []),
        pid=kwargs.get("pid"),
    )


# ---------------------------------------------------------------------------
# Tab-scope filtering
# ---------------------------------------------------------------------------


def test_command_hidden_when_tab_not_in_spec_tabs() -> None:
    """A CL-only command must be hidden on the agents tab."""
    catalog = _catalog_by_id()
    show_diff = catalog["app.show_diff"]
    ctx = CommandContext(tab="agents")
    assert not is_command_available(show_diff, ctx)


# ---------------------------------------------------------------------------
# CLs tab
# ---------------------------------------------------------------------------


def test_show_diff_hidden_when_no_cl_selected() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.show_diff"]
    ctx = CommandContext(tab="changespecs", changespec=None)
    assert not is_command_available(spec, ctx)


def test_show_diff_hidden_when_cl_has_no_cl_number() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.show_diff"]
    cs = _make_changespec(cl=None)
    ctx = CommandContext(tab="changespecs", changespec=cs)
    assert not is_command_available(spec, ctx)


def test_show_diff_visible_with_cl_number() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.show_diff"]
    cs = _make_changespec(cl="12345")
    ctx = CommandContext(tab="changespecs", changespec=cs)
    assert is_command_available(spec, ctx)


def test_mail_visible_only_for_ready_status() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.mail"]
    ready = _make_changespec(status="Ready")
    draft = _make_changespec(status="Draft")
    assert is_command_available(
        spec, CommandContext(tab="changespecs", changespec=ready)
    )
    assert not is_command_available(
        spec, CommandContext(tab="changespecs", changespec=draft)
    )


def test_reword_hidden_for_submitted_cl() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.reword"]
    cs = _make_changespec(status="Submitted")
    ctx = CommandContext(tab="changespecs", changespec=cs)
    assert not is_command_available(spec, ctx)


def test_rename_cl_hidden_for_reverted_cl() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.rename_cl"]
    cs = _make_changespec(status="Reverted")
    ctx = CommandContext(tab="changespecs", changespec=cs)
    assert not is_command_available(spec, ctx)


def test_accept_proposal_requires_proposed_entry() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.accept_proposal"]
    plain = CommitEntry(number=1, note="plain")
    proposed = CommitEntry(number=2, note="proposed", proposal_letter="a")
    cs_no = _make_changespec(commits=[plain])
    cs_yes = _make_changespec(commits=[plain, proposed])
    assert not is_command_available(
        spec, CommandContext(tab="changespecs", changespec=cs_no)
    )
    assert is_command_available(
        spec, CommandContext(tab="changespecs", changespec=cs_yes)
    )


def test_clear_marks_only_when_marks_exist() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.clear_marks"]
    cs = _make_changespec()
    assert not is_command_available(
        spec, CommandContext(tab="changespecs", changespec=cs, mark_count=0)
    )
    assert is_command_available(
        spec, CommandContext(tab="changespecs", changespec=cs, mark_count=3)
    )


def test_copy_changespecs_cl_number_requires_cl() -> None:
    catalog = _catalog_by_id()
    spec = catalog["copy.changespecs.cl_number"]
    cs_with_cl = _make_changespec(cl="12345")
    cs_without_cl = _make_changespec(cl=None)
    assert is_command_available(
        spec, CommandContext(tab="changespecs", changespec=cs_with_cl)
    )
    assert not is_command_available(
        spec, CommandContext(tab="changespecs", changespec=cs_without_cl)
    )


# ---------------------------------------------------------------------------
# Agents tab
# ---------------------------------------------------------------------------


def test_kill_agent_visible_on_group_banner_even_without_agent() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.kill_agent"]
    ctx = CommandContext(tab="agents", agent=None, group_focused=True)
    assert is_command_available(spec, ctx)


def test_kill_agent_hidden_when_no_agent_no_group_no_marks() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.kill_agent"]
    ctx = CommandContext(tab="agents", agent=None)
    assert not is_command_available(spec, ctx)


def test_edit_spec_only_for_done_agent() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.edit_spec"]
    done = _make_agent(status="DONE")
    failed = _make_agent(status="FAILED")
    running = _make_agent(status="RUNNING")
    assert is_command_available(spec, CommandContext(tab="agents", agent=done))
    # FAILED agents don't get edit_chat (per footer logic)
    assert not is_command_available(spec, CommandContext(tab="agents", agent=failed))
    assert not is_command_available(spec, CommandContext(tab="agents", agent=running))


def test_run_workflow_resume_requires_response_path() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.run_workflow"]
    no_path = _make_agent(status="DONE", response_path=None)
    with_path = _make_agent(status="DONE", response_path="/tmp/r.txt")
    assert not is_command_available(spec, CommandContext(tab="agents", agent=no_path))
    assert is_command_available(spec, CommandContext(tab="agents", agent=with_path))


def test_accept_proposal_on_agents_only_for_active_statuses() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.accept_proposal"]
    waiting = _make_agent(status="WAITING INPUT")
    done = _make_agent(status="DONE")
    assert is_command_available(spec, CommandContext(tab="agents", agent=waiting))
    assert not is_command_available(spec, CommandContext(tab="agents", agent=done))


def test_toggle_attempt_view_requires_history_and_no_pin() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.toggle_attempt_view"]
    no_history = _make_agent(attempt_history=[])
    fake_attempt = object()
    with_history = _make_agent(attempt_history=[fake_attempt])  # type: ignore[arg-type]
    assert not is_command_available(
        spec, CommandContext(tab="agents", agent=no_history)
    )
    assert is_command_available(
        spec,
        CommandContext(tab="agents", agent=with_history, attempt_pinned=False),
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="agents", agent=with_history, attempt_pinned=True),
    )


def test_jump_to_agent_changespec_requires_resolution() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.jump_to_agent_changespec"]
    agent = _make_agent()
    assert not is_command_available(
        spec,
        CommandContext(tab="agents", agent=agent, can_jump_to_changespec=False),
    )
    assert is_command_available(
        spec,
        CommandContext(tab="agents", agent=agent, can_jump_to_changespec=True),
    )


def test_open_tmux_requires_workspace() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.open_tmux"]
    no_ws = _make_agent(workspace_num=0)
    with_ws = _make_agent(workspace_num=42)
    assert not is_command_available(spec, CommandContext(tab="agents", agent=no_ws))
    assert is_command_available(spec, CommandContext(tab="agents", agent=with_ws))


def test_toggle_axe_on_agents_tab_needs_completed_or_focused_agent() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.toggle_axe"]
    # No completed agents and no focused agent: hidden.
    assert not is_command_available(spec, CommandContext(tab="agents"))
    # Completed agents exist (the "dismiss all" affordance from the footer).
    assert is_command_available(
        spec, CommandContext(tab="agents", completed_agent_count=2)
    )


# ---------------------------------------------------------------------------
# Axe tab
# ---------------------------------------------------------------------------


def test_axe_run_workflow_only_on_done_bgcmd_row() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.run_workflow"]
    parent_ctx = CommandContext(tab="axe", axe_item=AxeParentItem())
    bgcmd_running = CommandContext(
        tab="axe",
        axe_item=BgCmdItem(slot=1),
        selected_axe_slot_done=False,
    )
    bgcmd_done = CommandContext(
        tab="axe",
        axe_item=BgCmdItem(slot=1),
        selected_axe_slot_done=True,
    )
    assert not is_command_available(spec, parent_ctx)
    assert not is_command_available(spec, bgcmd_running)
    assert is_command_available(spec, bgcmd_done)


def test_axe_kill_agent_always_meaningful() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.kill_agent"]
    parent_ctx = CommandContext(tab="axe", axe_item=AxeParentItem())
    bgcmd_ctx = CommandContext(tab="axe", axe_item=BgCmdItem(slot=1))
    lumberjack_ctx = CommandContext(tab="axe", axe_item=LumberjackItem(name="hooks"))
    assert is_command_available(spec, parent_ctx)
    assert is_command_available(spec, bgcmd_ctx)
    assert is_command_available(spec, lumberjack_ctx)


def test_copy_axe_visible_requires_focused_row() -> None:
    catalog = _catalog_by_id()
    spec = catalog["copy.axe.visible"]
    no_item = CommandContext(tab="axe", axe_item=None)
    with_item = CommandContext(tab="axe", axe_item=BgCmdItem(slot=1))
    assert not is_command_available(spec, no_item)
    assert is_command_available(spec, with_item)
