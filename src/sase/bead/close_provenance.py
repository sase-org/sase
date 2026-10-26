"""Stable host-run identity for bead close provenance.

A close stamped with this run's origin can be recovered by the failed-close
recovery coordinator when host finalization terminally fails. The identity is
read from process state at close time — never from a declaration — so closes
are attributable even when ``/sase_final`` never ran.

The monitor/prepared-completion path overrides the ambient run identity with
``SASE_CLOSE_RECOVERY_*`` variables carrying the prepared intent's source
identity: a monitor has its own artifacts and may mint a new nonce, so the
ambient ``SASE_AGENT_TIMESTAMP`` would attribute the close to the wrong run.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

RUN_ID_ENV_VAR = "SASE_AGENT_TIMESTAMP"
ARTIFACTS_DIR_ENV_VAR = "SASE_ARTIFACTS_DIR"

# Prepared-intent source-identity overrides for the monitor path. Set and
# restored around the no-model ``run_finalizers`` call so terminal-failure
# recovery attributes the prepared run, not the monitor.
RECOVERY_RUN_ID_ENV_VAR = "SASE_CLOSE_RECOVERY_RUN_ID"
RECOVERY_AGENT_NAME_ENV_VAR = "SASE_CLOSE_RECOVERY_AGENT_NAME"
RECOVERY_ARTIFACTS_DIR_ENV_VAR = "SASE_CLOSE_RECOVERY_ARTIFACTS_DIR"


def host_run_close_provenance(
    env: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Return this run's close-provenance dict, or ``None`` when unattributed.

    Returns ``None`` when no stable run identity is available (a human shell
    or any context without ``SASE_AGENT_TIMESTAMP`` and an agent name):
    unattributed closes are never recovered. Never guesses from assignees or
    timestamps.
    """
    current_env = os.environ if env is None else env
    run_id = (current_env.get(RECOVERY_RUN_ID_ENV_VAR) or "").strip()
    override_agent = (current_env.get(RECOVERY_AGENT_NAME_ENV_VAR) or "").strip()
    artifact_dir = (current_env.get(RECOVERY_ARTIFACTS_DIR_ENV_VAR) or "").strip()
    if run_id and override_agent and artifact_dir:
        return {
            "run_id": run_id,
            "agent_name": override_agent,
            "artifact_dir": artifact_dir,
        }
    run_id = (current_env.get(RUN_ID_ENV_VAR) or "").strip()
    artifact_dir = (current_env.get(ARTIFACTS_DIR_ENV_VAR) or "").strip()
    if not run_id or not artifact_dir:
        return None
    agent_name = _agent_name(current_env)
    if not agent_name:
        return None
    return {
        "run_id": run_id,
        "agent_name": agent_name,
        "artifact_dir": artifact_dir,
    }


def _agent_name(env: Mapping[str, str]) -> str | None:
    from sase.agent.identity import discover_agent_identity

    identity = discover_agent_identity(env)
    if identity is None or not identity.name.strip():
        return None
    return identity.name


__all__ = [
    "ARTIFACTS_DIR_ENV_VAR",
    "RECOVERY_AGENT_NAME_ENV_VAR",
    "RECOVERY_ARTIFACTS_DIR_ENV_VAR",
    "RECOVERY_RUN_ID_ENV_VAR",
    "RUN_ID_ENV_VAR",
    "host_run_close_provenance",
]
