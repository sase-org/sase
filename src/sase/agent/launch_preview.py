"""Read-only launch preview and approval request files."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.agent.launch_executor_types import LaunchExecutionContext
from sase.core.agent_launch_wire import (
    LaunchFanoutPlanWire,
    agent_launch_wire_to_json_dict,
)

LAUNCH_PREVIEW_SCHEMA_VERSION = 1
LAUNCH_REQUEST_FILE = "launch_request.json"
LAUNCH_PREVIEW_FILE = "launch_preview.md"
LAUNCH_RESPONSE_FILE = "launch_response.json"


def _new_launch_request_id() -> str:
    """Return a globally unique host-side launch approval request id."""
    return f"launch-{uuid4()}"


def build_launch_preview_request(
    *,
    plan: LaunchFanoutPlanWire,
    context: LaunchExecutionContext,
    source_surface: str,
    request_id: str | None = None,
    submitted_prompt: str | None = None,
    created_at_unix: float | None = None,
    slot_contexts: Mapping[int, LaunchExecutionContext] | None = None,
    slot_extra_env: Mapping[int, Mapping[str, str]] | None = None,
    slot_planned_names: Mapping[int, str | None] | None = None,
) -> dict[str, Any]:
    """Build a deterministic launch preview/request payload.

    The payload records the already-normalized fanout graph and host context
    without claiming workspaces or spawning child processes.
    """
    created = time.time() if created_at_unix is None else created_at_unix
    request_id = request_id or _new_launch_request_id()
    slots: list[dict[str, Any]] = []
    kinds: Counter[str] = Counter()
    models: Counter[str] = Counter()
    for slot in plan.slots:
        slot_ctx = (
            slot_contexts.get(slot.slot_index, context) if slot_contexts else context
        )
        env = dict(slot_extra_env.get(slot.slot_index, {})) if slot_extra_env else {}
        planned_name = (
            slot_planned_names.get(slot.slot_index) if slot_planned_names else None
        )
        kinds[slot.launch_kind] += 1
        parsed_model, alias_overrides = _model_directives_for_preview(slot.prompt)
        model = slot.model or parsed_model
        if model:
            models[model] += 1
        slots.append(
            {
                "slot_index": slot.slot_index,
                "launch_kind": slot.launch_kind,
                "prompt": slot.prompt,
                "prompt_snippet": _prompt_snippet(slot.prompt),
                "prompt_sha256": _sha256(slot.prompt),
                "planned_name": planned_name,
                "timestamp": slot.timestamp,
                "workflow_name": slot.workflow_name,
                "model": model,
                "model_alias_overrides": alias_overrides,
                "repeat_name": slot.repeat_name,
                "wait_for_previous": slot.wait_for_previous,
                "name_generated": slot.name_generated,
                "workspace": _context_preview(slot_ctx),
                "extra_env_keys": sorted(env),
            }
        )

    return {
        "schema_version": LAUNCH_PREVIEW_SCHEMA_VERSION,
        "request_id": request_id,
        "created_at_unix": created,
        "source_surface": source_surface,
        "all_or_nothing": True,
        "response_file": LAUNCH_RESPONSE_FILE,
        "submitted_prompt_snippet": (
            None if submitted_prompt is None else _prompt_snippet(submitted_prompt)
        ),
        "submitted_prompt_sha256": (
            None if submitted_prompt is None else _sha256(submitted_prompt)
        ),
        "launch_kind": plan.launch_kind,
        "slot_count": len(slots),
        "fanout_counts": {
            "slots": len(slots),
            "launch_kinds": dict(sorted(kinds.items())),
            "models": dict(sorted(models.items())),
        },
        "plan": agent_launch_wire_to_json_dict(plan),
        "slots": slots,
    }


def write_launch_preview_files(
    request: Mapping[str, Any],
    *,
    response_dir: Path | None = None,
) -> dict[str, Path]:
    """Write ``launch_request.json`` and ``launch_preview.md`` for a request."""
    request_id = str(request["request_id"])
    if response_dir is None:
        from sase.core.paths import sase_subdir

        response_dir = sase_subdir("launch_requests") / request_id
    response_dir.mkdir(parents=True, exist_ok=True)
    request_path = response_dir / LAUNCH_REQUEST_FILE
    preview_path = response_dir / LAUNCH_PREVIEW_FILE
    response_path = response_dir / LAUNCH_RESPONSE_FILE
    request_path.write_text(
        json.dumps(dict(request), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    preview_path.write_text(_render_launch_preview_markdown(request), encoding="utf-8")
    if response_path.exists():
        response_path.unlink()
    return {
        "response_dir": response_dir,
        "request": request_path,
        "preview": preview_path,
        "response": response_path,
    }


def _render_launch_preview_markdown(request: Mapping[str, Any]) -> str:
    """Render a human-readable launch preview with complete prompts."""
    slots = [slot for slot in request.get("slots", []) if isinstance(slot, Mapping)]
    declared_slot_count = int(request.get("slot_count") or 0)
    slot_count = max(declared_slot_count, len(slots))
    source = str(request.get("source_surface") or "unknown")
    request_id = str(request.get("request_id") or "")
    policy = "all-or-nothing" if request.get("all_or_nothing") else "batch"
    summary = [
        f"**{_agent_count_label(slot_count)}**",
        f"source `{source}`",
        policy,
    ]
    model_summary = _model_summary_for_preview(request)
    if model_summary:
        summary.append(f"models {model_summary}")
    if request_id:
        summary.append(f"request `{request_id}`")
    lines = [
        "# Launch Preview",
        "",
        " · ".join(summary),
        "",
    ]
    for ordinal, slot in enumerate(slots, start=1):
        workspace = slot.get("workspace")
        project = (
            workspace.get("project_name") if isinstance(workspace, Mapping) else None
        )
        name = str(slot.get("planned_name") or "assigned at spawn")
        model = str(slot.get("model") or "default")
        alias_overrides = slot.get("model_alias_overrides")
        override_suffix = _format_alias_overrides(alias_overrides)
        kind = str(slot.get("launch_kind") or "agent")
        prompt = str(slot.get("prompt") or "")
        prompt_sha256 = str(slot.get("prompt_sha256") or "")
        prompt_sha_short = prompt_sha256[:12] if prompt_sha256 else "unknown"
        opening_fence, closing_fence = _markdown_code_fence(prompt, "sase")
        lines.extend(
            [
                f"## Agent {ordinal} of {slot_count} · {project or 'unknown project'}",
                "",
                f"model `{model}`{override_suffix} · kind `{kind}` · name `{name}`",
                "",
                opening_fence,
            ]
        )
        lines.extend(prompt.split("\n") if prompt else [""])
        lines.extend(
            [
                closing_fence,
                "",
                f"SHA-256 `{prompt_sha_short}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _agent_count_label(count: int) -> str:
    noun = "agent" if count == 1 else "agents"
    return f"{count} {noun}"


def _markdown_code_fence(text: str, language: str) -> tuple[str, str]:
    longest_backtick_run = max(
        (len(match.group(0)) for match in re.finditer(r"`+", text)),
        default=0,
    )
    fence = "`" * max(3, longest_backtick_run + 1)
    return f"{fence}{language}", fence


def _model_summary_for_preview(request: Mapping[str, Any]) -> str | None:
    """Return a compact, stable model list for the preview header."""
    seen: set[str] = set()
    ordered: list[str] = []
    counts: Counter[str] = Counter()
    for slot in request.get("slots", []):
        if not isinstance(slot, Mapping):
            continue
        model = str(slot.get("model") or "").strip()
        if not model:
            continue
        counts[model] += 1
        if model in seen:
            continue
        seen.add(model)
        ordered.append(model)
    if not ordered:
        return None
    return ", ".join(
        f"`{model}`" if counts[model] == 1 else f"`{model}` x{counts[model]}"
        for model in ordered
    )


def _model_directives_for_preview(prompt: str) -> tuple[str | None, dict[str, str]]:
    """Return parsed ``%model`` fields for read-only launch previews."""
    try:
        from sase.xprompt.directives import extract_prompt_directives

        _, directives = extract_prompt_directives(prompt)
    except Exception:
        return None, {}
    return directives.model, dict(directives.model_alias_overrides)


def _format_alias_overrides(value: object) -> str:
    if not isinstance(value, Mapping) or not value:
        return ""
    rendered = ", ".join(
        f"{key} → {item}"
        for key, item in sorted(value.items())
        if isinstance(key, str) and isinstance(item, str)
    )
    return f" · alias overrides: {rendered}" if rendered else ""


def _context_preview(context: LaunchExecutionContext) -> dict[str, Any]:
    vcs_workflow_type: str | None = None
    vcs_ref: str | None = None
    if context.vcs_ref is not None:
        vcs_workflow_type, vcs_ref = context.vcs_ref
    return {
        "cl_name": context.cl_name,
        "project_file": context.project_file,
        "project_name": context.project_name,
        "update_target": context.update_target,
        "history_sort_key": context.history_sort_key,
        "is_home_mode": context.is_home_mode,
        "vcs_workflow_type": vcs_workflow_type,
        "vcs_ref": vcs_ref,
        "deferred_workspace": context.deferred_workspace,
        "workspace_num": context.workspace_num,
        "workspace_dir": context.workspace_dir,
        "use_preallocated_workspace": context.use_preallocated_workspace,
    }


def _prompt_snippet(prompt: str, *, limit: int = 500) -> str:
    text = " ".join(prompt.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "LAUNCH_PREVIEW_FILE",
    "LAUNCH_PREVIEW_SCHEMA_VERSION",
    "LAUNCH_REQUEST_FILE",
    "LAUNCH_RESPONSE_FILE",
    "build_launch_preview_request",
    "write_launch_preview_files",
]
