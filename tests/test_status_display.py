"""Tests for status colors, available statuses, and display functions."""

from io import StringIO

from sase.ace.patch import Patch
from sase.ace.patch.models import DeltaEntry, DeltaLineStats
from sase.ace.display import display_patch
from sase.ace.status import get_available_statuses
from rich.console import Console


def test_get_available_statuses_includes_others() -> None:
    """Test that get_available_statuses includes other valid statuses."""
    current_status = "Ready"
    available = get_available_statuses(current_status)
    # Should include some other statuses but not current
    assert len(available) > 0
    assert all(s != current_status for s in available)


def test_display_patch_without_hints_returns_empty() -> None:
    """Test that display_patch without hints returns empty dict."""
    # Create a minimal Patch
    patch = Patch(
        name="test_spec",
        description="Test description",
        parent=None,
        cl=None,
        status="Ready",
        file_path="/tmp/test.sase",
        line_number=1,
    )

    # Create a console that writes to a string buffer
    console = Console(file=StringIO(), force_terminal=True)

    # Call without hints (default)
    hint_mappings, hook_hint_to_idx = display_patch(patch, console)

    # Should be empty when hints not enabled
    assert hint_mappings == {}
    assert hook_hint_to_idx == {}


def test_display_patch_renders_deltas_section() -> None:
    """display_patch emits the DELTAS section for non-empty deltas."""
    patch = Patch(
        name="test_spec",
        description="Test description",
        parent=None,
        cl=None,
        status="Ready",
        file_path="/tmp/test.sase",
        line_number=1,
        deltas=[
            DeltaEntry(
                path="src/added.py",
                change_type="A",
                line_stats=DeltaLineStats(added=8),
            ),
            DeltaEntry(
                path="src/modified.py",
                change_type="M",
                line_stats=DeltaLineStats(added=2, modified=3, removed=1),
            ),
            DeltaEntry(
                path="src/deleted.py",
                change_type="D",
                line_stats=DeltaLineStats(removed=5),
            ),
        ],
    )

    buf = StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None, width=200)
    display_patch(patch, console)
    out = buf.getvalue()
    assert "DELTAS:" in out
    assert "+ src/added.py" in out
    assert "~ src/modified.py" in out
    assert "- src/deleted.py" in out
    assert "+8" in out
    assert "+2 ~3 -1" in out
    assert "-5" in out


def test_display_patch_omits_deltas_when_empty() -> None:
    """display_patch does not render DELTAS for None / empty list."""
    patch = Patch(
        name="test_spec",
        description="Test description",
        parent=None,
        cl=None,
        status="Ready",
        file_path="/tmp/test.sase",
        line_number=1,
        deltas=None,
    )
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None, width=200)
    display_patch(patch, console)
    assert "DELTAS:" not in buf.getvalue()

    patch.deltas = []
    buf2 = StringIO()
    console2 = Console(file=buf2, force_terminal=False, color_system=None, width=200)
    display_patch(patch, console2)
    assert "DELTAS:" not in buf2.getvalue()


def test_display_patch_renders_stored_refs() -> None:
    patch = Patch(
        name="test_spec",
        description="Test description",
        parent=None,
        cl=None,
        status="Ready",
        file_path="/tmp/test.sase",
        line_number=1,
        refs=["research:202607/report.md"],
    )
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None, width=200)

    display_patch(patch, console)

    output = buf.getvalue()
    assert "REFS:" in output
    assert "research:202607/report.md" in output
