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

    commit_declaration = payload.get("commit_declaration")
    if isinstance(commit_declaration, Mapping):
        rule = commit_declaration.get("rule")
        lines.extend(["", "Commit declaration:"])
        if isinstance(rule, str) and rule:
            lines.append(f"  {rule}")
        deferral = commit_declaration.get("deferral")
        if isinstance(deferral, Mapping):
            reasons = deferral.get("reasons")
            if isinstance(reasons, list) and reasons:
                lines.append(
                    "  Deferral reasons: "
                    + ", ".join(str(reason) for reason in reasons)
                )
        evidence = commit_declaration.get("repository_evidence")
        if isinstance(evidence, list) and evidence:
            lines.append("  Evidence:")
            for item in evidence:
                if not isinstance(item, Mapping):
                    continue
                display = item.get("display_name") or item.get("repo_id")
                lines.append(f"    - {display}")
                for label, key in (
                    ("run wrote", "run_written_paths"),
                    ("already dirty", "already_dirty_at_run_start_paths"),
                    ("protected", "protected_paths"),
                ):
                    values = item.get(key)
                    if isinstance(values, list) and values:
                        lines.append(
                            f"        {label}: "
                            + ", ".join(str(path) for path in values)
                        )
    return "\n".join(lines)


__all__ = ["format_context_pretty"]
