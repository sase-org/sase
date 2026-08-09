"""Build the flat REFS section for a Patch detail view."""

from rich.text import Text

from ...patch import Patch


def build_refs_section(text: Text, patch: Patch) -> None:
    """Append stored artifact references without doing resolution or I/O."""

    if not patch.refs:
        return
    text.append("REFS:\n", style="bold #87D7FF")
    for reference in patch.refs:
        text.append(f"  {reference}\n", style="#87AFFF")


__all__ = ["build_refs_section"]
