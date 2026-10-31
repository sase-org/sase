"""Bind staged prepared-completion reservations before launch."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ._start_stage_shared import command_argv, optional_str
from .models import MonitorError
from .start_launch import MonitorLaunchContext


def bind_staged_prepared_completion(
    context: MonitorLaunchContext,
    payload: dict[str, Any],
) -> MonitorLaunchContext:
    """Bind the reserved prepared intent immediately before process launch."""

    request = context.request
    resources = payload.get("resources")
    resources = resources if isinstance(resources, dict) else {}
    intent_ref = optional_str(resources.get("prepared_intent_ref"))
    reservation = resources.get("prepared_reservation")
    if request.completion_ref is None and intent_ref is None and reservation is None:
        return context
    if (
        request.completion_ref is None
        or intent_ref != request.completion_ref
        or not isinstance(reservation, dict)
        or context.staged_id is None
        or context.starter_artifacts_dir is None
    ):
        raise MonitorError("staged prepared completion reservation is incomplete")
    command_parts, _execution_parts = command_argv(request)
    expected = {
        "staged_id": context.staged_id,
        "monitor_id": context.monitor_id,
        "request_fingerprint": context.request_fingerprint,
        "command": command_parts,
    }
    if reservation != expected:
        raise MonitorError(
            "staged prepared completion reservation does not match the frozen request"
        )
    from sase.finalizers.prepare import bind_prepared_completion
    from sase.finalizers.declaration import FinalizerDeclarationError

    try:
        bind_prepared_completion(
            request.completion_ref,
            monitor_id=context.monitor_id,
            command=command_parts,
            request_fingerprint=context.request_fingerprint,
            staged_id=context.staged_id,
            artifacts_dir=context.starter_artifacts_dir,
        )
    except FinalizerDeclarationError as exc:
        _retain_or_restore_prepared_binding(context, reservation, command_parts, exc)
    return replace(context, bound_completion_ref=request.completion_ref)


def _retain_or_restore_prepared_binding(
    context: MonitorLaunchContext,
    reservation: dict[str, Any],
    command_parts: list[str],
    bind_error: Exception,
) -> None:
    """Retain or reacquire the prepared binding after a failed bind.

    A crash after binding but before proc submit leaves the intent
    bound to this monitor: retaining it preserves the prepared
    evidence. A held cleanup rolls the intent back and releases the
    reservation: re-reserving the identical frozen reservation restores
    it for the retry. Anything else (a stolen intent, a consumed
    intent, a mismatched binding) is a precise refusal.
    """
    from sase.finalizers._prepare_reservations import reserve_prepared_intent
    from sase.finalizers.declaration import FinalizerDeclarationError
    from sase.finalizers.prepare import (
        bind_prepared_completion,
        load_prepared_completion,
    )

    starter = context.starter_artifacts_dir
    assert starter is not None
    try:
        intent = load_prepared_completion(
            str(context.request.completion_ref), artifacts_dir=starter
        )
    except FinalizerDeclarationError as exc:
        raise MonitorError(str(exc)) from exc
    binding = intent.get("binding")
    binding = binding if isinstance(binding, dict) else {}
    if (
        str(intent.get("status") or "") == "bound"
        and str(binding.get("monitor_id") or "") == context.monitor_id
        and str(binding.get("request_fingerprint") or "") == context.request_fingerprint
        and list(binding.get("bound_command") or []) == command_parts
    ):
        return
    if str(intent.get("status") or "") != "prepared":
        raise MonitorError(str(bind_error)) from bind_error
    try:
        reserve_prepared_intent(
            str(context.request.completion_ref),
            dict(reservation),
            artifacts_dir=starter,
        )
        bind_prepared_completion(
            str(context.request.completion_ref),
            monitor_id=context.monitor_id,
            command=command_parts,
            request_fingerprint=context.request_fingerprint,
            staged_id=context.staged_id,
            artifacts_dir=starter,
        )
    except FinalizerDeclarationError as exc:
        raise MonitorError(str(exc)) from exc
