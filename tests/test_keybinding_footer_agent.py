"""Tests for the ace TUI keybinding footer agent bindings."""

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import KeybindingFooter


def _make_agent(
    status: str = "RUNNING",
    response_path: str | None = None,
) -> Agent:
    """Create a test Agent for binding tests."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test_feature",
        project_file="/tmp/test.gp",
        status=status,
        start_time=None,
        response_path=response_path,
    )


def test_keybinding_footer_agent_bindings_none_agent() -> None:
    """Test agent bindings when no agent selected."""
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(None)
    binding_keys = [b[0] for b in bindings]

    assert "r" not in binding_keys  # No revive chat
    assert "x" not in binding_keys  # Kill/dismiss only when agent selected


def test_keybinding_footer_agent_bindings_running_agent() -> None:
    """Test agent bindings for a running agent."""
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")

    bindings = footer._compute_agent_bindings(agent)
    binding_keys = [b[0] for b in bindings]

    assert "x" in binding_keys  # Kill is available
    assert "r" not in binding_keys  # No revive chat


def test_keybinding_footer_agent_bindings_completed_agent_with_chat() -> None:
    """Test agent bindings for completed agent with chat file."""
    footer = KeybindingFooter()
    agent = _make_agent(status="DONE", response_path="/tmp/chat.md")

    bindings = footer._compute_agent_bindings(agent)
    binding_keys = [b[0] for b in bindings]

    assert "x" in binding_keys  # Dismiss is available
    assert "e" in binding_keys  # Edit chat is available


def test_keybinding_footer_agent_pinned_panel_binding() -> None:
    """Test that pinned panel jump binding appears when pinned agents exist."""
    footer = KeybindingFooter()
    agent = _make_agent(status="RUNNING")

    # No pinned agents: no jump binding
    bindings = footer._compute_agent_bindings(agent, pinned_count=0)
    binding_labels = [b[1] for b in bindings]
    assert not any("pinned" in label for label in binding_labels)

    # Pinned agents exist: jump binding present
    bindings = footer._compute_agent_bindings(agent, pinned_count=3)
    binding_labels = [b[1] for b in bindings]
    assert any("pinned (3)" in label for label in binding_labels)
