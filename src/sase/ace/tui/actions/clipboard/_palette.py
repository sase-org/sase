"""Warm-only context construction for the ACE Copy as palette."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from sase.core.commit_footer_facade import parse_commit_footer
from sase.project_display_names import humanize_cl_name

from ...commands import (
    CommandContext,
    build_command_catalog,
    is_command_available,
)
from ...copy_targets import copy_targets_for
from ...keymaps import footer_key_display

if TYPE_CHECKING:
    from ...modals.copy_as_types import CopyAsContext


_ARTIFACT_SUBTABS = frozenset({"commits", "plans", "chats", "bugs", "files"})
_DISPATCH_ORDER: dict[str, tuple[str, ...]] = {
    "changespecs": (
        "raw",
        "with_snapshot",
        "bug",
        "pr_number",
        "name",
        "link",
        "spec",
        "snapshot",
    ),
    "artifacts_commits": (
        "snapshot",
        "reference",
        "handoff",
        "link",
        "json",
        "sha",
        "message",
        "repo_sha",
        "plan",
    ),
    "artifacts_plans": (
        "snapshot",
        "reference",
        "handoff",
        "link",
        "json",
        "path",
        "title",
        "body",
    ),
    "artifacts_chats": (
        "snapshot",
        "reference",
        "handoff",
        "link",
        "json",
        "path",
        "agent",
        "transcript",
    ),
    "artifacts_files": (
        "snapshot",
        "reference",
        "handoff",
        "link",
        "json",
        "contents",
        "path",
        "source",
        "label",
    ),
    "artifacts_bugs": (
        "snapshot",
        "reference",
        "handoff",
        "link",
        "json",
        "number",
        "url",
        "title",
        "prompt",
    ),
    "agents": ("chat", "file_path", "name", "prompt", "snapshot"),
    "axe": ("visible", "full", "snapshot"),
}


def build_copy_as_context(app: Any) -> CopyAsContext | None:
    """Capture a palette context without filesystem or subprocess work."""

    tab = app.current_tab
    subtab = getattr(app, "current_artifacts_subtab", "prs")
    if tab == "changespecs" and subtab in _ARTIFACT_SUBTABS:
        return _build_artifacts_context(app, subtab)
    if tab == "changespecs":
        return _build_changespec_context(app)
    if tab == "agents":
        return _build_agent_context(app)
    return _build_axe_context(app)


def _build_changespec_context(app: Any) -> CopyAsContext | None:
    changespecs = getattr(app, "changespecs", ())
    index = getattr(app, "current_idx", 0)
    changespec = changespecs[index] if 0 <= index < len(changespecs) else None
    if changespec is None:
        _warn(app, "No ChangeSpec to copy")
        return None

    ctx = CommandContext(
        tab="changespecs",
        artifacts_subtab="prs",
        changespec=changespec,
    )
    previews = {
        "raw": _short(
            getattr(changespec, "description", "")
            or f"{changespec.status} · {humanize_cl_name(changespec.name)}"
        ),
        "with_snapshot": "ChangeSpec + current pane",
        "bug": _short(getattr(changespec, "bug", "")),
        "pr_number": _number_from_url(getattr(changespec, "pr_url", None)),
        "name": humanize_cl_name(changespec.name),
        "link": _short(getattr(changespec, "pr_url", "") or ""),
        "spec": _short(getattr(changespec, "file_path", "")),
        "snapshot": "current pane",
    }
    project = (
        getattr(changespec, "project_display_name", None)
        or getattr(changespec, "project_query_name", None)
        or "ChangeSpecs"
    )
    subtitle = f"{project} · {humanize_cl_name(changespec.name)}"
    return _context_from_registry(
        app,
        group="changespecs",
        command_context=ctx,
        subtitle=subtitle,
        unknown_context="ChangeSpecs",
        previews=previews,
    )


def _build_agent_context(app: Any) -> CopyAsContext | None:
    resolver = getattr(app, "_get_selected_agent", None)
    try:
        agent = resolver() if callable(resolver) else None
    except Exception:
        agent = None
    if agent is None:
        _warn(app, "No agent selected")
        return None

    file_path = _warm_agent_file_path(app)
    ctx = CommandContext(
        tab="agents",
        agent=agent,
        file_panel_visible=file_path is not None,
    )
    presented_name = (
        getattr(agent, "presented_agent_name", None)
        or getattr(agent, "display_name", None)
        or getattr(agent, "cl_name", "agent")
    )
    project = getattr(agent, "project_display_name", None)
    subtitle = f"{project} · {presented_name}" if project else str(presented_name)
    response_path = getattr(agent, "response_path", None)
    status = str(getattr(agent, "status", "")).lower()
    previews = {
        "chat": _short(response_path or ""),
        "file_path": _short(file_path or ""),
        "name": _short(str(presented_name)),
        "prompt": f"{status} agent prompt" if status else "agent prompt",
        "snapshot": "current pane",
    }
    return _context_from_registry(
        app,
        group="agents",
        command_context=ctx,
        subtitle=subtitle,
        unknown_context="agents",
        previews=previews,
    )


def _build_axe_context(app: Any) -> CopyAsContext | None:
    items = getattr(app, "_axe_items", ())
    index = getattr(app, "current_idx", 0)
    item = items[index] if 0 <= index < len(items) else None
    if item is None:
        _warn(app, "No AXE item to copy")
        return None

    ctx = CommandContext(tab="axe", axe_item=item)
    subtitle = _axe_item_label(item)
    output = getattr(app, "_axe_output", "")
    output_preview = _output_hint(output)
    if getattr(app, "_axe_current_view", "axe") != "axe":
        output_preview = (
            f"command output · {output_preview}" if output_preview else "command output"
        )
    previews = {
        "visible": output_preview or "visible output",
        "full": output_preview or "full output",
        "snapshot": "current pane",
    }
    return _context_from_registry(
        app,
        group="axe",
        command_context=ctx,
        subtitle=subtitle,
        unknown_context="axe",
        previews=previews,
    )


def _build_artifacts_context(app: Any, subtab: str) -> CopyAsContext | None:
    pane = _artifact_pane(app, subtab)
    if pane is None:
        _warn(app, f"No {subtab} entry to copy")
        return None

    visible_targets = _entry_targets(pane)
    all_marks = getattr(app, "_artifacts_marked_targets", {})
    marks = all_marks.get(subtab, set()) if isinstance(all_marks, dict) else set()
    marked_targets = tuple(target for target in visible_targets if target in marks)
    marked = bool(marks)
    if marked and not marked_targets:
        _warn(app, f"No marked {subtab} entries are visible")
        return None

    selected_target = _selected_entry_target(pane)
    selected_objects = _artifact_objects(
        pane,
        subtab,
        marked_targets
        if marked
        else (() if selected_target is None else (selected_target,)),
    )
    if not marked:
        selected = _selected_artifact_object(pane, subtab)
        if selected is not None and not selected_objects:
            selected_objects = (selected,)
        if selected_target is None and not selected_objects:
            _warn(app, f"No {subtab} entry to copy")
            return None

    count = len(marked_targets) if marked else 1
    available, previews = _artifact_target_state(
        group=f"artifacts_{subtab}",
        subtab=subtab,
        pane=pane,
        objects=selected_objects,
        marked=marked,
        count=count,
    )
    ctx = CommandContext(
        tab="changespecs",
        artifacts_subtab=subtab,  # type: ignore[arg-type]
        artifact_selection_present=True,
        artifact_available_targets=frozenset(available),
    )
    display_name = _artifact_display_name(pane, selected_objects)
    if marked:
        subtitle = f"{count} marked {subtab}"
        if display_name:
            subtitle += f" · {display_name}"
    else:
        identity = _artifact_identity(
            subtab, selected_objects[0] if selected_objects else None
        )
        subtitle = " · ".join(part for part in (display_name, identity) if part)
        if not subtitle:
            subtitle = f"Selected {subtab[:-1] if subtab.endswith('s') else subtab}"

    return _context_from_registry(
        app,
        group=f"artifacts_{subtab}",
        command_context=ctx,
        subtitle=subtitle,
        unknown_context=subtab.title(),
        previews=previews,
        marked=marked,
    )


def _context_from_registry(
    app: Any,
    *,
    group: str,
    command_context: CommandContext,
    subtitle: str,
    unknown_context: str,
    previews: dict[str, str],
    marked: bool = False,
) -> CopyAsContext | None:
    from ...modals.copy_as_types import CopyAsContext, CopyAsRow

    keys = app._keymap_registry.copy_mode.keys.get(group, {})
    if not isinstance(keys, dict):
        return None

    catalog = {
        spec.id: spec
        for spec in build_command_catalog(app._keymap_registry)
        if spec.executor.kind == "copy_mode_key"
    }
    dispatch_winners = _dispatch_winners(group, keys)
    rows: list[CopyAsRow] = []
    for target in copy_targets_for(group):
        key = keys.get(target.target)
        spec_id = f"copy.{group}.{target.target}"
        if target.target == "pr_number" and not isinstance(key, str):
            key = keys.get("cl_number")
            spec_id = f"copy.{group}.cl_number"
        if not isinstance(key, str):
            continue
        if dispatch_winners.get(key) != target.target:
            continue
        spec = catalog.get(spec_id)
        if spec is None or not is_command_available(spec, command_context):
            continue
        label = (
            target.plural_label
            if marked and target.accepts_marks
            else target.palette_label
        )
        rows.append(
            CopyAsRow(
                key=key,
                key_display=footer_key_display(key),
                target=target.target,
                label=label,
                category=target.category,
                preview=previews.get(target.target, ""),
            )
        )
    if not rows:
        return None
    return CopyAsContext(
        group=group,
        subtitle=_short(subtitle, limit=92),
        unknown_context=unknown_context,
        rows=tuple(rows),
    )


def _dispatch_winners(group: str, keys: dict[str, str]) -> dict[str, str]:
    winners: dict[str, str] = {}
    for target in _DISPATCH_ORDER[group]:
        key = keys.get(target)
        if target == "pr_number" and not isinstance(key, str):
            key = keys.get("cl_number")
        if isinstance(key, str):
            winners.setdefault(key, target)
    return winners


def _artifact_target_state(
    *,
    group: str,
    subtab: str,
    pane: Any,
    objects: tuple[Any, ...],
    marked: bool,
    count: int,
) -> tuple[set[str], dict[str, str]]:
    available = {target.target for target in copy_targets_for(group)}
    previews = {
        "reference": _marked_hint(count, "artifact references")
        if marked
        else "artifact reference",
        "link": _marked_hint(count, "Markdown links") if marked else "Markdown link",
        "json": _marked_hint(count, "metadata records")
        if marked
        else "metadata record",
        "handoff": _marked_hint(count, "prompt references")
        if marked
        else "new agent prompt",
        "snapshot": "current Artifacts pane",
    }
    first = objects[0] if objects else None
    suffix = f" · +{count - 1}" if marked and count > 1 else ""

    if subtab == "commits":
        commit = getattr(first, "commit", None)
        message = _commit_message(first)
        plan = _commit_plan_reference(message)
        values = {
            "sha": getattr(commit, "full_id", ""),
            "message": getattr(commit, "subject", "") or message,
            "repo_sha": (
                f"{getattr(first, 'repo', '')}@{getattr(commit, 'short_id', '')}"
                if first is not None
                else ""
            ),
            "plan": plan or "",
        }
        if not plan and not marked:
            available.discard("plan")
    elif subtab == "plans":
        values = _plan_values(pane, first)
        for target in ("path", "title", "body"):
            if not values.get(target) and not marked:
                available.discard(target)
    elif subtab == "chats":
        agent = getattr(first, "agent_local_name", None) or getattr(
            first, "agent", None
        )
        excerpt = (
            getattr(first, "prompt_snippet", None)
            or getattr(first, "response_snippet", None)
            or ""
        )
        values = {
            "path": getattr(first, "absolute_path", ""),
            "agent": agent or "",
            "transcript": excerpt or _size_hint(getattr(first, "size_bytes", None)),
        }
        if not agent and not marked:
            available.discard("agent")
    elif subtab == "bugs":
        number = getattr(first, "number", None)
        values = {
            "number": f"#{number}" if number is not None else "",
            "url": getattr(first, "url", ""),
            "title": getattr(first, "title", ""),
            "prompt": getattr(first, "body", "") or getattr(first, "title", ""),
        }
    else:
        values = {} if marked else _file_target_values(pane, first)
        counts = _file_target_counts(pane, objects)
        labels = {
            "contents": "copyable contents",
            "reference": "artifact references",
            "link": "Markdown links",
            "path": "stored paths",
            "source": "source paths",
            "label": "artifact-file labels",
            "json": "metadata records",
            "handoff": "prompt references",
        }
        for target, representable_count in counts.items():
            if not representable_count:
                available.discard(target)
            elif marked:
                previews[target] = _marked_count_hint(
                    representable_count,
                    count,
                    labels[target],
                )

    for target, value in values.items():
        if value:
            previews[target] = _short(str(value)) + suffix
        elif marked:
            previews[target] = _marked_hint(count, target.replace("_", " "))
    return available, previews


def _artifact_pane(app: Any, subtab: str) -> Any | None:
    resolver = getattr(app, f"_{subtab}_pane", None)
    if not callable(resolver):
        return getattr(app, f"{subtab}_pane", None)
    try:
        return resolver()
    except Exception:
        return None


def _entry_targets(pane: Any) -> tuple[tuple[str, ...], ...]:
    resolver = getattr(pane, "entry_targets", None)
    if not callable(resolver):
        return ()
    try:
        return tuple(resolver())
    except Exception:
        return ()


def _selected_entry_target(pane: Any) -> tuple[str, ...] | None:
    resolver = getattr(pane, "selected_entry_target", None)
    if not callable(resolver):
        return None
    try:
        return resolver()
    except Exception:
        return None


def _selected_artifact_object(pane: Any, subtab: str) -> Any | None:
    if subtab == "commits":
        resolver = getattr(pane, "_selected_entry", None)
        return resolver() if callable(resolver) else None
    if subtab == "plans":
        resolver = getattr(pane, "selected_row", None)
        return resolver() if callable(resolver) else None
    if subtab in {"chats", "files"}:
        return getattr(pane, "selected_entry", None)
    return getattr(pane, "selected_issue", None)


def _artifact_objects(
    pane: Any,
    subtab: str,
    targets: Iterable[tuple[str, ...]],
) -> tuple[Any, ...]:
    ordered_targets = tuple(targets)
    if not ordered_targets:
        return ()
    if subtab == "commits":
        result = getattr(pane, "result", None)
        candidates = () if result is None else getattr(result, "commits", ())
        commit_by_target: dict[tuple[str, ...], Any] = {
            ("commit", entry.repo, entry.commit.full_id): entry for entry in candidates
        }
        return tuple(
            commit_by_target[target]
            for target in ordered_targets
            if target in commit_by_target
        )
    if subtab in {"plans", "chats", "files"}:
        rows = getattr(pane, "_rows", {}).values()
        row_by_target: dict[tuple[str, ...], Any] = {}
        for row in rows:
            if subtab == "plans":
                from ...widgets.artifacts.plans_list import plan_row_target

                target = plan_row_target(row)
                value = row
            elif subtab == "chats":
                from ...widgets.artifacts.chats_list import chat_row_target

                target = chat_row_target(row)
                value = row.entry
            else:
                from ...widgets.artifacts.files_list import file_row_target

                target = file_row_target(row)
                value = row.entry
            row_by_target[target] = value
        return tuple(
            row_by_target[target]
            for target in ordered_targets
            if target in row_by_target
        )
    issues = getattr(pane, "issues", ())
    target_for = getattr(pane, "_issue_target", None)
    if not callable(target_for):
        return ()
    issue_by_target: dict[tuple[str, ...], Any] = {
        target_for(issue): issue for issue in issues
    }
    return tuple(
        issue_by_target[target]
        for target in ordered_targets
        if target in issue_by_target
    )


def _artifact_display_name(pane: Any, objects: tuple[Any, ...]) -> str:
    direct = getattr(pane, "_project_display_name", None)
    if isinstance(direct, str) and direct:
        return direct
    snapshot = getattr(pane, "snapshot", None) or getattr(pane, "_snapshot", None)
    display = getattr(snapshot, "display_name", None)
    if isinstance(display, str) and display:
        return display
    display_names = getattr(snapshot, "display_names", None)
    project = getattr(objects[0], "project", None) if objects else None
    if isinstance(display_names, Mapping) and isinstance(project, str):
        return str(display_names.get(project, project))
    filters = getattr(pane, "filters", None)
    scope = (
        getattr(filters, "project", None)
        or getattr(pane, "project_scope", None)
        or project
    )
    return str(scope or "")


def _artifact_identity(subtab: str, value: Any | None) -> str:
    if value is None:
        return ""
    if subtab == "commits":
        commit = getattr(value, "commit", None)
        return f"{getattr(value, 'repo', '')}@{getattr(commit, 'short_id', '')}"
    if subtab == "plans":
        if getattr(value, "proposal", None) is not None:
            return str(value.proposal.title)
        if getattr(value, "issue", None) is not None:
            return f"{value.issue.id} · {value.issue.title}"
        if getattr(value, "archive", None) is not None:
            plan = value.archive.plan
            return str(plan.title or plan.name)
        return str(getattr(value, "row_id", ""))
    if subtab == "chats":
        return str(getattr(value, "basename", ""))
    if subtab == "bugs":
        return f"#{getattr(value, 'number', '')} · {getattr(value, 'title', '')}"
    return str(getattr(value, "label", "") or getattr(value, "path", ""))


def _plan_values(pane: Any, row: Any | None) -> dict[str, str]:
    if row is None:
        return {"path": "", "title": "", "body": ""}
    if getattr(row, "proposal", None) is not None:
        return {
            "path": row.proposal.plan_path,
            "title": row.proposal.title,
            "body": row.proposal.body,
        }
    if getattr(row, "archive", None) is not None:
        plan = row.archive.plan
        return {
            "path": plan.path,
            "title": plan.title or plan.name,
            "body": plan.body,
        }
    issue = getattr(row, "issue", None)
    path = getattr(issue, "design", "") if issue is not None else ""
    body = (
        getattr(issue, "description", "") or getattr(issue, "notes", "")
        if issue is not None
        else ""
    )
    return {
        "path": path or "",
        "title": getattr(issue, "title", "") if issue is not None else "",
        "body": body or "",
    }


def _file_target_values(pane: Any, entry: Any | None) -> dict[str, str]:
    if entry is None:
        return {
            "contents": "",
            "reference": "",
            "link": "",
            "path": "",
            "source": "",
            "label": "",
            "json": "",
            "handoff": "",
        }

    artifact_id = str(getattr(entry, "id", "") or "")
    label = str(getattr(entry, "label", "") or "")
    kind = str(getattr(entry, "kind", "") or "")
    size = _size_hint(getattr(entry, "size_bytes", None))
    view_mode = _warm_file_view_mode(pane, entry, selected=True)
    reference = f"file:{artifact_id}" if artifact_id else ""
    metadata_hint = " · ".join(part for part in (kind, size, "metadata") if part)
    return {
        "contents": " · ".join(part for part in (view_mode, size) if part),
        "reference": f"@{reference}" if reference else "",
        "link": f"[{label}]({reference})" if label and reference else "",
        "path": str(getattr(entry, "path", "") or ""),
        "source": str(getattr(entry, "source_path", "") or ""),
        "label": label,
        "json": metadata_hint,
        "handoff": f"@{reference} · new agent prompt" if reference else "",
    }


def _file_target_counts(pane: Any, entries: tuple[Any, ...]) -> dict[str, int]:
    reference_count = sum(bool(getattr(entry, "id", None)) for entry in entries)
    return {
        "contents": sum(
            _warm_file_view_mode(pane, entry, selected=len(entries) == 1)
            in {"markdown", "text"}
            for entry in entries
        ),
        "reference": reference_count,
        "link": sum(
            bool(getattr(entry, "id", None) and getattr(entry, "label", None))
            for entry in entries
        ),
        "path": sum(bool(getattr(entry, "path", None)) for entry in entries),
        "source": sum(bool(getattr(entry, "source_path", None)) for entry in entries),
        "label": sum(bool(getattr(entry, "label", None)) for entry in entries),
        "json": len(entries),
        "handoff": reference_count,
    }


def _warm_file_view_mode(
    pane: Any,
    entry: Any,
    *,
    selected: bool,
) -> str:
    """Return an already-classified file view mode without filesystem work."""

    if selected:
        selected_mode = getattr(pane, "selected_view_mode", None)
        if isinstance(selected_mode, str):
            return selected_mode

    snapshot = getattr(pane, "snapshot", None) or getattr(pane, "_snapshot", None)
    view_mode_for = getattr(snapshot, "view_mode_for", None)
    if callable(view_mode_for):
        try:
            mode = view_mode_for(entry)
        except Exception:
            mode = None
        if isinstance(mode, str):
            return mode

    view_modes = getattr(snapshot, "view_modes", None)
    if isinstance(view_modes, Mapping):
        mode = view_modes.get(getattr(entry, "id", None))
        if isinstance(mode, str):
            return mode
    return ""


def _commit_message(entry: Any | None) -> str:
    commit = getattr(entry, "commit", None)
    if commit is None:
        return ""
    subject = str(getattr(commit, "subject", "") or "")
    body = str(getattr(commit, "body", "") or "")
    return f"{subject}\n\n{body}" if body else subject


def _commit_plan_reference(message: str) -> str | None:
    try:
        footer = parse_commit_footer(message)
    except Exception:
        return None
    tag = next(
        (tag for tag in reversed(footer.tags) if tag.raw_key == "SASE_PLAN"),
        None,
    )
    return None if tag is None else tag.label


def _warm_agent_file_path(app: Any) -> str | None:
    try:
        from ...widgets import AgentDetail
        from ...widgets.file_panel import AgentFilePanel

        detail = app.query_one("#agent-detail-panel", AgentDetail)
        if not detail.is_file_visible():
            return None
        return detail.query_one(
            "#agent-file-panel", AgentFilePanel
        ).get_current_file_path()
    except Exception:
        return None


def _axe_item_label(item: Any) -> str:
    if hasattr(item, "lumberjack_name") and hasattr(item, "chop_name"):
        return f"{item.lumberjack_name} · {item.chop_name}"
    if hasattr(item, "name"):
        return str(item.name)
    if hasattr(item, "slot"):
        return f"Command #{item.slot}"
    return "AXE selection"


def _output_hint(output: str) -> str:
    if not output or not output.strip():
        return ""
    lines = output.strip().splitlines()
    return _short(f"{len(lines)} lines · {lines[0]}")


def _number_from_url(url: str | None) -> str:
    if not url:
        return ""
    match = re.search(r"/(\d+)(?:/)?$", url)
    return match.group(1) if match else ""


def _size_hint(size: Any) -> str:
    if not isinstance(size, int) or size < 0:
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def _marked_hint(count: int, label: str) -> str:
    return f"{count} marked · {label}"


def _marked_count_hint(representable: int, total: int, label: str) -> str:
    if representable == total:
        return _marked_hint(total, label)
    return f"{representable}/{total} marked · {label}"


def _short(value: str, *, limit: int = 58) -> str:
    collapsed = " ".join(str(value).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def _warn(app: Any, message: str) -> None:
    app.notify(message, severity="warning")


__all__ = ["build_copy_as_context"]
