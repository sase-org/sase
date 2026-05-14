"""Configuration, path, and argv assembly for the local SASE daemon."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.config.core import load_merged_config
from sase.daemon.paths import (
    SOCKET_FILENAME,
    default_run_root,
    sanitize_host_identity,
)
from sase.integrations._daemon_lifecycle_types import (
    DEFAULT_STARTUP_TIMEOUT_SECONDS,
    LOCK_METADATA_FILENAME,
    DaemonLaunch,
    DaemonLifecycleConfig,
    DaemonLifecycleError,
    DaemonRuntimePaths,
)
from sase.integrations._daemon_lifecycle_values import (
    command_value,
    optional_path,
    positive_float,
)


def load_daemon_config() -> DaemonLifecycleConfig:
    raw = load_merged_config().get("daemon", {})
    if not isinstance(raw, dict):
        raw = {}
    return DaemonLifecycleConfig(
        command=command_value(raw.get("command")),
        sase_home=optional_path(raw.get("sase_home")),
        run_root=optional_path(raw.get("run_root")),
        socket_path=optional_path(raw.get("socket_path")),
        disable_mobile_http=bool(raw.get("disable_mobile_http", False)),
        startup_timeout_seconds=positive_float(
            raw.get("startup_timeout_seconds"),
            DEFAULT_STARTUP_TIMEOUT_SECONDS,
        ),
    )


def prepare_daemon_launch(
    args: argparse.Namespace,
    *,
    config: DaemonLifecycleConfig | None = None,
    gateway_command_resolver: Callable[[], tuple[str, ...]] | None = None,
) -> DaemonLaunch:
    """Merge CLI/config values and build the safe gateway daemon argv."""
    config = config or load_daemon_config()
    command = command_value(getattr(args, "daemon_command", None)) or config.command
    if not command:
        resolver = gateway_command_resolver or resolve_gateway_command
        command = resolver()
    if not command:
        raise DaemonLifecycleError(
            "sase_gateway binary not found; set daemon.command in SASE config "
            "or pass --command/-c"
        )

    paths = runtime_paths_from_args(args, config=config)
    foreground = bool(getattr(args, "foreground", False))
    disable_mobile_http = config.disable_mobile_http or bool(
        getattr(args, "disable_mobile_http", False)
    )
    startup_timeout = positive_float(
        getattr(args, "startup_timeout", None),
        config.startup_timeout_seconds,
    )

    argv = [*command, "daemon", "--sase-home", str(paths.sase_home)]
    if _arg_path(args, "run_root") is not None or config.run_root is not None:
        argv.extend(["--run-root", str(paths.run_root)])
    if _arg_path(args, "socket_path") is not None or config.socket_path is not None:
        argv.extend(["--socket-path", str(paths.socket_path)])
    if foreground:
        argv.append("--foreground")
    if bool(getattr(args, "tokio_console", False)):
        argv.append("--tokio-console")
    if disable_mobile_http:
        argv.append("--disable-mobile-http")
    if bind_address := getattr(args, "bind_address", None):
        argv.extend(["--bind", str(bind_address)])
    if bool(getattr(args, "allow_non_loopback", False)):
        argv.append("--allow-non-loopback")
    if agent_bridge_command := command_value(
        getattr(args, "agent_bridge_command", None)
    ):
        argv.extend(["--agent-bridge-command", shlex.join(agent_bridge_command)])
    if helper_bridge_command := command_value(
        getattr(args, "helper_bridge_command", None)
    ):
        argv.extend(["--helper-bridge-command", shlex.join(helper_bridge_command)])

    return DaemonLaunch(
        argv=argv,
        paths=paths,
        foreground=foreground,
        startup_timeout_seconds=startup_timeout,
    )


def runtime_paths_from_args(
    args: argparse.Namespace,
    *,
    config: DaemonLifecycleConfig | None = None,
) -> DaemonRuntimePaths:
    """Resolve daemon runtime paths using the same defaults as ``sase_gateway``."""
    config = config or load_daemon_config()
    sase_home = (
        _arg_path(args, "sase_home")
        or config.sase_home
        or Path(os.environ.get("SASE_HOME") or Path.home() / ".sase")
    ).expanduser()
    run_root = (
        _arg_path(args, "run_root")
        or config.run_root
        or default_run_root(sase_home, host_identity_from_env())
    ).expanduser()
    socket_path = (
        _arg_path(args, "socket_path")
        or config.socket_path
        or run_root / SOCKET_FILENAME
    ).expanduser()
    return DaemonRuntimePaths(
        sase_home=sase_home,
        run_root=run_root,
        socket_path=socket_path,
        metadata_path=run_root / LOCK_METADATA_FILENAME,
    )


def host_identity_from_env() -> str:
    value = os.environ.get("HOSTNAME")
    return sanitize_host_identity(value) if value and value.strip() else "sase-host"


def resolve_gateway_command() -> tuple[str, ...]:
    path = shutil.which("sase_gateway")
    if path:
        return (path,)

    repo_root = Path(__file__).resolve().parents[3]
    sibling_core = repo_root.parent / "sase-core"
    for candidate in (
        sibling_core / "target" / "debug" / "sase_gateway",
        sibling_core / "target" / "release" / "sase_gateway",
    ):
        if candidate.is_file():
            return (str(candidate),)
    return ()


def _arg_path(args: argparse.Namespace, name: str) -> Path | None:
    return optional_path(getattr(args, name, None))
