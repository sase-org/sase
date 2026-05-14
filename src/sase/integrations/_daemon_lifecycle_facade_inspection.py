"""Inspection, process, and diagnostic wrappers for the lifecycle facade."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

from sase.integrations import _daemon_lifecycle_inspection as _inspection
from sase.integrations import _daemon_lifecycle_process as _process
from sase.integrations._daemon_lifecycle_diagnostics import (
    doctor_payload,
    inspection_to_dict,
    print_status,
)
from sase.integrations._daemon_lifecycle_facade import lifecycle_facade
from sase.integrations._daemon_lifecycle_inspection import (
    read_metadata,
    try_health_rpc,
)
from sase.integrations._daemon_lifecycle_types import DaemonInspection


def inspect_daemon_facade(args: argparse.Namespace) -> DaemonInspection:
    facade = lifecycle_facade()
    return _inspection.inspect_daemon(
        args,
        runtime_paths_from_args=facade._runtime_paths_from_args,
        host_identity_from_env=facade._host_identity_from_env,
        process_is_live=facade._process_is_live,
        executable_matches_metadata=facade._executable_matches_metadata,
        metadata_reader=facade._read_metadata,
        health_rpc=facade._try_health_rpc,
    )


def read_metadata_facade(path: Path) -> dict[str, Any] | str | None:
    return read_metadata(path)


def try_health_rpc_facade(socket_path: Path) -> dict[str, Any]:
    return try_health_rpc(socket_path)


def terminate_process_facade(proc: subprocess.Popen[Any]) -> None:
    return _process.terminate_process(proc)


def process_is_live_facade(pid: int) -> bool:
    return _process.process_is_live(pid)


def executable_matches_metadata_facade(pid: int, metadata: dict[str, Any]) -> bool:
    return _process.executable_matches_metadata(pid, metadata)


def print_status_facade(inspection: DaemonInspection) -> None:
    return print_status(inspection)


def inspection_to_dict_facade(inspection: DaemonInspection) -> dict[str, Any]:
    return inspection_to_dict(inspection)


def doctor_payload_facade(inspection: DaemonInspection) -> dict[str, Any]:
    return doctor_payload(inspection)
