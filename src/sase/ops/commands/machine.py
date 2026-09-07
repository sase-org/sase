"""Durable runner for ``sase machine agent`` remote lifecycle mutations."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from typing import Any

from sase.dispatch.config import load_dispatch_config
from sase.dispatch.federation import build_federation_facade
from sase.dispatch.mutations import (
    RemoteDispatchMutationError,
    RemoteMutationResult,
    submit_remote_mutations,
)
from sase.ops.cli import load_request
from sase.ops.commands.common import OperationCommandResult, run_and_finish
from sase.ops.names import MACHINE_AGENT_ACTION


def handle_machine_agent_command(args: argparse.Namespace) -> int:
    """Dispatch ``sase machine agent {fork,retry,stop}``."""
    return run_and_finish(
        operation=MACHINE_AGENT_ACTION,
        body=lambda: _run_machine_agent(args),
        args=args,
    )


def _run_machine_agent(args: argparse.Namespace) -> OperationCommandResult:
    kind = getattr(args, "machine_agent_subcommand", None)
    if kind not in {"fork", "retry", "stop"}:
        return OperationCommandResult(
            success=False,
            message="machine agent action is required",
            payload={"ok": False},
            exit_code=2,
        )
    request = load_request(MACHINE_AGENT_ACTION, args)
    payload = dict(request.payload) if request.payload else {}
    alias = str(getattr(args, "alias", "") or payload.get("alias") or "")
    fork_prompt = payload.get("fork_prompt") or getattr(args, "instruction", None)
    if kind == "fork" and not fork_prompt:
        return OperationCommandResult(
            success=False,
            message="fork instruction is required",
            payload={"ok": False, "kind": kind, "alias": alias},
            exit_code=2,
        )
    timeout = getattr(args, "timeout", None)
    follow = bool(payload.get("follow", True))
    snapshots = _sidecar_snapshots(payload, alias)
    if not snapshots:
        snapshots = _lookup_snapshots(alias, _agent_names(args, kind), timeout)
    try:
        results: list[RemoteMutationResult] = list(
            submit_remote_mutations(
                snapshots,
                kind=kind,
                fork_prompt=fork_prompt,
                kill_source_first=payload.get("kill_source_first"),
                follow=follow if kind in {"retry", "fork"} else False,
                reason=payload.get("reason"),
                timeout_seconds=timeout,
            )
        )
    except RemoteDispatchMutationError as exc:
        return OperationCommandResult(
            success=False,
            message=str(exc),
            payload={"ok": False, "kind": kind, "alias": alias},
            exit_code=1,
        )
    success = bool(results) and all(
        item.outcome in {"applied", "already_settled"} for item in results
    )
    message = "; ".join(item.message for item in results) or f"{kind} submitted"
    return OperationCommandResult(
        success=success,
        message=message,
        payload={
            "ok": success,
            "kind": kind,
            "alias": alias,
            "results": [
                {
                    "alias": item.alias,
                    "kind": item.kind,
                    "outcome": item.outcome,
                    "message": item.message,
                    "decision": item.decision,
                    "reason": item.reason,
                    "receipt": item.receipt,
                }
                for item in results
            ],
        },
        exit_code=0 if success else 1,
    )


def _agent_names(args: argparse.Namespace, kind: str) -> tuple[str, ...]:
    if kind == "fork":
        name = getattr(args, "agent", None)
        return (str(name),) if name else ()
    names = getattr(args, "agents", None) or ()
    return tuple(str(name) for name in names)


def _sidecar_snapshots(
    payload: Mapping[str, Any],
    alias: str,
) -> list[dict[str, Any]]:
    if isinstance(payload.get("targets"), list):
        return [dict(item) for item in payload["targets"] if isinstance(item, Mapping)]
    if isinstance(payload.get("exact_locator"), Mapping):
        snapshot = dict(payload)
        snapshot.setdefault("alias", alias)
        return [snapshot]
    return []


def _lookup_snapshots(
    alias: str,
    names: Sequence[str],
    timeout: float | None,
) -> list[dict[str, Any]]:
    config = load_dispatch_config()
    machine = config.machine_by_alias().get(alias)
    if machine is None:
        raise RemoteDispatchMutationError(
            f"dispatch target {alias!r} is not enrolled in dispatch.machines"
        )
    response = build_federation_facade().catalog_sync(
        {"schema_version": 1, "limit": 100, "query": names[0] if names else None},
        timeout_seconds=timeout or config.request_timeout_seconds,
    )
    snapshots: list[dict[str, Any]] = []
    wanted = set(names)
    for host in response.get("hosts") or ():
        if not isinstance(host, Mapping):
            continue
        payload = host.get("payload")
        rows = []
        if isinstance(payload, Mapping):
            page = payload.get("page")
            if isinstance(page, Mapping) and isinstance(page.get("rows"), list):
                rows = page["rows"]
            elif isinstance(payload.get("summaries"), list):
                rows = payload["summaries"]
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            locator = row.get("logical_locator")
            agent_id = None
            if isinstance(locator, Mapping):
                agent_id = locator.get("agent_id")
            agent_id = agent_id or row.get("agent_id")
            if wanted and str(agent_id) not in wanted:
                continue
            snapshots.append(
                {
                    "alias": alias,
                    "origin_installation_id": machine.pinned_installation_id,
                    "exact_locator": row.get("exact_locator"),
                    "row_revision": row.get("row_revision"),
                    "capabilities": row.get("capabilities") or {},
                }
            )
    if not snapshots:
        raise RemoteDispatchMutationError(
            f"no remote agent matching {', '.join(names)} on {alias}"
        )
    return snapshots


__all__ = ["handle_machine_agent_command"]
