"""Tests for the ace TUI keybinding footer core bindings."""

from unittest.mock import patch

from sase.ace.patch import Patch, CommitEntry
from sase.ace.tui.widgets import KeybindingFooter
from sase.ace.tui.widgets.keybinding_footer import _MODE_BADGE_STYLE


def _make_patch(
    name: str = "test_feature",
    description: str = "Test description",
    status: str = "Ready",
    cl: str | None = None,
    parent: str | None = None,
    file_path: str = "/tmp/test.sase",
    commits: list[CommitEntry] | None = None,
) -> Patch:
    """Create a mock Patch for testing."""
    return Patch(
        name=name,
        description=description,
        parent=parent,
        cl=cl,
        status=status,
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
    patch = _make_patch(status="Reverted", cl="123456")

    bindings = footer._compute_available_bindings(patch)
    binding_keys = [b[0] for b in bindings]

    assert "w" not in binding_keys


# --- Diff Binding Tests ---


# --- Mail Binding Tests ---


def test_keybinding_footer_mail_visible_ready_status() -> None:
    """Test 'M' binding is visible when status is Ready."""
    footer = KeybindingFooter()
    patch = _make_patch(status="Ready", cl="123456")

    bindings = footer._compute_available_bindings(patch)
    binding_keys = [b[0] for b in bindings]

    assert "M" in binding_keys


# --- Accept Binding Tests ---


def test_keybinding_footer_accept_visible_with_proposals() -> None:
    """Test 'A' (accept) binding is visible when proposed entries exist."""
    footer = KeybindingFooter()
    commits = [CommitEntry(number=1, note="Test", proposal_letter="a")]
    patch = _make_patch(status="Ready", commits=commits)

    bindings = footer._compute_available_bindings(patch)
    binding_keys = [b[0] for b in bindings]

    assert "A" in binding_keys


def test_keybinding_footer_accept_hidden_without_proposals() -> None:
    """Test 'A' (accept) binding is hidden when no proposed entries."""
    footer = KeybindingFooter()
    commits = [CommitEntry(number=1, note="Test")]
    patch = _make_patch(status="Ready", commits=commits)

    bindings = footer._compute_available_bindings(patch)
    binding_keys = [b[0] for b in bindings]

    assert "A" not in binding_keys


# --- Format Bindings Tests ---


# --- Custom Registry Tests ---


def test_keybinding_footer_custom_registry_changes_keys() -> None:
    """Test that a non-default registry changes the displayed keys."""
    from sase.ace.tui.keymaps import (
        KeymapRegistry,
        AppKeymaps,
        load_builtin_app_defaults,
    )

    footer = KeybindingFooter()
    kwargs = load_builtin_app_defaults()
    kwargs.update(accept_proposal="Z", show_diff="D")
    custom_app = AppKeymaps(**kwargs)
    footer.set_keymap_registry(KeymapRegistry(app=custom_app))

    commits = [CommitEntry(number=1, note="Test", proposal_letter="a")]
    patch = _make_patch(status="Ready", cl="123456", commits=commits)

    bindings = footer._compute_available_bindings(patch)
    binding_keys = [b[0] for b in bindings]

    assert "Z" in binding_keys  # accept_proposal remapped
    assert "D" in binding_keys  # show_diff remapped
    assert "a" not in binding_keys  # original key gone
    assert "d" not in binding_keys  # original key gone


def test_keybinding_footer_custom_registry_axe_key() -> None:
    """Test that remapped kill_agent key appears in axe bindings."""
    from sase.ace.tui.keymaps import (
        KeymapRegistry,
        AppKeymaps,
        load_builtin_app_defaults,
    )

    footer = KeybindingFooter()
    kwargs = load_builtin_app_defaults()
    kwargs.update(kill_agent="K")
    custom_app = AppKeymaps(**kwargs)
    footer.set_keymap_registry(KeymapRegistry(app=custom_app))

    bindings = footer._compute_axe_bindings("axe")
    assert bindings[0][0] == "K"


# --- Chip Formatter Tests ---


def test_format_bindings_inline_uses_middle_dot_separator() -> None:
    """Chips on a single line are separated by `` · ``."""
    footer = KeybindingFooter()

    text = footer._format_bindings_inline([("a", "alpha"), ("b", "beta")])

    assert " · " in text.plain
    # The sort puts ``a`` before ``b`` alphabetically.
    assert text.plain == "a alpha · b beta"


def test_format_bindings_inline_sort_preserved() -> None:
    """Symbol keys sort before alphabetic keys (existing rule)."""
    footer = KeybindingFooter()

    text = footer._format_bindings_inline(
        [("z", "last"), ("<esc>", "esc"), ("a", "alpha")]
    )

    # ``<esc>`` (symbol) before ``a``/``z`` (alpha).
    assert text.plain.startswith("<esc> esc")


def test_format_bindings_grid_layout_columns_and_padding() -> None:
    """Grid layout pads chips to common width and uses ``\\n`` between rows."""
    footer = KeybindingFooter()

    bindings = [("a", "x"), ("bb", "yy"), ("c", "z"), ("d", "w")]
    grid = footer._format_bindings_grid(bindings, columns=2)

    # Two rows, two chips each.
    lines = grid.plain.split("\n")
    assert len(lines) == 2
    # Each chip in row 0 should still be intact (no chip split across newline).
    for line in lines:
        # No isolated key character with no following space-label.
        assert line.strip()


def test_grid_chip_never_split_across_newline() -> None:
    """A chip's ``key⎵label`` token is always preserved on a single row."""
    footer = KeybindingFooter()

    bindings = [
        ("alpha", "first"),
        ("beta", "second"),
        ("gamma", "third"),
        ("delta", "fourth"),
        ("epsilon", "fifth"),
    ]
    grid = footer._format_bindings_grid(bindings, columns=2)

    for chip_key, chip_label in bindings:
        chip = f"{chip_key} {chip_label}"
        # The chip text must appear contiguously (no ``\n`` inside it).
        assert chip in grid.plain
        # And the chip cannot straddle a newline boundary.
        for line in grid.plain.split("\n"):
            if chip_key in line and chip_label in line:
                assert chip in line


def test_layout_falls_back_to_inline_when_width_unknown() -> None:
    """Without a known width, the footer renders inline."""
    footer = KeybindingFooter()

    result = footer._layout([("a", "alpha"), ("b", "beta")], mode_label=None)

    # No newline → inline layout chosen.
    assert "\n" not in result.plain


def test_layout_emits_grid_when_width_is_narrow() -> None:
    """A narrow content width forces the grid layout with the badge on its own row."""
    footer = KeybindingFooter()
    bindings = [
        ("a", "alpha"),
        ("b", "beta"),
        ("c", "gamma"),
        ("d", "delta"),
        ("e", "epsilon"),
        ("f", "zeta"),
    ]

    with patch.object(KeybindingFooter, "_available_content_width", return_value=20):
        result = footer._layout(bindings, mode_label="LEADER")

    # Multi-line output and the badge sits on the first row alone.
    lines = result.plain.split("\n")
    assert len(lines) >= 2
    assert lines[0].strip() == "LEADER"


def test_layout_mode_badge_uses_gold_span_exactly_once() -> None:
    """The mode badge text is styled ``bold black on #FFD700`` and not duplicated."""
    footer = KeybindingFooter()

    with patch.object(KeybindingFooter, "_available_content_width", return_value=200):
        result = footer._layout([("a", "alpha")], mode_label="LEADER")

    # ``LEADER`` should appear once in the plain text.
    assert result.plain.count("LEADER") == 1
    # And there should be exactly one span carrying the badge style.
    badge_spans = [s for s in result.spans if str(s.style) == _MODE_BADGE_STYLE]
    assert len(badge_spans) == 1


def test_layout_grid_columns_scale_with_width() -> None:
    """A wider content budget produces fewer rows for the same chip set."""
    footer = KeybindingFooter()
    bindings = [
        ("a", "alpha"),
        ("b", "beta"),
        ("c", "gamma"),
        ("d", "delta"),
        ("e", "epsilon"),
        ("f", "zeta"),
    ]

    with patch.object(KeybindingFooter, "_available_content_width", return_value=20):
        narrow = footer._layout(bindings, mode_label=None)

    with patch.object(KeybindingFooter, "_available_content_width", return_value=40):
        wide = footer._layout(bindings, mode_label=None)

    narrow_rows = narrow.plain.count("\n") + 1
    wide_rows = wide.plain.count("\n") + 1
    assert wide_rows <= narrow_rows


# --- Always-Visible Binding Tests ---
