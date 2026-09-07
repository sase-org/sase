"""Durable runner for ``sase machine attention`` remote question/gate answers."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from sase.dispatch.attention import (
    RemoteAttentionResult,
    RemoteDispatchAttentionError,
    fetch_remote_attention,
    submit_remote_attention_answer,
)
from sase.dispatch.config import load_dispatch_config, require_remote_dispatch_enabled
from sase.dispatch.federation import build_federation_facade
from sase.ops.cli import load_request
from sase.ops.commands.common import OperationCommandResult, run_and_finish
from sase.ops.names import MACHINE_ATTENTION_ACTION


def handle_machine_attention_command(args: argparse.Namespace) -> int:
    """Dispatch ``sase machine attention {answer,approve}``."""
    return run_and_finish(
        operation=MACHINE_ATTENTION_ACTION,
        body=lambda: _run_machine_attention(args),
        args=args,
    )


def _run_machine_attention(args: argparse.Namespace) -> OperationCommandResult:
    require_remote_dispatch_enabled()
    kind = getattr(args, "machine_attention_subcommand", None)
    if kind not in {"answer", "approve"}:
        return OperationCommandResult(
            success=False,
            message="machine attention action is required",
            payload={"ok": False},
            exit_code=2,
        )
    request = load_request(MACHINE_ATTENTION_ACTION, args)
    payload = dict(request.payload) if request.payload else {}
    alias = str(getattr(args, "alias", "") or payload.get("alias") or "")
    request_id = str(getattr(args, "request", "") or payload.get("request_id") or "")
    timeout = getattr(args, "timeout", None)

    try:
        intent = _sidecar_intent(payload)
        if intent is None:
            intent = _resolve_current_intent(
                alias=alias,
                request_id=request_id,
                kind=kind,
                args=args,
                timeout=timeout,
            )
        operation_id = payload.get("operation_id")
        result: RemoteAttentionResult = submit_remote_attention_answer(
            alias,
            intent,
            operation_id=operation_id if isinstance(operation_id, str) else None,
            timeout_seconds=timeout,
        )
    except RemoteDispatchAttentionError as exc:
        return OperationCommandResult(
            success=False,
            message=str(exc),
            payload={"ok": False, "kind": kind, "alias": alias},
            exit_code=1,
        )
    success = result.outcome in {"applied", "already_settled"}
    return OperationCommandResult(
        success=success,
        message=result.message,
        payload={
            "ok": success,
            "kind": kind,
            "alias": alias,
            "outcome": result.outcome,
            "message": result.message,
            "decision": result.decision,
            "reason": result.reason,
            "receipt": result.receipt,
            "settled_response": result.settled_response,
        },
        exit_code=0 if success else 1,
    )


def _sidecar_intent(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    intent = payload.get("intent")
    if isinstance(intent, Mapping) and isinstance(intent.get("request_key"), Mapping):
        return dict(intent)
    return None


def _resolve_current_intent(
    *,
    alias: str,
    request_id: str,
    kind: str,
    args: argparse.Namespace,
    timeout: float | None,
) -> dict[str, Any]:
    if not alias:
        raise RemoteDispatchAttentionError("a machine alias is required")
    if not request_id:
        raise RemoteDispatchAttentionError("an attention request identity is required")
    config = load_dispatch_config()
    machine = config.machine_by_alias().get(alias)
    if machine is None:
        raise RemoteDispatchAttentionError(
            f"dispatch target {alias!r} is not enrolled in dispatch.machines"
        )
    catalog = build_federation_facade().catalog_sync(
        {"schema_version": 1, "limit": 100},
        timeout_seconds=timeout or config.request_timeout_seconds,
    )
    logical_keys = _logical_keys_for_host(catalog, alias)
    attention = fetch_remote_attention(logical_keys, timeout_seconds=timeout)
    entry = _find_entry(attention, alias, request_id)
    if entry is None:
        raise RemoteDispatchAttentionError(
            f"no pending attention request {request_id!r} found on {alias!r}"
        )
    return _intent_from_entry(entry, kind, args)


def _intent_from_entry(
    entry: Mapping[str, Any],
    kind: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    entry_kind = entry.get("kind")
    if kind == "approve" and entry_kind != "gate":
        raise RemoteDispatchAttentionError("attention request is not a gate")
    if kind == "answer" and entry_kind != "question":
        raise RemoteDispatchAttentionError("attention request is not a question")
    request_key = entry.get("request_key")
    if not isinstance(request_key, Mapping):
        raise RemoteDispatchAttentionError("attention entry is missing request_key")
    intent: dict[str, Any] = {
        "kind": entry_kind,
        "request_key": dict(request_key),
        "observed_revision": entry.get("revision"),
        "selected_option_ids": [],
        "feedback": None,
        "question_choice": None,
        "question_index": None,
        "selected_option_id": None,
        "selected_option_label": None,
        "selected_option_index": None,
        "custom_answer": None,
        "global_note": None,
    }
    if kind == "approve":
        options = [str(value) for value in getattr(args, "options", None) or ()]
        if not options:
            raise RemoteDispatchAttentionError(
                "at least one option is required to approve a gate"
            )
        intent["selected_option_ids"] = options
        intent["feedback"] = getattr(args, "feedback", None)
    else:
        answer = getattr(args, "answer", None)
        if not answer:
            raise RemoteDispatchAttentionError("an answer is required")
        intent["question_choice"] = "custom"
        intent["custom_answer"] = str(answer)
    return intent


def _logical_keys_for_host(catalog: Mapping[str, Any], alias: str) -> list[str]:
    keys: list[str] = []
    for host in catalog.get("hosts") or ():
        if not isinstance(host, Mapping) or host.get("alias") != alias:
            continue
        payload = host.get("payload")
        rows: list[Any] = []
        if isinstance(payload, Mapping):
            page = payload.get("page")
            if isinstance(page, Mapping) and isinstance(page.get("rows"), list):
                rows = page["rows"]
        for row in rows:
            if isinstance(row, Mapping) and isinstance(row.get("logical_key"), str):
                keys.append(row["logical_key"])
    return keys


def _find_entry(
    attention: Mapping[str, Any],
    alias: str,
    request_id: str,
) -> dict[str, Any] | None:
    for host in attention.get("hosts") or ():
        if not isinstance(host, Mapping) or host.get("alias") != alias:
            continue
        payload = host.get("payload")
        if not isinstance(payload, Mapping):
            continue
        for entry in payload.get("entries") or ():
            if not isinstance(entry, Mapping):
                continue
            request_key = entry.get("request_key")
            if (
                isinstance(request_key, Mapping)
                and request_key.get("request_id") == request_id
            ):
                return dict(entry)
    return None


__all__ = ["handle_machine_attention_command"]
