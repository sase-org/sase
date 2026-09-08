"""Handler for the ``sase usage`` command group."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TextIO

from sase.llm_provider.usage.config import get_usage_metrics_settings
from sase.llm_provider.usage.presentation import (
    render_refresh_receipt_plain,
    render_usage_plain,
    render_usage_rich,
    usage_snapshot_json_payload,
)
from sase.llm_provider.usage.refresh import (
    USAGE_REFRESH_BATCH_DEADLINE_SECONDS,
    USAGE_REFRESH_OPERATION,
    UsageRefreshReceipt,
    submit_usage_refresh,
)
from sase.llm_provider.usage.store import (
    ProviderUsageStateError,
    ProviderUsageStoreRead,
    load_provider_usage,
)
from sase.ops import OperationIOError, read_operation_result

_USAGE_CLI_SCHEMA_VERSION = 1
_REFRESH_ERROR_OUTCOMES = frozenset({"error", "unauthenticated"})


@dataclass(frozen=True)
class _UsageOperationResult:
    """One waited usage-refresh operation result."""

    proc_id: str
    success: bool
    message: str
    error: str | None
    payload: Mapping[str, Any]
    proc_status: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "error": self.error,
            "message": self.message,
            "payload": dict(self.payload),
            "proc_id": self.proc_id,
            "proc_status": self.proc_status,
            "success": self.success,
        }


def handle_usage_command(args: argparse.Namespace) -> int:
    """Dispatch the ``sase usage`` subcommands."""
    if getattr(args, "json", False) and getattr(args, "plain", False):
        print("sase usage: --json and --plain cannot be combined", file=sys.stderr)
        return 2

    providers = _requested_providers(args)
    known = _registered_provider_names()
    unknown = [name for name in providers if name not in known]
    if unknown:
        choices = ", ".join(known) if known else "none"
        print(
            f"sase usage: unknown provider {unknown[0]!r} (choose from: {choices})",
            file=sys.stderr,
        )
        return 2

    subcommand = getattr(args, "usage_subcommand", "list")
    if subcommand == "list":
        return _handle_usage_list(args, providers)
    if subcommand == "refresh":
        return _handle_usage_refresh(args, providers)
    print(f"sase usage: unknown subcommand {subcommand!r}", file=sys.stderr)
    return 2


def _handle_usage_list(args: argparse.Namespace, providers: tuple[str, ...]) -> int:
    try:
        read = _load_provider_usage_read()
    except (
        ProviderUsageStateError,
        OSError,
        RuntimeError,
        AttributeError,
        ImportError,
    ) as exc:
        _emit_usage_error(
            "usage_store_unreadable",
            str(exc),
            json_output=bool(getattr(args, "json", False)),
        )
        return 1
    _emit_usage_snapshot(read, args, providers)
    return 0


def _handle_usage_refresh(args: argparse.Namespace, providers: tuple[str, ...]) -> int:
    try:
        receipt = submit_usage_refresh(providers or None, explicit=True, origin="cli")
    except Exception as exc:
        _emit_usage_error(
            "usage_refresh_submit_failed",
            str(exc),
            json_output=bool(getattr(args, "json", False)),
        )
        return 1

    if getattr(args, "background", False):
        _emit_background_receipt(receipt, args)
        return 1 if _receipt_failed(receipt) else 0

    if not getattr(args, "json", False):
        print(render_refresh_receipt_plain(receipt), file=sys.stderr)
    operation_results = _wait_for_operation_ids(
        receipt.operation_ids,
        stream=sys.stderr,
    )
    try:
        read = _load_provider_usage_read()
    except (
        ProviderUsageStateError,
        OSError,
        RuntimeError,
        AttributeError,
        ImportError,
    ) as exc:
        _emit_usage_error(
            "usage_store_unreadable",
            str(exc),
            json_output=bool(getattr(args, "json", False)),
        )
        return 1

    if getattr(args, "json", False):
        payload = usage_snapshot_json_payload(
            read.snapshot,
            read.diagnostics,
            requested_providers=providers,
        )
        payload["refresh_receipt"] = receipt.to_json()
        payload["operation_results"] = [item.to_json() for item in operation_results]
        print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    else:
        _emit_usage_snapshot(read, args, providers)
    return 1 if _refresh_failed(receipt, operation_results) else 0


def _load_provider_usage_read() -> ProviderUsageStoreRead:
    settings = get_usage_metrics_settings()
    return load_provider_usage(
        cadence_seconds=settings.refresh_seconds,
        warn_percent=settings.warn_percent,
        critical_percent=settings.critical_percent,
    )


def _emit_usage_snapshot(
    read: ProviderUsageStoreRead,
    args: argparse.Namespace,
    providers: tuple[str, ...],
) -> None:
    if getattr(args, "json", False):
        payload = usage_snapshot_json_payload(
            read.snapshot,
            read.diagnostics,
            requested_providers=providers,
        )
        print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        return
    if _plain_output(args):
        print(
            render_usage_plain(
                read.snapshot,
                read.diagnostics,
                requested_providers=providers,
                verbose=bool(getattr(args, "verbose", False)),
            )
        )
        return
    from rich.console import Console

    console = Console()
    console.print(
        render_usage_rich(
            read.snapshot,
            read.diagnostics,
            requested_providers=providers,
            verbose=bool(getattr(args, "verbose", False)),
        )
    )


def _emit_background_receipt(
    receipt: UsageRefreshReceipt,
    args: argparse.Namespace,
) -> None:
    if getattr(args, "json", False):
        print(
            json.dumps(receipt.to_json(), ensure_ascii=True, indent=2, sort_keys=True)
        )
        return
    print(render_refresh_receipt_plain(receipt))


def _wait_for_operation_ids(
    operation_ids: Sequence[str],
    *,
    stream: TextIO,
) -> tuple[_UsageOperationResult, ...]:
    if not operation_ids:
        return ()
    from sase.procs import ProcControlError, short_proc_id, wait_for_proc
    from sase.procs.runtime import proc_operation_result_path

    results: list[_UsageOperationResult] = []
    timeout = USAGE_REFRESH_BATCH_DEADLINE_SECONDS + 20.0
    for proc_id in operation_ids:
        short_id = short_proc_id(proc_id)
        print(f"Waiting for usage refresh {short_id}...", file=stream)

        def _line(line: str, *, prefix: str = short_id) -> None:
            if line:
                print(f"[{prefix}] {line}", file=stream)

        try:
            proc = wait_for_proc(proc_id, timeout=timeout, on_line=_line)
        except (ProcControlError, TimeoutError) as exc:
            message = str(exc)
            print(f"Usage refresh {short_id} failed: {message}", file=stream)
            results.append(
                _UsageOperationResult(
                    proc_id=proc_id,
                    success=False,
                    message=message,
                    error=message,
                    payload={},
                )
            )
            continue
        try:
            result = read_operation_result(
                proc_operation_result_path(proc_id),
                expected_operation=USAGE_REFRESH_OPERATION,
                expected_proc_id=proc_id,
            )
        except OperationIOError as exc:
            message = str(exc)
            print(f"Usage refresh {short_id} failed: {message}", file=stream)
            results.append(
                _UsageOperationResult(
                    proc_id=proc_id,
                    success=False,
                    message=message,
                    error=message,
                    payload={},
                    proc_status=proc.status,
                )
            )
            continue
        status = "completed" if result.success else "failed"
        print(f"Usage refresh {short_id} {status}: {result.message}", file=stream)
        results.append(
            _UsageOperationResult(
                proc_id=proc_id,
                success=result.success,
                message=result.message,
                error=result.error,
                payload={} if result.payload is None else dict(result.payload),
                proc_status=proc.status,
            )
        )
    return tuple(results)


def _refresh_failed(
    receipt: UsageRefreshReceipt,
    operation_results: Sequence[_UsageOperationResult],
) -> bool:
    if _receipt_failed(receipt):
        return True
    for result in operation_results:
        if not result.success:
            return True
        raw_providers = result.payload.get("providers")
        if not isinstance(raw_providers, list):
            continue
        for item in raw_providers:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("outcome") or "") in _REFRESH_ERROR_OUTCOMES:
                return True
    return False


def _receipt_failed(receipt: UsageRefreshReceipt) -> bool:
    return any(item.status == "error" for item in receipt.providers)


def _emit_usage_error(code: str, message: str, *, json_output: bool) -> None:
    if json_output:
        payload = {
            "error": {"code": code, "message": message},
            "schema_version": _USAGE_CLI_SCHEMA_VERSION,
        }
        print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        return
    print(f"sase usage: {message}", file=sys.stderr)


def _plain_output(args: argparse.Namespace) -> bool:
    if getattr(args, "plain", False):
        return True
    if os.environ.get("NO_COLOR") is not None:
        return True
    if os.environ.get("TERM") == "dumb":
        return True
    return not sys.stdout.isatty()


def _requested_providers(args: argparse.Namespace) -> tuple[str, ...]:
    values = getattr(args, "provider", None) or ()
    return tuple(
        dict.fromkeys(str(item).strip() for item in values if str(item).strip())
    )


def _registered_provider_names() -> tuple[str, ...]:
    from sase.llm_provider.registry import registered_provider_names

    return tuple(registered_provider_names())


__all__ = ["handle_usage_command"]
