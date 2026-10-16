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
_MANAGED_TEMPLATE_OPTIONAL_VARS = frozenset({"projection_note"})

#: Project-only header for committed ``AGENTS.md`` files (design D6). It names
#: the memory source and the per-invocation bundle inspectors. Bundles never
#: render through the agent template, so they never contain this text.
PROJECT_PROJECTION_NOTE = (
    "> This file is generated from `sase/memory/` by `sase memory init`; "
    "edit the notes, not\n"
    "> this file. SASE-launched agents get a per-invocation bundle from the same "
    "notes plus\n"
    "> home memory and a provider directive. Preview it with "
    "`sase instructions render`; see\n"
    "> what an agent received with `sase instructions show NAME`."
)


def render_agents_template(
    root: Path,
    *,
    title: str,
    core_sections: str,
    reference_entries: str = "",
    web_sections: str = "",
    minimal: bool = False,
    projection_note: str | None = None,
) -> tuple[str | None, str | None]:
    """Render the resolved agent template or return an actionable blocker."""
    override, resolve_error = resolve_amd_template_override(root, minimal=minimal)
    if resolve_error is not None:
        return None, resolve_error
    filename = MINIMAL_TEMPLATE_FILENAME if minimal else MANAGED_TEMPLATE_FILENAME
    required = _MINIMAL_TEMPLATE_VARS if minimal else _MANAGED_TEMPLATE_VARS
    optional = frozenset() if minimal else _MANAGED_TEMPLATE_OPTIONAL_VARS
    # The packaged template inlines `{{ projection_note }}` directly before the
    # `## Core Memory` heading (an `{% if %}` block would be reflowed by
    # prettier into a space-padded single line), so the separating blank lines
    # travel with the value itself. Empty stays byte-identical to the old text.
    header = ""
    if projection_note and not minimal:
        header = projection_note.rstrip("\n") + "\n\n"
    rendered, error = render_markdown_template(
        package="sase.amd",
        filename=f"templates/{filename}",
        required_variables=required,
        optional_variables=optional,
        context={
            "title": title,
            "core_sections": core_sections,
            "web_sections": web_sections,
            "reference_entries": reference_entries,
            "projection_note": header,
        },
        override_path=override,
    )
    if rendered is None:
        return None, error
    return number_agent_document_sections(rendered), None


__all__ = [
    "MANAGED_TEMPLATE_FILENAME",
    "MINIMAL_TEMPLATE_FILENAME",
    "PROJECT_PROJECTION_NOTE",
    "render_agents_template",
]
