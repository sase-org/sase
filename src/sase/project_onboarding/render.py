"""Rich renderers for the suggest command (plan/progress arrive with cli-add)."""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from typing import Any

GROUP_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("resume", "RESUME", "↻"),
    ("local", "ON THIS MACHINE", "⌂"),
    ("suggested", "SUGGESTED", "○"),
    ("linked", "LINKED TO YOUR PROJECTS", "⇄"),
    ("disabled", "DISABLED PROJECTS", "◐"),
)
"""(group id, human heading, row glyph) in core's fixed group order."""

_HIDDEN_PLURALS = {
    "sidecar": "sidecars",
    "fork": "forks",
    "archived": "archived",
    "enabled_project": "projects",
    "numbered_copy": "numbered copies",
    "third_party_local": "third-party checkouts",
}

_HIDDEN_SINGULARS = {
    "sidecar": "sidecar",
    "fork": "fork",
    "archived": "archived",
    "enabled_project": "enabled project",
    "numbered_copy": "numbered copy",
    "third_party_local": "third-party checkout",
}

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_PUSH_PERMISSIONS = frozenset({"ADMIN", "MAINTAIN", "WRITE"})


def _clean(text: str) -> str:
    """Strip control characters from untrusted provider text."""

    return _CONTROL_RE.sub("", text)


