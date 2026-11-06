"""Rich and JSON presentation for ``sase agent recover``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.agent.hijack.preview import (
    HijackContinuationPrompt,
    RecoveryAction,
    RecoveryPreview,
)
from sase.agent.hijack.recover_common import RecoveryResult

RECOVER_JSON_SCHEMA_VERSION = 1


def menu_envelope(name: str, preview: RecoveryPreview) -> dict[str, Any]:
    """Serialize the read-only menu in the shared recover JSON shape."""
    return {
        "schema_version": RECOVER_JSON_SCHEMA_VERSION,
        "ok": True,
        "mode": "menu",
        "name": name,
        "state": preview.state,
        "hijack_id": preview.hijack_id,
        "revision": preview.revision,
        "default_action": preview.default_action,
        "header": dict(preview.header),
        "actions": preview.to_dict()["actions"],
        "action": None,
        "target": None,
        "model_changed": None,
        "prompt_supplied": None,
        "plan": None,
        "result": None,
        "error": None,
        "message": "Read-only recovery menu; no action was taken.",
    }


def dry_run_envelope(
    name: str,
    preview: RecoveryPreview,
    *,
    action: str,
    target: str,
    model_changed: bool,
    prepared: HijackContinuationPrompt,
    prompt_supplied: bool,
) -> dict[str, Any]:
    """Serialize a side-effect-free action preflight."""
    return {
        "schema_version": RECOVER_JSON_SCHEMA_VERSION,
        "ok": True,
        "mode": "dry_run",
        "name": name,
        "state": preview.state,
        "hijack_id": preview.hijack_id,
        "revision": preview.revision,
        "default_action": preview.default_action,
        "header": dict(preview.header),
        "actions": preview.to_dict()["actions"],
        "action": action,
        "target": target,
        "model_changed": model_changed,
        "prompt_supplied": prompt_supplied,
        "plan": {
            "context_mode": prepared.context_mode,
            "transcript_path": prepared.transcript_path,
            "expanded_prompt_bytes": prepared.expanded_prompt_bytes,
            "budget_decision": dict(prepared.budget_decision),
        },
        "result": None,
        "error": None,
        "message": f"Read-only {action} preview; nothing was launched.",
    }


def result_envelope(
    name: str,
    action: str,
    result: RecoveryResult,
    *,
    exit_code: int,
    message: str,
) -> dict[str, Any]:
    """Serialize a completed, queued, refused, or failed recovery."""
    error = None
    if exit_code != 0:
        error = {
            "code": str(dict(result.detail).get("code") or result.kind),
            "message": message,
        }
    return {
        "schema_version": RECOVER_JSON_SCHEMA_VERSION,
        "ok": exit_code == 0,
        "mode": "recovery",
        "name": name,
        "state": result.detail.get("state"),
        "hijack_id": result.hijack_id,
        "revision": result.revision,
        "default_action": None,
        "header": None,
        "actions": None,
        "action": action,
        "target": result.concrete_target,
        "model_changed": result.model_changed,
        "prompt_supplied": None,
        "plan": None,
        "result": {
            "kind": result.kind,
            "successor": result.successor,
            "launch_identity": result.launch_identity,
            "admission_request_id": result.admission_request_id,
            "detail": dict(result.detail),
        },
        "error": error,
        "message": message,
    }


def error_envelope(
    name: str,
    message: str,
    *,
    code: str,
    mode: str,
    action: object,
    preview: RecoveryPreview | None = None,
) -> dict[str, Any]:
    """Serialize an input, preview, or preflight error."""
    return {
        "schema_version": RECOVER_JSON_SCHEMA_VERSION,
        "ok": False,
        "mode": mode,
        "name": name,
        "state": preview.state if preview is not None else None,
        "hijack_id": preview.hijack_id if preview is not None else None,
        "revision": preview.revision if preview is not None else None,
        "default_action": preview.default_action if preview is not None else None,
        "header": dict(preview.header) if preview is not None else None,
        "actions": preview.to_dict()["actions"] if preview is not None else None,
        "action": action,
        "target": None,
        "model_changed": None,
        "prompt_supplied": None,
        "plan": None,
        "result": None,
        "error": {"code": code, "message": message},
        "message": message,
    }


def default_result_message(result: RecoveryResult) -> str:
    """Return a concise public message when the backend has none."""
    if result.kind == "queued":
        return "Recovery is queued; the held workspace stays pinned until ownership transfers."
    if result.kind == "launched":
        return f"Recovery launched {result.successor or 'a successor'} in the held workspace."
    if result.kind == "already_resolved":
        return "The hijack was already resolved."
    if result.kind == "already_resolving":
        return "A recovery resolution is already in progress."
    return "Hijack recovery did not complete."


def render_recovery_menu(
    preview: RecoveryPreview,
    *,
    selected_action: str | None = None,
) -> Panel:
    """Render the accepted grouped recovery menu with concrete targets."""
    name = str(preview.header.get("agent_name") or "unknown")
    workspace = preview.header.get("workspace_num")
    workspace_label = (
        f"ws #{workspace}" if workspace is not None else "workspace unknown"
    )
    title = Text(f"⏏ Recover {name}  ·  HIJACKED  ·  {workspace_label}")
    title.stylize("bold #FF5FAF")
    header = _header_text(preview.header)
    body = Table.grid(padding=(0, 1), expand=True)
    body.add_column(width=2, no_wrap=True)
    body.add_column(min_width=20, no_wrap=True)
    body.add_column(ratio=1)

    groups: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("KEEP THE WORK", ("escalate", "continue", "instruct")),
        ("START OVER", ("restart",)),
        ("INSPECT OR LEAVE", ("view_diff", "shell", "dismiss")),
    )
    rows = {item.action: item for item in preview.actions}
    for heading, action_names in groups:
        members = [rows[action] for action in action_names if action in rows]
        if not members:
            continue
        body.add_row("", Text(heading, style="bold #8787AF"), "")
        for row in members:
            selected = selected_action or preview.default_action
            is_selected = row.action == selected
            marker = Text("›" if is_selected else " ", style="bold #FF5FAF")
            label = Text(row.label or row.action.replace("_", " ").title())
            details = _action_detail(row)
            if row.available:
                label.stylize("bold #FF5FAF" if is_selected else "#FFFFFF")
            else:
                label.stylize("dim")
                details.stylize("dim")
            body.add_row(marker, label, details)

    caption = Text("j/k move  ·  enter select  ·  Esc decide later", style="dim")
    return Panel(
        _menu_content(header, body),
        title=title,
        subtitle=caption,
        border_style="#FF5FAF",
    )


def _menu_content(header: Text, body: Table) -> Table:
    content = Table.grid(padding=(0, 0), expand=True)
    content.add_column(ratio=1)
    content.add_row(header)
    content.add_row(Text(""))
    content.add_row(body)
    return content


def _header_text(header: Mapping[str, Any]) -> Text:
    model = str(header.get("model_display") or "unknown model")
    duration = str(header.get("run_duration_display") or "duration unknown")
    age = str(header.get("hijacked_ago") or "")
    files = header.get("files_changed", 0)
    insertions = header.get("insertions", 0)
    deletions = header.get("deletions", 0)
    text = Text(f"{model}  ·  ran {duration}")
    if age:
        text.append(f"  ·  hijacked {age}")
    text.append(f"\n{files} files +{insertions} −{deletions}")
    last_tool = str(header.get("last_tool") or "")
    if last_tool:
        last_tool_age = str(header.get("last_tool_age") or "")
        text.append(f"  ·  last tool: {last_tool}")
        if last_tool_age:
            text.append(f" ({last_tool_age})")
    return text


def _action_detail(row: RecoveryAction) -> Text:
    if not row.available:
        return Text(row.reason or "Unavailable")
    detail = row.detail.strip()
    target = row.target
    if target and target not in detail:
        detail = f"{detail}  ·  {target}" if detail else target
    return Text(detail)


__all__ = [
    "RECOVER_JSON_SCHEMA_VERSION",
    "default_result_message",
    "dry_run_envelope",
    "error_envelope",
    "menu_envelope",
    "render_recovery_menu",
    "result_envelope",
]
