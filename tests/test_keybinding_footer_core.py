"""Tests for the ace TUI keybinding footer core bindings."""

from sase.ace.changespec import ChangeSpec, CommitEntry
from sase.ace.tui.widgets import KeybindingFooter


def _make_changespec(
    name: str = "test_feature",
    description: str = "Test description",
    status: str = "Ready",
    cl: str | None = None,
    parent: str | None = None,
    file_path: str = "/tmp/test.gp",
    commits: list[CommitEntry] | None = None,
) -> ChangeSpec:
    """Create a mock ChangeSpec for testing."""
    return ChangeSpec(
        name=name,
        description=description,
        parent=parent,
        cl=cl,
        status=status,
        test_targets=None,
        kickstart=None,
        file_path=file_path,
        line_number=1,
        commits=commits,
        hooks=None,
        comments=None,
    )


# --- Reword Binding Tests ---


def test_keybinding_footer_reword_hidden_reverted() -> None:
    """Test 'w' (reword) binding is hidden for Reverted status."""
    footer = KeybindingFooter()
    changespec = _make_changespec(status="Reverted", cl="123456")

    bindings = footer._compute_available_bindings(changespec)
    binding_keys = [b[0] for b in bindings]

    assert "w" not in binding_keys


# --- Diff Binding Tests ---


# --- Mail Binding Tests ---


def test_keybinding_footer_mail_visible_ready_status() -> None:
    """Test 'M' binding is visible when status is Ready."""
    footer = KeybindingFooter()
    changespec = _make_changespec(status="Ready", cl="123456")

    bindings = footer._compute_available_bindings(changespec)
    binding_keys = [b[0] for b in bindings]

    assert "M" in binding_keys


# --- Accept Binding Tests ---


def test_keybinding_footer_accept_visible_with_proposals() -> None:
    """Test 'a' (accept) binding is visible when proposed entries exist."""
    footer = KeybindingFooter()
    commits = [CommitEntry(number=1, note="Test", proposal_letter="a")]
    changespec = _make_changespec(status="Ready", commits=commits)

    bindings = footer._compute_available_bindings(changespec)
    binding_keys = [b[0] for b in bindings]

    assert "a" in binding_keys


def test_keybinding_footer_accept_hidden_without_proposals() -> None:
    """Test 'a' (accept) binding is hidden when no proposed entries."""
    footer = KeybindingFooter()
    commits = [CommitEntry(number=1, note="Test")]
    changespec = _make_changespec(status="Ready", commits=commits)

    bindings = footer._compute_available_bindings(changespec)
    binding_keys = [b[0] for b in bindings]

    assert "a" not in binding_keys


# --- Format Bindings Tests ---


# --- Always-Visible Binding Tests ---
