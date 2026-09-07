"""Remote dispatch support modules."""

from __future__ import annotations

from .federation import (
    FEDERATION_IPC_SCHEMA_VERSION,
    FEDERATION_MAX_FRAME_BYTES,
    FederationConfig,
    FederationConfigError,
    FederationFacade,
    FederationHostConfig,
    FederationIpcClient,
    FederationWorkerResponseError,
    FederationWorkerSettings,
    FederationWorkerSupervisor,
    FederationWorkerUnavailable,
    build_federation_facade,
    load_federation_config,
    resolve_federation_worker_command,
)

__all__ = [
    "FEDERATION_IPC_SCHEMA_VERSION",
    "FEDERATION_MAX_FRAME_BYTES",
    "FederationConfig",
    "FederationConfigError",
    "FederationFacade",
    "FederationHostConfig",
    "FederationIpcClient",
    "FederationWorkerResponseError",
    "FederationWorkerSettings",
    "FederationWorkerSupervisor",
    "FederationWorkerUnavailable",
    "build_federation_facade",
    "load_federation_config",
    "resolve_federation_worker_command",
]
