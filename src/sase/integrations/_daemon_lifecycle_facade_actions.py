"""Action wrappers for the daemon lifecycle compatibility facade."""

from __future__ import annotations

import argparse
import time
from typing import Any

from sase.integrations import _daemon_lifecycle_actions as _actions
from sase.integrations._daemon_lifecycle_actions import (
    repair_stale_lock,
    run_daemon_backup,
    run_daemon_checkpoint,
    run_daemon_diff,
    run_daemon_list_backups,
    run_daemon_rebuild,
    run_daemon_restore,
    run_daemon_start,
    run_daemon_stop,
    run_daemon_verify,
    wait_for_background_start,
)
from sase.integrations._daemon_lifecycle_facade import lifecycle_facade
from sase.integrations._daemon_lifecycle_types import (
    DaemonInspection,
    DaemonLaunch,
    KillFn,
    PopenFactory,
    SleepFn,
)


def run_daemon_start_facade(
    args: argparse.Namespace,
    *,
    popen: PopenFactory = _actions.subprocess.Popen,
    sleep: SleepFn = time.sleep,
) -> int:
    facade = lifecycle_facade()
    return run_daemon_start(
        args,
        popen=popen,
        sleep=sleep,
        prepare_daemon_launch=facade._prepare_daemon_launch,
        background_start_waiter=facade._wait_for_background_start,
        terminate_process=facade._terminate_process,
    )


def run_daemon_stop_facade(
    args: argparse.Namespace,
    *,
    kill: KillFn = _actions.os.kill,
    sleep: SleepFn = time.sleep,
) -> int:
    facade = lifecycle_facade()
    return run_daemon_stop(
        args,
        kill=kill,
        sleep=sleep,
        inspect_daemon=facade._inspect_daemon,
        process_is_live=facade._process_is_live,
        executable_matches_metadata=facade._executable_matches_metadata,
    )


def run_daemon_rebuild_facade(args: argparse.Namespace) -> dict[str, Any]:
    facade = lifecycle_facade()
    return run_daemon_rebuild(
        args,
        inspect_daemon=facade._inspect_daemon,
        prepare_daemon_launch=facade._prepare_daemon_launch,
    )


def repair_stale_lock_facade(args: argparse.Namespace) -> dict[str, Any]:
    return repair_stale_lock(args, inspect_daemon=lifecycle_facade()._inspect_daemon)


def run_daemon_checkpoint_facade(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_checkpoint(
        args, inspect_daemon=lifecycle_facade()._inspect_daemon
    )


def run_daemon_backup_facade(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_backup(args, inspect_daemon=lifecycle_facade()._inspect_daemon)


def run_daemon_list_backups_facade(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_list_backups(
        args,
        inspect_daemon=lifecycle_facade()._inspect_daemon,
    )


def run_daemon_restore_facade(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_restore(args, inspect_daemon=lifecycle_facade()._inspect_daemon)


def run_daemon_verify_facade(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_verify(args, inspect_daemon=lifecycle_facade()._inspect_daemon)


def run_daemon_diff_facade(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_diff(args, inspect_daemon=lifecycle_facade()._inspect_daemon)


def wait_for_background_start_facade(
    launch: DaemonLaunch,
    proc: _actions.subprocess.Popen[Any],
    sleep: SleepFn,
) -> DaemonInspection:
    return wait_for_background_start(
        launch,
        proc,
        sleep,
        inspect_daemon=lifecycle_facade()._inspect_daemon,
    )
