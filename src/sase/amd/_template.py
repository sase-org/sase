"""Loading and rendering for human-editable AMD agent templates."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from jinja2 import Environment, StrictUndefined, TemplateError, meta

from ._config import resolve_amd_template_override
from ._shared import read_text

MANAGED_TEMPLATE_FILENAME = "AGENTS.template.md"
MINIMAL_TEMPLATE_FILENAME = "AGENTS.minimal.template.md"
_MANAGED_TEMPLATE_VARS = frozenset({"title", "tier1_sections", "tier2_entries"})
_MINIMAL_TEMPLATE_VARS = frozenset({"title", "tier1_sections"})

_ENVIRONMENT = Environment(
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
)


def _template_label(path: Path | None, *, minimal: bool) -> str:
    if path is not None:
        return str(path)
    filename = MINIMAL_TEMPLATE_FILENAME if minimal else MANAGED_TEMPLATE_FILENAME
    return f"packaged {filename}"


def _load_template(root: Path, *, minimal: bool) -> tuple[str | None, str, str | None]:
    override, resolve_error = resolve_amd_template_override(root, minimal=minimal)
    label = _template_label(override, minimal=minimal)
    if resolve_error is not None:
        return None, label, resolve_error
    if override is not None:
        content, read_error = read_text(override)
        return content, label, read_error

    filename = MINIMAL_TEMPLATE_FILENAME if minimal else MANAGED_TEMPLATE_FILENAME
    source = resources.files("sase.amd").joinpath("templates", filename)
    try:
        return source.read_text(encoding="utf-8"), label, None
    except OSError as exc:
        return None, label, f"{label}: failed to read template: {exc}"


def render_agents_template(
    root: Path,
    *,
    title: str,
    tier1_sections: str,
    tier2_entries: str = "",
    minimal: bool = False,
) -> tuple[str | None, str | None]:
    """Render the resolved agent template or return an actionable blocker."""
    content, label, load_error = _load_template(root, minimal=minimal)
    if load_error is not None or content is None:
        return None, load_error or f"{label}: failed to load template"

    required = _MINIMAL_TEMPLATE_VARS if minimal else _MANAGED_TEMPLATE_VARS
    try:
        parsed = _ENVIRONMENT.parse(content)
    except TemplateError as exc:
        return None, f"{label}: template error: {exc}"

    variables = meta.find_undeclared_variables(parsed)
    missing = sorted(required - variables)
    if missing:
        placeholders = ", ".join(f"{{{{ {name} }}}}" for name in missing)
        return None, f"{label}: template must contain {placeholders}"
    unknown = sorted(variables - required)
    if unknown:
        placeholders = ", ".join(f"{{{{ {name} }}}}" for name in unknown)
        return None, f"{label}: unknown template placeholder {placeholders}"

    try:
        template = _ENVIRONMENT.from_string(content)
        return (
            template.render(
                title=title,
                tier1_sections=tier1_sections,
                tier2_entries=tier2_entries,
            ),
            None,
        )
    except TemplateError as exc:
        return None, f"{label}: template error: {exc}"


__all__ = [
    "MANAGED_TEMPLATE_FILENAME",
    "MINIMAL_TEMPLATE_FILENAME",
    "render_agents_template",
]
