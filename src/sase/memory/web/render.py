"""Shared rendering for glossary memory-web closure output.

Memory-web and preview surfaces resolve a
:class:`~sase.memory.web.resolution.GlossaryClosure` through identical code,
so retained glossary rendering routes through these helpers.
"""

from __future__ import annotations

from sase.memory.web.resolution import (
    GlossaryClosure,
    GlossaryClosureNode,
)

_MARKDOWN_MAX_HEADING_LEVEL = 6


def glossary_closure_markdown(closure: GlossaryClosure, *, project_name: str) -> str:
    """Render *closure* as plain Markdown suitable for pasting into a prompt."""
    pieces: list[str] = []
    if project_name:
        pieces.append(f"GLOSSARY: {project_name}\n")
    for node in closure.nodes:
        level = min(node.depth + 1, _MARKDOWN_MAX_HEADING_LEVEL)
        heading = "#" * level
        pieces.append(f"{heading} {node.entry.term}\n")
        pieces.append(f"*{_markdown_provenance(node)}*\n")
        if node.entry.display_aliases:
            pieces.append("aka " + ", ".join(node.entry.display_aliases) + "\n")
        pieces.append(node.entry.definition.strip() + "\n")
    return "\n".join(pieces) + "\n"


def _markdown_provenance(node: GlossaryClosureNode) -> str:
    if node.origin == "requested":
        return "Requested"
    parts = [f"Related · depth {node.depth}"]
    if node.referrer is not None:
        parts.append(
            f'mentioned as "{node.referrer.matched_text}" in {node.referrer.term}'
        )
    if node.also_referenced_by:
        parts.append("also mentioned by " + ", ".join(node.also_referenced_by))
    return " — ".join(parts)


__all__ = [
    "glossary_closure_markdown",
]
