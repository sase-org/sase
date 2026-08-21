"""Human-readable rendering for finalizer declaration artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def format_context_pretty(payload: Mapping[str, Any]) -> str:
    """Render a compact human-readable finalizer context."""

    context = payload.get("context")
    if not isinstance(context, Mapping):
        return "No finalizer context available."
    lines = [
        f"Finalizer context: {context.get('context_digest', '<unknown>')}",
        f"Run: {context.get('run_id', '<unknown>')}",
        f"Agent: {context.get('agent_id', '<unknown>')}",
        "",
        "Selected instances:",
    ]
    selected = payload.get("selected_instances")
    if isinstance(selected, list) and selected:
        for item in selected:
            if not isinstance(item, Mapping):
                continue
            required = "required" if item.get("submission_required") else "none"
            lines.append(
                "  - "
                f"{item.get('instance_id', '<unknown>')} "
                f"({item.get('provider_ref', '<unknown>')}; submission: {required}; "
                f"trigger: {item.get('trigger', '<unknown>')})"
            )
    else:
        lines.append("  - none")

    obligations = context.get("obligations")
    lines.extend(["", "Repository obligations:"])
    repo_obligations = (
        [
            item
            for item in obligations
            if isinstance(item, Mapping) and item.get("kind") == "repository"
        ]
        if isinstance(obligations, list)
        else []
    )
    if not repo_obligations:
        lines.append("  - none")
    for item in repo_obligations:
        lines.append(
            f"  - {item.get('obligation_id', '<unknown>')} "
            f"{item.get('display_name', '')}".rstrip()
        )
        paths = item.get("paths")
        if isinstance(paths, list):
            for path in paths:
                lines.append(f"      {path}")
    return "\n".join(lines)


__all__ = ["format_context_pretty"]
