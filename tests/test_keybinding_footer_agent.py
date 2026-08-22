"""Tests for the ace TUI keybinding footer agent bindings."""

from sase.ace.tui.models.agent import Agent, AgentType, AttemptRecord
from sase.ace.tui.widgets import KeybindingFooter


def _edit_hooks_key(footer: KeybindingFooter) -> str:
    return footer._kd("edit_hooks")


def _make_agent(
    status: str = "RUNNING",
    response_path: str | None = None,
) -> Agent:
    """Create a test Agent for binding tests."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test_feature",
        project_file="/tmp/test.sase",
        status=status,
        start_time=None,
        response_path=response_path,
    )


def test_keybinding_footer_agent_bindings_none_agent() -> None:
    """Test agent bindings when no agent selected."""
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(None)
    binding_keys = [b[0] for b in bindings]

    assert _edit_hooks_key(footer) not in binding_keys  # No fork chat
    assert "r" not in binding_keys
    assert "x" not in binding_keys  # Kill/dismiss only when agent selected


def test_keybinding_footer_agent_cleanup_panel_when_completed_exists() -> None:
    """X opens cleanup when completed agents exist."""
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(None, completed_count=3)

    assert ("X", "cleanup (3 done)") in bindings


def test_keybinding_footer_agent_bindings_running_agent() -> None:
    """Test agent bindings for a running agent."""
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")

    bindings = footer._compute_agent_bindings(agent)
    binding_keys = [b[0] for b in bindings]

    assert "x" in binding_keys  # Kill is available
    assert _edit_hooks_key(footer) not in binding_keys  # No fork chat
    assert ("r", "retry") in bindings


def test_keybinding_footer_agent_bindings_starting_agent() -> None:
    """STARTING agents are killable and can be restarted with a wait target."""
    footer = KeybindingFooter()
    agent = _make_agent(status="STARTING")

    bindings = footer._compute_agent_bindings(agent)

    assert ("x", "dismiss") in bindings
    assert ("w", "edit wait") in bindings


def test_keybinding_footer_agent_bindings_completed_agent_with_chat() -> None:
    """Test agent bindings for completed agent with chat file."""
    footer = KeybindingFooter()
    agent = _make_agent(status="DONE", response_path="/tmp/chat.md")

    bindings = footer._compute_agent_bindings(agent)
    binding_keys = [b[0] for b in bindings]

    assert "x" in binding_keys  # Dismiss is available
    assert "e" in binding_keys  # Edit chat is available


def test_keybinding_footer_agent_bindings_tale_done_with_chat() -> None:
    """Terminal tale rows with chats can be forked."""
    footer = KeybindingFooter()
    agent = _make_agent(status="TALE DONE", response_path="/tmp/chat.md")

    bindings = footer._compute_agent_bindings(agent)

    assert (_edit_hooks_key(footer), "fork") in bindings
    assert ("r", "resume") not in bindings


def test_keybinding_footer_approve_eligible_shows_auto_approve_label() -> None:
    """Approve-eligible agents advertise a single stable auto-approve label.

    The old 3-state cycle was replaced by the Auto-Approve menu, so the footer
    no longer flips between approve/epic/unapprove based on the agent's state.
    """
    footer = KeybindingFooter()
    key = footer._kd("accept_proposal")

    # Every prior cycle state (off / normal / epic) plus the new tale state now
    # collapses to the same label, since `a` always opens the menu.
    for approve, action in (
        (False, None),
        (True, None),
        (True, "epic"),
        (True, "tale"),
    ):
        agent = _make_agent(status="RUNNING")
        agent.approve = approve
        agent.auto_approve_plan_action = action

        bindings = footer._compute_agent_bindings(agent)
        labels = [label for k, label in bindings if k == key]

        assert "auto-approve" in labels
        assert "approve" not in labels
        assert "epic" not in labels
        assert "unapprove" not in labels


def test_keybinding_footer_non_eligible_agent_omits_auto_approve_label() -> None:
    """Terminal agents (e.g. DONE) are not approve-eligible, so no menu label."""
    footer = KeybindingFooter()
    key = footer._kd("accept_proposal")
    agent = _make_agent(status="DONE", response_path="/tmp/chat.md")

    bindings = footer._compute_agent_bindings(agent)

    assert (key, "auto-approve") not in bindings


def test_keybinding_footer_group_focused_overrides_x_label() -> None:
    """When a group banner is focused (no marks), x reads 'kill/dismiss group'."""
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(None, group_focused=True)
    assert ("x", "kill/dismiss group") in bindings


def test_keybinding_footer_collapsed_panel_focus_advertises_panel_cleanup() -> None:
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(None, collapsed_panel_focused=True)

    assert ("x", "kill/dismiss panel") in bindings
    assert not any(label == "kill/dismiss group" for _, label in bindings)


def test_keybinding_footer_expanded_panel_focus_advertises_navigation() -> None:
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(
        None,
        panel_focused=True,
        panel_collapsed=False,
    )

    labels = [label for _, label in bindings]
    assert "kill/dismiss panel" in labels
    assert "panel" in labels
    assert "member" in labels
    assert "collapse panel" in labels
    assert labels.count("enter panel") == 2


def test_keybinding_footer_named_panel_advertises_tribe_fork() -> None:
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(
        None,
        panel_focused=True,
        focused_panel_key="builders",
    )

    assert (_edit_hooks_key(footer), "fork tribe") in bindings


def test_keybinding_footer_default_panel_omits_tribe_targets() -> None:
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(
        None,
        panel_focused=True,
        focused_panel_key=None,
    )

    assert (_edit_hooks_key(footer), "fork tribe") not in bindings
    assert ("W", "wait for tribe") not in bindings


def test_keybinding_footer_clan_advertises_clan_fork() -> None:
    footer = KeybindingFooter()
    clan = _make_agent()
    clan.is_clan_container = True
    clan.agent_clan = "builders"

    bindings = footer._compute_agent_bindings(clan)

    assert (_edit_hooks_key(footer), "fork clan") in bindings
    assert (_edit_hooks_key(footer), "fork clan") in footer._compute_agent_bindings(
        clan,
        marked_count=2,
    )
    assert (_edit_hooks_key(footer), "fork clan") not in footer._compute_agent_bindings(
        clan,
        group_focused=True,
    )


def test_keybinding_footer_family_member_advertises_shell_digits() -> None:
    footer = KeybindingFooter()
    root = _make_agent()
    root.agent_name = "alpha--plan"
    root.agent_family = "alpha"
    root.plan_chain_root = True
    root.role_suffix = "--plan"
    child = _make_agent()
    child.agent_name = "alpha--code"
    child.agent_family = "alpha"
    child.role_suffix = "--code"
    child.parent_timestamp = "20260101000000"
    root.followup_agents = [child]
    # Production sets this in ``sort_and_reorder`` (``_attach_family_containers``).
    child.family_container = root
    assert root.is_family_container_row is True
    assert child.is_family_container_row is False

    bindings = footer._compute_agent_bindings(child)

    assert ("0-9", "shell") in bindings
    assert ("0-9", "member") not in bindings
    assert ("0-9", "shell") not in footer._compute_agent_bindings(
        child,
        group_focused=True,
    )


def test_keybinding_footer_canonical_collapsed_panel_focus_shows_expand() -> None:
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(
        None,
        panel_focused=True,
        panel_collapsed=True,
    )

    labels = [label for _, label in bindings]
    assert "expand panel" in labels
    assert "collapse panel" not in labels
    assert "enter panel" not in labels


def test_keybinding_footer_marks_take_priority_over_collapsed_panel_label() -> None:
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(
        None,
        marked_count=2,
        collapsed_panel_focused=True,
    )

    assert ("x", "kill/dismiss panel") not in bindings
    assert ("x", "kill/dismiss (2 marked)") in bindings


def test_keybinding_footer_panel_label_absent_for_other_focus_types() -> None:
    footer = KeybindingFooter()
    agent = _make_agent()

    assert ("x", "kill/dismiss panel") not in footer._compute_agent_bindings(agent)
    assert ("x", "kill/dismiss panel") not in footer._compute_agent_bindings(
        None, group_focused=True
    )


def test_keybinding_footer_marks_take_priority_over_group_label() -> None:
    """Marks override the group-focused x label."""
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(None, marked_count=2, group_focused=True)
    assert ("x", "kill/dismiss group") not in bindings
    assert any(label == "kill/dismiss (2 marked)" for _, label in bindings)
    assert ("s", "save/dismiss (2 marked)") in bindings


def test_keybinding_footer_marked_agents_advertise_bulk_chat_edit() -> None:
    """Marked agent sets expose e as a bulk chat edit action."""
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")

    bindings = footer._compute_agent_bindings(agent, marked_count=3)

    assert ("e", "edit chats (3 marked)") in bindings
    assert ("e", "edit chat") not in bindings


def test_keybinding_footer_attempt_view_only_when_history_present() -> None:
    """D appears only when the agent has prior attempt records."""
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")

    no_history_bindings = footer._compute_agent_bindings(agent)
    assert "D" not in [b[0] for b in no_history_bindings]

    agent.attempt_history = [
        AttemptRecord(
            attempt_number=1,
            status="failed",
            start_epoch=0.0,
            end_epoch=1.0,
            model=None,
            used_fallback=False,
            error_snippet="err",
            error_full="err",
            live_reply_path="/x",
            timestamps_path="/y",
        )
    ]
    with_history_bindings = footer._compute_agent_bindings(agent)
    assert any(
        key == "D" and label == "attempt view" for key, label in with_history_bindings
    )


def test_keybinding_footer_artifacts_and_attempts_have_separate_keys() -> None:
    """a advertises artifacts while D keeps attempt-history fallback separate."""
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")
    agent.attempt_history = [
        AttemptRecord(
            attempt_number=1,
            status="failed",
            start_epoch=0.0,
            end_epoch=1.0,
            model=None,
            used_fallback=False,
            error_snippet="err",
            error_full="err",
            live_reply_path="/x",
            timestamps_path="/y",
        )
    ]

    bindings = footer._compute_agent_bindings(agent, has_artifact_files=True)

    assert ("a", "artifact files") in bindings
    assert ("D", "attempt view") in bindings


def test_keybinding_footer_agent_neighbor_binding_for_single_neighbor() -> None:
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")

    bindings = footer._compute_agent_bindings(agent, neighbor_count=1)

    assert ("~", "neighbor") in bindings


def test_keybinding_footer_agent_neighbor_binding_for_multiple_neighbors() -> None:
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")

    bindings = footer._compute_agent_bindings(agent, neighbor_count=3)

    assert ("~", "neighbors (3)") in bindings


def test_keybinding_footer_agent_neighbor_binding_hidden_without_neighbors() -> None:
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")

    bindings = footer._compute_agent_bindings(agent, neighbor_count=0)

    assert ("~", "neighbor") not in bindings
    assert not any(label.startswith("neighbors") for _key, label in bindings)


def _workspace_agent() -> Agent:
    """Agent with a managed workspace so the tmux bindings are emitted."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workspace_num=2,
    )