def _relative_age(pushed_at: str, *, now: float | None = None) -> str:
    """Render an ISO timestamp as ``4h``/``9d`` age, or ``""`` when unknown."""

    if not pushed_at:
        return ""
    try:
        parsed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    try:
        stamp = parsed.timestamp()
    except (OSError, OverflowError):
        return ""
    base = datetime.now(UTC).timestamp() if now is None else now
    minutes = max(0, int((base - stamp) // 60))
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"


def _row_meta(row: dict[str, Any]) -> str:
    """Join one classified row's secondary facts for the human line."""

    parts: list[str] = []
    if row.get("group") == "resume":
        status = str(row.get("journal_status") or "running")
        stopped = _relative_age(str(row.get("stopped_at") or ""))
        parts.append(f"{status} · stopped {stopped} ago" if stopped else status)
    visibility = _clean(str(row.get("visibility") or ""))
    if visibility:
        parts.append(visibility)
    age = _relative_age(str(row.get("pushed_at") or ""))
    if age:
        parts.append(age)
    description = _clean(str(row.get("description") or ""))
    if description:
        parts.append(description if len(description) <= 100 else description[:99] + "…")
    if row.get("is_empty") is True:
        parts.append("empty")
    permission = str(row.get("viewer_permission") or "")
    if permission.upper() in _PUSH_PERMISSIONS:
        parts.append("you can push")
    local_path = str(row.get("local_path") or "")
    if local_path:
        parts.append(f"at {local_path}")
    project_key = str(row.get("project_key") or "")
    if project_key:
        parts.append(f"project {project_key}")
    linked_by = row.get("linked_by")
    if isinstance(linked_by, list) and linked_by:
        parts.append(f"linked by {', '.join(str(k) for k in linked_by)}")
    if row.get("group") == "disabled" and project_key:
        parts.append(f"run `sase project enable {project_key}` to re-enable")
    return " · ".join(parts)


def _row_line(row: dict[str, Any], glyph: str) -> list[tuple[str, str]]:
    """Return one ``(segment, style)`` human line for a classified row."""

    display = _clean(str(row.get("display") or row.get("ref") or "?"))
    line: list[tuple[str, str]] = [(f"    {glyph} {display}", "bold")]
    meta = _row_meta(row)
    if meta:
        line.append((f"  {meta}", "dim"))
    return line


def _provider_lines(
    provider: dict[str, Any], *, include_hidden: bool
) -> list[list[tuple[str, str]]]:
    """Return the ``(segment, style)`` human lines for one provider payload."""

    lines: list[list[tuple[str, str]]] = []
    display = _clean(str(provider.get("display") or provider.get("workflow_type")))
    account = _clean(str(provider.get("account") or ""))
    owners = provider.get("owners")
    owner_list = owners if isinstance(owners, list) else []
    groups = provider.get("groups")
    group_list = groups if isinstance(groups, list) else []
    hidden = provider.get("hidden")
    hidden_list = hidden if isinstance(hidden, list) else []
    search_only = provider.get("search_only")
    search_rows = search_only if isinstance(search_only, list) else []

    lines.append([(display, "bold")])
    errors = sum(
        1
        for owner in owner_list
        if isinstance(owner, dict) and owner.get("status") == "error"
    )
    if not owner_list:
        lines.append([("  ○ no owners yet", "dim")])
    elif account:
        lines.append([(f"  ✓ {account} · {len(owner_list)} owners", "green")])
    else:
        lines.append([(f"  ○ {len(owner_list)} owners", "")])
    if errors:
        lines.append([(f"  ⚠ {errors} of {len(owner_list)} owners failed", "yellow")])
    for owner in owner_list:
        if not isinstance(owner, dict):
            continue
        name = _clean(str(owner.get("name") or "?"))
        if owner.get("status") != "error":
            if owner.get("truncated") is True:
                count = owner.get("entry_count")
                shown = f"showing {count} · " if isinstance(count, int) else ""
                lines.append(
                    [
                        (
                            f"  ⓘ {name}: {shown}results truncated "
                            f"— narrow with --owner {name}",
                            "yellow",
                        )
                    ]
                )
            continue
        message = _clean(str(owner.get("message") or "owner failed"))
        remedy = owner.get("remedy_argv")
        detail = f"{name}: {message}"
        if isinstance(remedy, list) and remedy:
            detail += f" — run: {' '.join(str(a) for a in remedy)}"
        if owner.get("stale") is True:
            detail += " (showing cached rows)"
        lines.append([(f"  ⚠ {detail}", "yellow")])

    rows_seen = 0
    by_id = {group.get("id"): group for group in group_list if isinstance(group, dict)}
    for group_id, heading, glyph in GROUP_SECTIONS:
        group = by_id.get(group_id)
        rows = group.get("rows") if isinstance(group, dict) else None
        row_list = (
            [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        )
        if not row_list:
            continue
        rows_seen += len(row_list)
        lines.append([(f"  {heading}", "dim")])
        for row in row_list:
            lines.append(_row_line(row, glyph))

    hidden_counts = [
        (str(h.get("reason") or "?"), int(h.get("count") or 0))
        for h in hidden_list
        if isinstance(h, dict) and int(h.get("count") or 0) > 0
    ]
    if hidden_counts and not include_hidden:
        rendered = " · ".join(
            f"{count} "
            f"{_HIDDEN_SINGULARS.get(reason, reason) if count == 1 else _HIDDEN_PLURALS.get(reason, reason)}"
            for reason, count in hidden_counts
        )
        lines.append([(f"  ┄ {rendered} hidden — use --all", "yellow")])
    if include_hidden and search_rows:
        lines.append([("  HIDDEN", "dim")])
        for row in search_rows:
            if not isinstance(row, dict):
                continue
            reason = str(row.get("hidden_reason") or "?")
            display_row = _clean(str(row.get("display") or row.get("ref") or "?"))
            lines.append(
                [
                    (
                        f"    ┄ {display_row} — "
                        f"{_HIDDEN_SINGULARS.get(reason, reason)}",
                        "dim",
                    )
                ]
            )
            rows_seen += 1

    if rows_seen == 0 and errors == 0:
        if not owner_list:
            lines.append(
                [
                    (
                        "  No candidates — add owners to github_orgs in Config Center.",
                        "",
                    )
                ]
            )
        else:
            lines.append([("  No repositories found.", "")])
    return lines


def _suggest_lines(
    payload: dict[str, Any], *, include_hidden: bool
) -> list[list[tuple[str, str]]]:
    """Return the full human suggest output as styled segment lines."""

    providers = payload.get("providers")
    provider_list = providers if isinstance(providers, list) else []
    if not provider_list:
        return [[("No workspace providers available.", "")]]
    lines: list[list[tuple[str, str]]] = []
    for index, provider in enumerate(provider_list):
        if not isinstance(provider, dict):
            continue
        if index:
            lines.append([("", "")])
        lines.extend(_provider_lines(provider, include_hidden=include_hidden))
    if any(
        isinstance(p, dict)
        and any(
            isinstance(g, dict) and g.get("rows")
            for g in (p.get("groups") or [])
            if isinstance(g, dict)
        )
        for p in provider_list
    ):
        lines.append([("", "")])
        lines.append([("Add one with: sase project add REF", "")])
    return lines


def render_suggest_json(payload: dict[str, Any]) -> str:
    """Return the ``--json`` document for a suggest payload."""

    return json.dumps(payload, indent=2, sort_keys=True)


def print_suggest(payload: dict[str, Any], *, include_hidden: bool) -> None:
    """Print the colored human rendering of a suggest payload."""

    from sase.core.term_color import should_colorize

    lines = _suggest_lines(payload, include_hidden=include_hidden)
    if not should_colorize(sys.stdout):
        for line in lines:
            print("".join(segment for segment, _ in line))
        return
    from rich.console import Console
    from rich.text import Text

    console = Console()
    for line in lines:
        rendered = Text()
        for segment, style in line:
            rendered.append(segment, style=style or None)
        console.print(rendered, soft_wrap=True)


__all__ = [
    "GROUP_SECTIONS",
    "print_suggest",
    "render_suggest_json",
]
