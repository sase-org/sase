"""Config and launch wrappers for the daemon lifecycle compatibility facade."""

from __future__ import annotations

import argparse

from sase.integrations._daemon_lifecycle_config import (
    host_identity_from_env,
    load_daemon_config,
    prepare_daemon_launch,
    resolve_gateway_command,
    runtime_paths_from_args,
)
from sase.integrations._daemon_lifecycle_facade import lifecycle_facade
from sase.integrations._daemon_lifecycle_types import (
    DaemonLaunch,
    DaemonLifecycleConfig,
    DaemonRuntimePaths,
)


def load_daemon_config_facade() -> DaemonLifecycleConfig:
    return load_daemon_config()


def prepare_daemon_launch_facade(
    args: argparse.Namespace,
    *,
    config: DaemonLifecycleConfig | None = None,
) -> DaemonLaunch:
    facade = lifecycle_facade()
    if config is None:
        config = facade._load_daemon_config()
    return prepare_daemon_launch(
        args,
        config=config,
        gateway_command_resolver=facade._resolve_gateway_command,
    )


def runtime_paths_from_args_facade(
    args: argparse.Namespace,
    *,
    config: DaemonLifecycleConfig | None = None,
) -> DaemonRuntimePaths:
    if config is None:
        config = lifecycle_facade()._load_daemon_config()
    return runtime_paths_from_args(args, config=config)


def host_identity_from_env_facade() -> str:
    return host_identity_from_env()


def resolve_gateway_command_facade() -> tuple[str, ...]:
    return resolve_gateway_command()
