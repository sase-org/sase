"""Tests for the local federation-worker Python facade.

Split facade: the tests now live in ``test_dispatch_federation_config``,
``test_dispatch_federation_facade``, and ``test_dispatch_federation_ipc``,
with shared helpers in ``_dispatch_federation_helpers``. This module
re-exports the public names so the original import path keeps working. It
collects no tests itself.
"""

from __future__ import annotations

from tests.test_dispatch_federation_config import (
    test_dispatch_machines_degrade_to_diagnostics,
    test_dispatch_machines_resolve_local_credentials,
    test_empty_remote_hosts_keep_facade_disabled_without_rust_binding,
    test_federation_worker_resolver_checks_active_python_environment,
    test_host_config_requires_env_credentials,
    test_host_config_validates_plan_and_redacts_secret,
    test_machine_config_derives_federation_host_from_local_credential,
)
from tests.test_dispatch_federation_facade import (
    test_facade_catalog_hosts_threads_per_host_queries,
    test_facade_read_deadline_preserves_healthy_partial_host,
    test_supervisor_spawns_worker_and_replaces_config,
)
from tests.test_dispatch_federation_ipc import (
    test_ipc_client_decodes_success_and_error_frames,
    test_ipc_client_rejects_oversized_response,
    test_ipc_recv_timeout_is_worker_timeout_with_grace,
    test_ipc_refused_socket_is_plain_unavailable,
    test_supervisor_does_not_respawn_or_resend_on_worker_timeout,
    test_supervisor_slow_health_probe_does_not_spawn_worker,
    test_supervisor_still_respawns_and_retries_refused_connection,
)

__test__ = False

__all__ = [
    "test_dispatch_machines_degrade_to_diagnostics",
    "test_dispatch_machines_resolve_local_credentials",
    "test_empty_remote_hosts_keep_facade_disabled_without_rust_binding",
    "test_facade_catalog_hosts_threads_per_host_queries",
    "test_facade_read_deadline_preserves_healthy_partial_host",
    "test_federation_worker_resolver_checks_active_python_environment",
    "test_host_config_requires_env_credentials",
    "test_host_config_validates_plan_and_redacts_secret",
    "test_ipc_client_decodes_success_and_error_frames",
    "test_ipc_client_rejects_oversized_response",
    "test_ipc_recv_timeout_is_worker_timeout_with_grace",
    "test_ipc_refused_socket_is_plain_unavailable",
    "test_machine_config_derives_federation_host_from_local_credential",
    "test_supervisor_does_not_respawn_or_resend_on_worker_timeout",
    "test_supervisor_slow_health_probe_does_not_spawn_worker",
    "test_supervisor_spawns_worker_and_replaces_config",
    "test_supervisor_still_respawns_and_retries_refused_connection",
]
