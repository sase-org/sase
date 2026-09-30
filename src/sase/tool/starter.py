"""Starter identity for agent-scoped detached ToolRuns.

A detached run is scoped to the agent runner that started it: the process
whose PID ``kill_agent_runner_group`` reads from
``$SASE_ARTIFACTS_DIR/agent_meta.json`` (written in-process by the runner at
launch via ``os.getpid()`` in ``run_agent_runner_setup_meta`` and
``build_agent_meta``). The ``sase tool run -d`` CLI runs as a child of that
runner, so resolution reads the runner PID from the meta file, never from
``os.getpid()``.

A PID alone is not durable (Linux reuses PIDs), so the starter record pairs
the PID with boot/start-time identity from ``process_identity_token``. Both
the worker watchdog and the end-of-invocation cleanup require a matching
identity plus liveness; a reused PID is never proof of life.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.process_identity import process_identity_token

#: Typed ``resolve_starter`` failure reasons (fail-closed: exit 1, start nothing).
NOT_AGENT = "not-agent"
NO_AGENT_NAME = "no-agent-name"
NO_ARTIFACTS_DIR = "no-artifacts-dir"
META_UNREADABLE = "meta-unreadable"
PID_MISSING = "pid-missing"
IDENTITY_UNREADABLE = "identity-unreadable"


@dataclass(frozen=True)
class StarterResolution:
    """Outcome of ``resolve_starter``: a starter wire dict or a typed reason."""

    starter: dict[str, Any] | None
    reason: str | None = None

    @property
    def resolved(self) -> bool:
        return self.starter is not None


def _meta_path(artifacts_dir: str) -> Path:
    return Path(artifacts_dir).expanduser() / "agent_meta.json"


def resolve_starter(env: Mapping[str, str] | None = None) -> StarterResolution:
    """Resolve the starter record for the calling agent runner.

    Reads ``SASE_AGENT``, ``SASE_AGENT_NAME``, and the runner PID from
    ``$SASE_ARTIFACTS_DIR/agent_meta.json``. Returns the starter wire dict
    (``agent``, ``pid``, ``boot_id``, ``process_start_identity``) or a typed
    reason; never raises.
    """

    environ: Mapping[str, str] = os.environ if env is None else env
    if not str(environ.get("SASE_AGENT") or "").strip():
        return StarterResolution(starter=None, reason=NOT_AGENT)
    agent = str(environ.get("SASE_AGENT_NAME") or "").strip()
    if not agent:
        return StarterResolution(starter=None, reason=NO_AGENT_NAME)
    artifacts_dir = str(environ.get("SASE_ARTIFACTS_DIR") or "").strip()
    if not artifacts_dir:
        return StarterResolution(starter=None, reason=NO_ARTIFACTS_DIR)
    try:
        with open(_meta_path(artifacts_dir), encoding="utf-8") as stream:
            meta = json.load(stream)
    except (OSError, ValueError):
        return StarterResolution(starter=None, reason=META_UNREADABLE)
    if not isinstance(meta, dict):
        return StarterResolution(starter=None, reason=META_UNREADABLE)
    raw_pid = meta.get("pid")
    try:
        pid = int(raw_pid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return StarterResolution(starter=None, reason=PID_MISSING)
    if pid <= 0:
        return StarterResolution(starter=None, reason=PID_MISSING)
    identity = process_identity_token(pid)
    if not identity:
        fallback = meta.get("process_identity")
        if isinstance(fallback, str) and fallback:
            identity = fallback
    if not identity:
        return StarterResolution(starter=None, reason=IDENTITY_UNREADABLE)
    boot_id, _, _ = identity.partition(":")
    starter: dict[str, Any] = {
        "agent": agent,
        "pid": pid,
        "boot_id": boot_id or None,
        "process_start_identity": identity,
    }
    return StarterResolution(starter=starter)


def _pid_is_zombie(pid: int) -> bool:
    """Return whether *pid* is a zombie (dead but unreaped).

    A zombie keeps its ``/proc`` entry and its start identity, so identity
    alone calls it alive; but the runner has ended, and a starter-scoped run
    must not outlive it. Unknown (no ``/proc``, unreadable stat) is not a
    zombie.
    """

    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    close_paren = stat.rfind(")")
    if close_paren < 0:
        return False
    fields = stat[close_paren + 1 :].split()
    try:
        state = fields[0]
    except IndexError:
        return False
    return state == "Z"


def _pid_live(pid: int) -> bool:
    """Return whether *pid* names a live process; unknown counts as live."""

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except OSError:
        return True
    if _pid_is_zombie(pid):
        return False
    return True


def starter_alive(starter: Mapping[str, Any]) -> bool:
    """Return whether a starter record still names its live runner.

    Requires the same boot (when both sides can read one), a live PID, and
    a matching start identity on a definite comparison. A reused PID never
    counts: a definite identity mismatch, a boot change, or a dead PID all
    read as not alive. An unreadable present is not proof of death, so an
    unknown liveness leaves the run alone (returns True).
    """

    try:
        pid = int(starter.get("pid"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    recorded_boot = str(starter.get("boot_id") or "")
    if recorded_boot:
        try:
            from sase.tool.liveness import current_boot_id
        except Exception:  # noqa: BLE001 - unreadable boot is not proof.
            current_boot: str | None = None
        else:
            try:
                current_boot = current_boot_id()
            except Exception:  # noqa: BLE001 - unreadable boot is not proof.
                current_boot = None
        if current_boot and recorded_boot != current_boot:
            return False
    recorded_identity = starter.get("process_start_identity")
    if isinstance(recorded_identity, str) and recorded_identity:
        current_identity = process_identity_token(pid)
        if current_identity:
            if current_identity != recorded_identity:
                # Definite reuse or replacement: not our starter.
                return False
            return _pid_live(pid)
        # The identity is recorded but currently unreadable: only a dead
        # PID is definite proof; anything else leaves the run alone.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True
    return _pid_live(pid)


__all__ = [
    "IDENTITY_UNREADABLE",
    "META_UNREADABLE",
    "NOT_AGENT",
    "NO_AGENT_NAME",
    "NO_ARTIFACTS_DIR",
    "PID_MISSING",
    "StarterResolution",
    "resolve_starter",
    "starter_alive",
]
