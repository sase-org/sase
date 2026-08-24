"""Shared loading and rendering for packaged Markdown templates."""

from __future__ import annotations

from collections.abc import Mapping, Set
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateError, meta


_ENVIRONMENT = Environment(
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
)


def _read_override(path: Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, f"{path}: failed to read file: {exc}"
    except UnicodeDecodeError as exc:
        return None, f"{path}: failed to decode as UTF-8: {exc}"


def packaged_markdown_text(package: str, filename: str) -> str:
    """Read one UTF-8 Markdown asset from *package*."""
    relative = PurePosixPath(filename)
    return (
        resources.files(package).joinpath(*relative.parts).read_text(encoding="utf-8")
    )


def render_markdown_template(
    *,
    package: str,
    filename: str,
    required_variables: Set[str],
    context: Mapping[str, Any],
    optional_variables: Set[str] = frozenset(),
    override_path: Path | None = None,
) -> tuple[str | None, str | None]:
    """Render a Markdown template or return an actionable labeled error."""
    packaged_label = PurePosixPath(filename).name
    label = (
        str(override_path)
        if override_path is not None
        else f"packaged {packaged_label}"
    )
    if override_path is not None:
        content, read_error = _read_override(override_path)
        if read_error is not None or content is None:
            return None, read_error or f"{label}: failed to load template"
    else:
        try:
            content = packaged_markdown_text(package, filename)
        except OSError as exc:
            return None, f"{label}: failed to read template: {exc}"

    try:
        parsed = _ENVIRONMENT.parse(content)
    except TemplateError as exc:
        return None, f"{label}: template error: {exc}"

    variables = meta.find_undeclared_variables(parsed)
    missing = sorted(required_variables - variables)
    if missing:
        placeholders = ", ".join(f"{{{{ {name} }}}}" for name in missing)
        return None, f"{label}: template must contain {placeholders}"
    unknown = sorted(variables - required_variables - optional_variables)
    if unknown:
        placeholders = ", ".join(f"{{{{ {name} }}}}" for name in unknown)
        return None, f"{label}: unknown template placeholder {placeholders}"

    try:
        return _ENVIRONMENT.from_string(content).render(dict(context)), None
    except TemplateError as exc:
        return None, f"{label}: template error: {exc}"


__all__ = ["packaged_markdown_text", "render_markdown_template"]
