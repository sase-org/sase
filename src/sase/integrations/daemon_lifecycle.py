"""Python lifecycle glue for the local SASE daemon."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import Any

from sase.integrations import _daemon_lifecycle_actions as _actions
from sase.integrations import _daemon_lifecycle_inspection as _inspection
from sase.integrations import _daemon_lifecycle_process as _process
from sase.integrations import _daemon_lifecycle_types as _types
from sase.integrations import _daemon_lifecycle_values as _values
from sase.integrations._daemon_lifecycle_actions import (
    run_daemon_diff,
    run_daemon_rebuild,
    run_daemon_start,
    run_daemon_stop,
    run_daemon_verify,
    wait_for_background_start,
)
from sase.integrations._daemon_lifecycle_config import (
    host_identity_from_env,
    load_daemon_config,
    prepare_daemon_launch,
    resolve_gateway_command,
    runtime_paths_from_args,
)
from sase.integrations._daemon_lifecycle_diagnostics import (
    doctor_payload,
    inspection_to_dict,
    print_status,
)
from sase.integrations._daemon_lifecycle_inspection import (
    read_metadata,
    try_health_rpc,
)

DEFAULT_STARTUP_TIMEOUT_SECONDS = _types.DEFAULT_STARTUP_TIMEOUT_SECONDS
DEFAULT_STOP_TIMEOUT_SECONDS = _types.DEFAULT_STOP_TIMEOUT_SECONDS
LOCK_METADATA_FILENAME = _types.LOCK_METADATA_FILENAME
LOCK_SCHEMA_VERSION = _types.LOCK_SCHEMA_VERSION
SOCKET_FILENAME = _types.SOCKET_FILENAME
KillFn = _types.KillFn
PopenFactory = _types.PopenFactory
SleepFn = _types.SleepFn
_DaemonInspection = _types.DaemonInspection
_DaemonLaunch = _types.DaemonLaunch
_DaemonLifecycleConfig = _types.DaemonLifecycleConfig
_DaemonLifecycleError = _types.DaemonLifecycleError
_DaemonRuntimePaths = _types.DaemonRuntimePaths
_command_value = _values.command_value
_int_value = _values.int_value
_optional_path = _values.optional_path
_positive_float = _values.positive_float

__all__ = [
    "DEFAULT_STARTUP_TIMEOUT_SECONDS",
    "DEFAULT_STOP_TIMEOUT_SECONDS",
    "LOCK_METADATA_FILENAME",
    "LOCK_SCHEMA_VERSION",
    "SOCKET_FILENAME",
    "KillFn",
    "PopenFactory",
    "SleepFn",
    "_DaemonInspection",
    "_DaemonLaunch",
    "_DaemonLifecycleConfig",
    "_DaemonLifecycleError",
    "_DaemonRuntimePaths",
    "_command_value",
    "_doctor_payload",
    "_executable_matches_metadata",
    "_host_identity_from_env",
    "_inspect_daemon",
    "_inspection_to_dict",
    "_int_value",
    "_load_daemon_config",
    "_optional_path",
    "_positive_float",
    "_prepare_daemon_launch",
    "_print_status",
    "_process_is_live",
    "_read_metadata",
    "_resolve_gateway_command",
    "_run_daemon_diff",
    "_run_daemon_rebuild",
    "_run_daemon_start",
    "_run_daemon_stop",
    "_run_daemon_verify",
    "_runtime_paths_from_args",
    "_terminate_process",
    "_try_health_rpc",
    "_wait_for_background_start",
    "handle_daemon_diff",
    "handle_daemon_doctor",
    "handle_daemon_rebuild",
    "handle_daemon_start",
    "handle_daemon_status",
    "handle_daemon_stop",
    "handle_daemon_verify",
    "signal",
]


def handle_daemon_start(args: argparse.Namespace) -> int:
    """CLI wrapper for ``sase daemon start``."""
    try:
        return _run_daemon_start(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def handle_daemon_status(args: argparse.Namespace) -> int:
    """CLI wrapper for ``sase daemon status``."""
    inspection = _inspect_daemon(args)
    if getattr(args, "json_output", False):
        print(json.dumps(_inspection_to_dict(inspection), indent=2, sort_keys=True))
    else:
        _print_status(inspection)
    return 0


def handle_daemon_stop(args: argparse.Namespace) -> int:
    """CLI wrapper for ``sase daemon stop``."""
    try:
        return _run_daemon_stop(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def handle_daemon_doctor(args: argparse.Namespace) -> int:
    """Run daemon lifecycle and projection diagnostics."""
    inspection = _inspect_daemon(args)
    payload = _doctor_payload(inspection)
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_status(inspection)
        print(f"Doctor: {payload['doctor']['state']}")
        for check in payload["doctor"]["checks"]:
            print(f"- {check['name']}: {check['state']} - {check['message']}")
    return 0


def handle_daemon_rebuild(args: argparse.Namespace) -> int:
    """Rebuild daemon projections through a live daemon or one-shot Rust path."""
    try:
        payload = _run_daemon_rebuild(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        mode = payload.get("mode", "projection_storage_rebuild")
        limitation = payload.get("limitation")
        source = payload.get("source")
        print(f"Rebuild: {mode} completed via {source}.")
        if limitation:
            print(f"Limitation: {limitation}")
    return 0


def handle_daemon_verify(args: argparse.Namespace) -> int:
    """Verify daemon shadow projections through a live daemon."""
    try:
        payload = _run_daemon_verify(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        state = "ok" if payload.get("ok") else "degraded"
        print(f"Verify: {state}")
        for summary in payload.get("summaries", []):
            if isinstance(summary, dict):
                counts = summary.get("diff_counts", {})
                print(
                    "- {surface}: {state} "
                    "missing={missing} stale={stale} extra={extra} corrupt={corrupt}".format(
                        surface=summary.get("surface", "unknown"),
                        state=summary.get("state", "unknown"),
                        missing=counts.get("missing", 0)
                        if isinstance(counts, dict)
                        else 0,
                        stale=counts.get("stale", 0) if isinstance(counts, dict) else 0,
                        extra=counts.get("extra", 0) if isinstance(counts, dict) else 0,
                        corrupt=counts.get("corrupt", 0)
                        if isinstance(counts, dict)
                        else 0,
                    )
                )
    return 0 if payload.get("ok") else 1


def handle_daemon_diff(args: argparse.Namespace) -> int:
    """Print bounded daemon shadow projection diffs."""
    try:
        payload = _run_daemon_diff(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Diff: {payload.get('surface', 'all')}")
        for record in payload.get("records", []):
            if isinstance(record, dict):
                print(
                    "- {category} {domain} {handle}: {message}".format(
                        category=record.get("category", "unknown"),
                        domain=record.get("domain", "unknown"),
                        handle=record.get("handle") or record.get("source_path") or "",
                        message=record.get("message", ""),
                    )
                )
        if payload.get("next_cursor"):
            print(f"Next cursor: {payload['next_cursor']}")
    counts = payload.get("counts")
    has_diff = (
        isinstance(counts, dict)
        and sum(
            int(counts.get(key, 0)) for key in ("missing", "stale", "extra", "corrupt")
        )
        > 0
    )
    return 1 if has_diff else 0


def _load_daemon_config() -> _DaemonLifecycleConfig:
    return load_daemon_config()


def _prepare_daemon_launch(
    args: argparse.Namespace,
    *,
    config: _DaemonLifecycleConfig | None = None,
) -> _DaemonLaunch:
    if config is None:
        config = _load_daemon_config()
    return prepare_daemon_launch(
        args,
        config=config,
        gateway_command_resolver=_resolve_gateway_command,
    )


def _runtime_paths_from_args(
    args: argparse.Namespace,
    *,
    config: _DaemonLifecycleConfig | None = None,
) -> _DaemonRuntimePaths:
    if config is None:
        config = _load_daemon_config()
    return runtime_paths_from_args(args, config=config)


def _host_identity_from_env() -> str:
    return host_identity_from_env()


def _resolve_gateway_command() -> tuple[str, ...]:
    return resolve_gateway_command()


def _inspect_daemon(args: argparse.Namespace) -> _DaemonInspection:
    return _inspection.inspect_daemon(
        args,
        runtime_paths_from_args=_runtime_paths_from_args,
        host_identity_from_env=_host_identity_from_env,
        process_is_live=_process_is_live,
        metadata_reader=_read_metadata,
        health_rpc=_try_health_rpc,
    )


def _read_metadata(path: Path) -> dict[str, Any] | str | None:
    return read_metadata(path)


def _try_health_rpc(socket_path: Path) -> dict[str, Any]:
    return try_health_rpc(socket_path)


def _run_daemon_start(
    args: argparse.Namespace,
    *,
    popen: PopenFactory = _actions.subprocess.Popen,
    sleep: SleepFn = time.sleep,
) -> int:
    return run_daemon_start(
        args,
        popen=popen,
        sleep=sleep,
        prepare_daemon_launch=_prepare_daemon_launch,
        background_start_waiter=_wait_for_background_start,
        terminate_process=_terminate_process,
    )


def _run_daemon_stop(
    args: argparse.Namespace,
    *,
    kill: KillFn = _actions.os.kill,
    sleep: SleepFn = time.sleep,
) -> int:
    return run_daemon_stop(
        args,
        kill=kill,
        sleep=sleep,
        inspect_daemon=_inspect_daemon,
        process_is_live=_process_is_live,
        executable_matches_metadata=_executable_matches_metadata,
    )


def _run_daemon_rebuild(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_rebuild(
        args,
        inspect_daemon=_inspect_daemon,
        prepare_daemon_launch=_prepare_daemon_launch,
    )


def _run_daemon_verify(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_verify(args, inspect_daemon=_inspect_daemon)


def _run_daemon_diff(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_diff(args, inspect_daemon=_inspect_daemon)


def _wait_for_background_start(
    launch: _DaemonLaunch,
    proc: _actions.subprocess.Popen[Any],
    sleep: SleepFn,
) -> _DaemonInspection:
    return wait_for_background_start(
        launch,
        proc,
        sleep,
        inspect_daemon=_inspect_daemon,
    )


def _terminate_process(proc: _actions.subprocess.Popen[Any]) -> None:
    return _process.terminate_process(proc)


def _process_is_live(pid: int) -> bool:
    return _process.process_is_live(pid)


def _executable_matches_metadata(pid: int, metadata: dict[str, Any]) -> bool:
    return _process.executable_matches_metadata(pid, metadata)


def _print_status(inspection: _DaemonInspection) -> None:
    return print_status(inspection)


def _inspection_to_dict(inspection: _DaemonInspection) -> dict[str, Any]:
    return inspection_to_dict(inspection)


def _doctor_payload(inspection: _DaemonInspection) -> dict[str, Any]:
    return doctor_payload(inspection)
