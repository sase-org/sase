"""Tests for the ace TUI keybinding footer agent bindings."""

from sase.ace.tui.models.agent import Agent, AgentType, AttemptRecord
from sase.ace.tui.widgets import KeybindingFooter


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

    assert "f" not in binding_keys  # No fork chat
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
    assert "f" not in binding_keys  # No fork chat
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

    assert ("f", "fork") in bindings
    assert ("r", "resume") not in bindings


def test_keybinding_footer_group_focused_overrides_x_label() -> None:
    """When a group banner is focused (no marks), x reads 'kill/dismiss group'."""
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(None, group_focused=True)
    assert ("x", "kill/dismiss group") in bindings


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
    """A advertises artifacts while D keeps attempt-history fallback separate."""
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

    bindings = footer._compute_agent_bindings(agent, has_agent_artifacts=True)

    assert ("A", "artifacts") in bindings
    assert ("D", "attempt view") in bindings


def test_keybinding_footer_agent_sibling_binding_for_single_sibling() -> None:
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")

    bindings = footer._compute_agent_bindings(agent, sibling_count=1)

    assert ("~", "sibling") in bindings


def test_keybinding_footer_agent_sibling_binding_for_multiple_siblings() -> None:
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")

    bindings = footer._compute_agent_bindings(agent, sibling_count=3)

    assert ("~", "siblings (3)") in bindings


def test_keybinding_footer_agent_sibling_binding_hidden_without_siblings() -> None:
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")

    bindings = footer._compute_agent_bindings(agent, sibling_count=0)

    assert ("~", "sibling") not in bindings
    assert not any(label.startswith("siblings") for _key, label in bindings)


def test_keybinding_footer_agent_artifact_viewer_active_advertises_focus_key() -> None:
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")

    inactive = footer._compute_agent_bindings(agent, artifact_viewer_active=False)
    active = footer._compute_agent_bindings(agent, artifact_viewer_active=True)

    assert ("<tab>", "focus artifact pane") not in inactive
    assert ("q", "close artifact pane") not in inactive
    assert ("<tab>", "focus artifact pane") in active
    assert ("q", "close artifact pane") in active
