"""Asynchronous hijack recovery preview loading and choice updates."""

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from ...modals.agent_action_chooser_modal import (
    AgentActionChoice,
    AgentActionChooserModal,
)
from rich.text import Text

from ._hijack_recovery_formatting import RESULT_PREFIX, int_value, text_value

_PREVIEW_CACHE_MAX = 64
_preview_lock = threading.Lock()
_preview_cache: OrderedDict[tuple[str, int], Any] = OrderedDict()


def schedule_preview(
    app: Any,
    modal: AgentActionChooserModal,
    record: Mapping[str, Any],
) -> None:
    async def _load() -> None:
        try:
            preview = await asyncio.to_thread(_cached_preview_for_record, dict(record))
            error: str | None = None
        except Exception as exc:  # noqa: BLE001 - preview refusal is a disabled-row reason.
            preview = None
            error = str(exc) or "Could not compute recovery preview"
        if not modal.is_mounted:
            return
        if preview is None:
            choices = tuple(
                AgentActionChoice(
                    **{
                        **choice.__dict__,
                        "pending": False,
                        "disabled_reason": error,
                        "detail": None,
                    }
                )
                if choice.pending
                else choice
                for choice in modal.choices
            )
            modal.update_choices(choices, primary_result="")
            return
        choices = _apply_preview(modal.choices, preview)
        primary = None
        for action_name in ("escalate", "continue"):
            action = preview.action(action_name)
            if preview.state == "held" and action is not None and action.available:
                primary = f"{RESULT_PREFIX}{action_name}"
                break
        if primary is None:
            primary = ""
        selected = None
        if modal.choices and modal.selected_index == 0:
            selected = primary
        modal.update_choices(
            choices,
            primary_result=primary,
            selected_result=selected,
        )
        modal.update_header(_preview_header(preview.header, record))

    from ...util.pump_tasks import spawn_pump_free_task

    task = spawn_pump_free_task(
        app,
        _load(),
        name="sase-hijack-recovery-preview",
        registry_attr="_agent_enter_async_tasks",
    )
    if task is None:
        modal.update_choices(
            tuple(
                AgentActionChoice(
                    **{
                        **choice.__dict__,
                        "pending": False,
                        "disabled_reason": "Recovery preview is unavailable",
                        "detail": None,
                    }
                )
                if choice.pending
                else choice
                for choice in modal.choices
            ),
            primary_result="",
        )


def _cached_preview_for_record(record: dict[str, Any]) -> Any:
    from sase.agent.hijack.preview import hijack_recovery_preview

    hijack_id = str(record.get("hijack_id") or "")
    revision = int_value(record.get("revision"))
    key = (hijack_id, revision)
    with _preview_lock:
        cached = _preview_cache.get(key)
        if cached is not None:
            _preview_cache.move_to_end(key)
            return cached
    preview = hijack_recovery_preview(record)
    with _preview_lock:
        _preview_cache[key] = preview
        _preview_cache.move_to_end(key)
        while len(_preview_cache) > _PREVIEW_CACHE_MAX:
            _preview_cache.popitem(last=False)
    return preview


def _apply_preview(
    choices: tuple[AgentActionChoice, ...], preview: Any
) -> tuple[AgentActionChoice, ...]:
    action_names = {
        "escalate": "escalate",
        "continue": "continue",
        "restart": "restart",
        "edit": "edit",
    }
    updated: list[AgentActionChoice] = []
    for choice in choices:
        action_name = next(
            (
                name
                for suffix, name in action_names.items()
                if choice.result == f"{RESULT_PREFIX}{suffix}"
            ),
            None,
        )
        if action_name is None:
            updated.append(choice)
            continue
        action = preview.action(action_name)
        if action is None:
            updated.append(
                AgentActionChoice(
                    **{
                        **choice.__dict__,
                        "pending": False,
                        "disabled_reason": "not available",
                        "detail": None,
                    }
                )
            )
            continue
        detail = text_value(action.detail)
        target = text_value(action.target)
        if target and target not in detail:
            detail = f"{detail} · {target}" if detail else target
        glyph = (
            "↔"
            if action_name == "escalate" and "switch" in action.label.lower()
            else choice.glyph
        )
        updated.append(
            AgentActionChoice(
                **{
                    **choice.__dict__,
                    "label": action.label or choice.label,
                    "detail": detail or None,
                    "glyph": glyph,
                    "action_target": target or None,
                    "pending": False,
                    "disabled_reason": None
                    if action.available
                    else (action.reason or "unavailable"),
                }
            )
        )
    return tuple(updated)


def _preview_header(
    header: Mapping[str, Any], record: Mapping[str, Any] | None = None
) -> Text:
    model = text_value(header.get("model_display")) or "unknown model"
    parts = [model]
    alias = text_value((record or {}).get("model_alias"))
    if alias:
        try:
            from sase.agent.hijack.core import normalize_hijack_rung

            alias = normalize_hijack_rung(alias)
        except Exception:
            pass
        parts.append(f"via {alias}")
    run_duration = text_value(header.get("run_duration_display"))
    age = text_value(header.get("hijacked_ago"))
    if run_duration:
        parts.append(f"ran {run_duration}")
    if age:
        parts.append(f"hijacked {age}")
    result = Text(" · ".join(parts) + "\n")
    files = int_value(header.get("files_changed"))
    insertions = int_value(header.get("insertions"))
    deletions = int_value(header.get("deletions"))
    details = []
    if files:
        details.append(f"{files} files +{insertions} −{deletions}")
    tool = text_value(header.get("last_tool"))
    tool_age = text_value(header.get("last_tool_age"))
    if tool:
        details.append(f"last tool: {tool}" + (f" ({tool_age})" if tool_age else ""))
    result.append(" · ".join(details) or "Recovery snapshot is held", style="dim")
    return result


__all__ = ["schedule_preview"]
