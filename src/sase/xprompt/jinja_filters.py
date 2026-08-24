"""Shared Jinja2 filters available to xprompt and workflow prompt bodies."""

from __future__ import annotations

from typing import Any

from jinja2 import Environment


def register_prompt_filters(env: Environment) -> None:
    """Register filters usable from prompt-body Jinja2 templates."""
    env.filters["plan_ref_path"] = _plan_ref_path


def _plan_ref_path(value: Any) -> Any:
    """Return the ``YYYYmm/<name>.md`` portion of a plan path or reference."""
    if not isinstance(value, str):
        return value

    from sase.sdd.plan_refs import plan_reference_display_path

    return plan_reference_display_path(value)
