"""Loading and rendering for human-editable AMD agent templates."""

from __future__ import annotations

from pathlib import Path

from ._config import resolve_amd_template_override
from ._section_numbers import number_agent_document_sections
from sase.mdtemplates import render_markdown_template

MANAGED_TEMPLATE_FILENAME = "AGENTS.template.md"
MINIMAL_TEMPLATE_FILENAME = "AGENTS.minimal.template.md"
_MANAGED_TEMPLATE_VARS = frozenset(
    {"title", "core_sections", "web_sections", "reference_entries"}
)
_MINIMAL_TEMPLATE_VARS = frozenset({"title", "core_sections"})


def render_agents_template(
    root: Path,
    *,
    title: str,
    core_sections: str,
    reference_entries: str = "",
    web_sections: str = "",
    minimal: bool = False,
) -> tuple[str | None, str | None]:
    """Render the resolved agent template or return an actionable blocker."""
    override, resolve_error = resolve_amd_template_override(root, minimal=minimal)
    if resolve_error is not None:
        return None, resolve_error
    filename = MINIMAL_TEMPLATE_FILENAME if minimal else MANAGED_TEMPLATE_FILENAME
    required = _MINIMAL_TEMPLATE_VARS if minimal else _MANAGED_TEMPLATE_VARS
    rendered, error = render_markdown_template(
        package="sase.amd",
        filename=f"templates/{filename}",
        required_variables=required,
        context={
            "title": title,
            "core_sections": core_sections,
            "web_sections": web_sections,
            "reference_entries": reference_entries,
        },
        override_path=override,
    )
    if rendered is None:
        return None, error
    return number_agent_document_sections(rendered), None


__all__ = [
    "MANAGED_TEMPLATE_FILENAME",
    "MINIMAL_TEMPLATE_FILENAME",
    "render_agents_template",
]
