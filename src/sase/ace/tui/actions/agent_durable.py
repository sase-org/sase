"""Shared durable submission helpers for ACE agent actions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sase.ace.tui.durable_ops import (
    agent_directive_concurrency_key,
    agent_tribe_concurrency_key,
    cleanup_concurrency_key,
    launch_concurrency_key,
    operation_fingerprint,
    sase_command_argv,
)
from sase.ops.names import (
    AGENT_CLEANUP,
    AGENT_PERSIST_DIRECTIVE,
    AGENT_REVERT,
    RUN_LAUNCH,
)

from .proc_actions import TrackedProcCompletion


def submit_agent_directive(
    app: Any,
    *,
    artifacts_dir: str,
    payload: Mapping[str, Any],
    cl_name: str,
    display_name: str,
    on_complete: Callable[[TrackedProcCompletion[Any]], None] | None = None,
    tribe_store: bool = False,
    duplicate_message: str = "A directive update is already running for this agent",
) -> bool:
    """Submit ``sase agent persist-directive`` through the durable adapter."""
    request_payload = dict(payload)
    request_payload.setdefault("artifacts_dir", artifacts_dir)
    key = (
        agent_tribe_concurrency_key()
        if tribe_store
        else agent_directive_concurrency_key(artifacts_dir)
    )
    submitted = app._submit_durable_proc(
        sase_command_argv("agent", "persist-directive", artifacts_dir),
        operation=AGENT_PERSIST_DIRECTIVE,
        request=request_payload,
        request_fingerprint=operation_fingerprint(
            AGENT_PERSIST_DIRECTIVE, request_payload
        ),
        concurrency_keys=(key,),
        proc_type="agent-directive",
        display_name=display_name,
        cl_name=cl_name,
        project_file=artifacts_dir,
        duplicate_message=duplicate_message,
        on_complete=on_complete,
        reload_on_complete=False,
        notify_on_complete=False,
    )
    return submitted is not None


def submit_agent_revert(
    app: Any,
    *,
    name: str,
    payload: Mapping[str, Any],
    cl_name: str,
    project_file: str,
    display_name: str,
    concurrency_key: str,
    on_complete: Callable[[TrackedProcCompletion[Any]], None] | None = None,
) -> bool:
    """Submit ``sase agent revert`` through the durable adapter."""
    submitted = app._submit_durable_proc(
        sase_command_argv("agent", "revert", name),
        operation=AGENT_REVERT,
        request=payload,
        request_fingerprint=operation_fingerprint(AGENT_REVERT, payload),
        concurrency_keys=(concurrency_key,),
        proc_type="revert_agent",
        display_name=display_name,
        cl_name=cl_name,
        project_file=project_file,
        on_complete=on_complete,
        reload_on_complete=False,
        notify_on_complete=True,
    )
    return submitted is not None


def submit_agent_launch(
    app: Any,
    *,
    prompt: str,
    workflow: str,
    cl_name: str,
    project_file: str,
    display_name: str,
    extra_payload: Mapping[str, Any] | None = None,
    on_complete: Callable[[TrackedProcCompletion[Any]], None] | None = None,
) -> Any:
    """Submit ``sase run`` through the durable adapter."""
    payload = {"prompt": prompt, "workflow": workflow, **dict(extra_payload or {})}
    return app._submit_durable_proc(
        sase_command_argv("run"),
        operation=RUN_LAUNCH,
        request=payload,
        request_fingerprint=operation_fingerprint(RUN_LAUNCH, payload),
        concurrency_keys=(launch_concurrency_key(workflow),),
        proc_type="launch",
        display_name=display_name,
        cl_name=cl_name,
        project_file=project_file,
        on_complete=on_complete,
        reload_on_complete=False,
        notify_on_complete=False,
    )


def submit_agent_cleanup(
    app: Any,
    *,
    proc_type: str,
    identity: str,
    payload: Mapping[str, Any],
    cl_name: str,
    project_file: str,
    display_name: str,
    on_complete: Callable[[TrackedProcCompletion[Any]], None] | None = None,
    live_body: Callable[..., Any] | None = None,
    on_settled: Callable[[], None] | None = None,
) -> bool:
    """Submit ``sase agent persist-cleanup`` through the durable adapter."""
    request_payload = dict(payload)
    request_payload.setdefault("action", proc_type)
    submitted = app._submit_durable_proc(
        sase_command_argv("agent", "persist-cleanup"),
        operation=AGENT_CLEANUP,
        request=request_payload,
        request_fingerprint=operation_fingerprint(AGENT_CLEANUP, request_payload),
        concurrency_keys=(cleanup_concurrency_key(proc_type, identity),),
        proc_type=proc_type,
        display_name=display_name,
        cl_name=cl_name,
        project_file=project_file,
        on_complete=on_complete,
        reload_on_complete=False,
        notify_on_complete=False,
        live_body=live_body,
        on_settled=on_settled,
    )
    return submitted is not None


__all__ = [
    "submit_agent_cleanup",
    "submit_agent_directive",
    "submit_agent_launch",
    "submit_agent_revert",
]