def test_keybinding_footer_tmux_label_plain_without_cached_choices() -> None:
    footer = KeybindingFooter()
    agent = _workspace_agent()

    bindings = footer._compute_agent_bindings(agent, tmux_choice_count=0)

    labels = [label for _key, label in bindings]
    assert "tmux" in labels
    assert not any(label.startswith("tmux choices") for label in labels)
    assert "tmux (primary)" in labels


def test_keybinding_footer_tmux_choices_label_with_cached_choices() -> None:
    footer = KeybindingFooter()
    agent = _workspace_agent()

    bindings = footer._compute_agent_bindings(agent, tmux_choice_count=4)

    labels = [label for _key, label in bindings]
    assert "tmux choices (4)" in labels
    assert "tmux" not in labels
    assert "tmux (primary)" in labels


def _monitor_agent(*, monitor_state: str = "running") -> Agent:
    status = "MONITORING" if monitor_state == "running" else "MONITORED"
    agent = _make_agent(status=status)
    agent.agent_family_role = "monitor"
    agent.role_suffix = "--mon"
    agent.monitor_id = "m123"
    agent.monitor_state = monitor_state
    agent.monitor_command = "just check-full"
    agent.monitor_label = "just check"
    assert agent.is_monitor is True
    return agent


def _monitor_starter_agent() -> Agent:
    agent = _make_agent(status="DONE")
    agent.agent_family_role = "root"
    agent.role_suffix = "--0"
    agent.monitor_id = "m123"
    agent.monitor_state = None
    assert agent.is_monitor is False
    return agent


