"""Python facade and supervisor for the local federation worker."""

from __future__ import annotations

from ._constants import (
    FEDERATION_IPC_SCHEMA_VERSION,
    FEDERATION_MAX_FRAME_BYTES,
    FEDERATION_WORKER_COMMAND,
    FEDERATION_WORKER_SOCKET,
)
from ._errors import (
    FederationConfigError,
    FederationWorkerResponseError,
    FederationWorkerUnavailable,
)
from ._facade import FederationFacade, build_federation_facade
from ._hosts import FederationConfig, FederationHostConfig, load_federation_config
from ._ipc import FederationIpcClient
from ._settings import FederationWorkerSettings
from ._supervisor import (
    CommandResolver,
    FederationWorkerSupervisor,
    IpcClientFactory,
    PopenFactory,
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
