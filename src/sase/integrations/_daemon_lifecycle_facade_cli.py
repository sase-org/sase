"""CLI handler wrappers for the daemon lifecycle compatibility facade."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import cast


def _handler(name: str) -> Callable[[argparse.Namespace], int]:
    from sase.integrations import _daemon_lifecycle_cli

    return cast(
        Callable[[argparse.Namespace], int], getattr(_daemon_lifecycle_cli, name)
    )


def handle_daemon_start(args: argparse.Namespace) -> int:
    return _handler("handle_daemon_start")(args)


def handle_daemon_status(args: argparse.Namespace) -> int:
    return _handler("handle_daemon_status")(args)


def handle_daemon_rollout(args: argparse.Namespace) -> int:
    return _handler("handle_daemon_rollout")(args)


def handle_daemon_scheduler(args: argparse.Namespace) -> int:
    return _handler("handle_daemon_scheduler")(args)


def handle_daemon_stop(args: argparse.Namespace) -> int:
    return _handler("handle_daemon_stop")(args)


def handle_daemon_doctor(args: argparse.Namespace) -> int:
    return _handler("handle_daemon_doctor")(args)


def handle_daemon_rebuild(args: argparse.Namespace) -> int:
    return _handler("handle_daemon_rebuild")(args)


def handle_daemon_checkpoint(args: argparse.Namespace) -> int:
    return _handler("handle_daemon_checkpoint")(args)


def handle_daemon_backup(args: argparse.Namespace) -> int:
    return _handler("handle_daemon_backup")(args)


def handle_daemon_list_backups(args: argparse.Namespace) -> int:
    return _handler("handle_daemon_list_backups")(args)


def handle_daemon_restore(args: argparse.Namespace) -> int:
    return _handler("handle_daemon_restore")(args)


def handle_daemon_verify(args: argparse.Namespace) -> int:
    return _handler("handle_daemon_verify")(args)


def handle_daemon_diff(args: argparse.Namespace) -> int:
    return _handler("handle_daemon_diff")(args)