def test_keybinding_footer_running_monitor_advertises_stop_monitor() -> None:
    footer = KeybindingFooter()
    agent = _monitor_agent(monitor_state="running")

    bindings = footer._compute_agent_bindings(agent)

    assert ("x", "stop monitor") in bindings
    assert ("0-9", "shell") not in bindings


def test_keybinding_footer_running_family_monitor_advertises_shell_digits() -> None:
    footer = KeybindingFooter()
    root = _make_agent()
    root.agent_name = "alpha--0"
    root.agent_family = "alpha"
    root.plan_chain_root = True
    root.role_suffix = "--0"
    monitor = _monitor_agent(monitor_state="running")
    monitor.family_container = root

    bindings = footer._compute_agent_bindings(monitor)

    assert ("x", "stop monitor") in bindings
    assert ("0-9", "shell") in bindings


def test_keybinding_footer_terminal_monitor_omits_stop_monitor() -> None:
    footer = KeybindingFooter()
    agent = _monitor_agent(monitor_state="completed")

    bindings = footer._compute_agent_bindings(agent)

    assert ("x", "dismiss") in bindings
    assert ("x", "stop monitor") not in bindings
    labels = [label for _key, label in bindings]
    assert "retry" in labels
    assert "name" in labels


def test_keybinding_footer_monitor_starter_advertises_normal_agent_bindings() -> None:
    footer = KeybindingFooter()
    agent = _monitor_starter_agent()

    bindings = footer._compute_agent_bindings(agent)

    assert ("x", "dismiss") in bindings
    assert ("x", "stop monitor") not in bindings
    labels = [label for _key, label in bindings]
    assert "retry" in labels


def test_keybinding_footer_running_monitor_omits_agent_only_bindings() -> None:
    """A monitor has no LLM process, so agent-only actions must not leak in."""
    footer = KeybindingFooter()
    agent = _monitor_agent(monitor_state="running")

    bindings = footer._compute_agent_bindings(agent)

    labels = [label for _key, label in bindings]
    assert "retry" not in labels
    assert "name" not in labels


def test_keybinding_footer_artifact_file_viewer_active_advertises_focus_key() -> None:
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")

    inactive = footer._compute_agent_bindings(agent, artifact_file_viewer_active=False)
    active = footer._compute_agent_bindings(agent, artifact_file_viewer_active=True)

    assert ("<tab>", "focus artifact pane") not in inactive
    assert ("q", "close artifact pane") not in inactive
    assert ("<tab>", "focus artifact pane") in active
    assert ("q", "close artifact pane") in active
