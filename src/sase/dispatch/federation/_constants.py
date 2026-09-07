"""Wire-protocol constants shared across the federation package."""

from __future__ import annotations

FEDERATION_IPC_SCHEMA_VERSION = 1
FEDERATION_MAX_FRAME_BYTES = 1024 * 1024
FEDERATION_WORKER_COMMAND = "sase_federation_worker"
FEDERATION_WORKER_SOCKET = "sase-federation-worker.sock"
