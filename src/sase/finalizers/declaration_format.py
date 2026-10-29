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
    handoff = context.get("handoff")
    if isinstance(handoff, Mapping):
        lines.extend(["", "Staged handoff:"])
        lines.append(
            "  "
            f"{handoff.get('kind', '<unknown>')} "
            f"(staged ref: {handoff.get('staged_ref', '<unknown>')}; "
            "successor workspace: "
            f"{handoff.get('successor_workspace', '<unknown>')})"
        )
        prepared_ref = handoff.get("prepared_intent_ref")
        if isinstance(prepared_ref, str) and prepared_ref:
            lines.append(f"  Prepared intent: {prepared_ref}")
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
        allowed_actions = commit_declaration.get("allowed_repository_actions")
        if isinstance(allowed_actions, list) and allowed_actions:
            lines.append(
                "  Allowed repository actions: "
                + ", ".join(str(action) for action in allowed_actions)
            )
        assigned = commit_declaration.get("assigned_bead")
        if isinstance(assigned, Mapping):
            bead_id = assigned.get("bead_id")
            primary = assigned.get("primary_repo_id")
            if isinstance(bead_id, str) and bead_id:
                suffix = f"; primary repo: {primary}" if primary else ""
                lines.append(f"  Assigned bead: {bead_id}{suffix}")
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
        absorbed = commit_declaration.get("absorbed_raw_commits")
        if isinstance(absorbed, list) and absorbed:
            lines.append("  Absorbed raw commits:")
            for item in absorbed:
                if not isinstance(item, Mapping):
                    continue
                commits = item.get("commits")
                summaries = (
                    ", ".join(
                        f"{str(entry.get('sha', ''))[:12]} "
                        f"{str(entry.get('subject', '')).strip()}".rstrip()
                        for entry in commits
                        if isinstance(entry, Mapping)
                    )
                    if isinstance(commits, list)
                    else ""
                )
                lines.append(f"    - {item.get('repo', '<unknown>')}: {summaries}")
    return "\n".join(lines)


__all__ = ["format_context_pretty"]
