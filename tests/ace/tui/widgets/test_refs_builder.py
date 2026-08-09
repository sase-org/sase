"""Tests for the Patch REFS detail builder."""

from rich.text import Text

from sase.ace.patch import Patch
from sase.ace.tui.widgets.refs_builder import build_refs_section


def test_refs_builder_renders_stored_values_without_resolution() -> None:
    patch = Patch(
        name="example",
        description="Example",
        parent=None,
        status="Draft",
        refs=["research:202607/report.md", "file:default:abc123"],
    )
    text = Text()

    build_refs_section(text, patch)

    assert text.plain == ("REFS:\n  research:202607/report.md\n  file:default:abc123\n")
