"""Per-checkout occupant marker (guard phase of sase-q0).

Each managed checkout carries a ``.sase/occupant.json`` naming the agent
that currently holds it: pid, artifacts timestamp, agent name, workflow,
project, cl_name, and claim time.  It is written when an agent takes a
workspace and cleared when the claim is released, and is the checkout-local
half of the occupancy guard — the RUNNING field is the allocation ledger,
this file is what a destructive preparation step checks before it cleans or
resets the tree it is sitting in.

Like ``.sase/checkout.json`` (see ``marker.py``), this file lives under the
``.sase/`` directory that ``ensure_sase_git_info_excludes`` keeps out of
``git clean``.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


OCCUPANT_DIR = ".sase"
OCCUPANT_FILENAME = "occupant.json"


@dataclass(frozen=True)
class OccupantRecord:
    """Identity of the agent that currently holds a checkout."""

    pid: int
    workflow: str
    project: str
    workspace_num: int
    artifacts_timestamp: str | None = None
    agent_name: str | None = None
    cl_name: str | None = None
    claimed_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OccupantRecord:
        return cls(
            pid=int(raw["pid"]),
            workflow=str(raw.get("workflow", "")),
            project=str(raw.get("project", "")),
            workspace_num=int(raw.get("workspace_num", 0)),
            artifacts_timestamp=raw.get("artifacts_timestamp"),
            agent_name=raw.get("agent_name"),
            cl_name=raw.get("cl_name"),
            claimed_at=float(raw.get("claimed_at", 0.0)),
        )

    def to_wire_dict(self) -> dict[str, Any]:
        """Project to the shape ``sase_core``'s ``OccupantRecordWire`` expects."""
        return {
            "pid": self.pid,
            "artifacts_timestamp": self.artifacts_timestamp,
            "agent_name": self.agent_name,
            "workflow": self.workflow,
            "project": self.project,
            "workspace_num": self.workspace_num,
            "cl_name": self.cl_name,
            "claimed_at": self.claimed_at,
        }


def occupant_marker_path(checkout_dir: str) -> str:
    """Return the path to the occupant marker inside *checkout_dir*."""
    return str(Path(checkout_dir) / OCCUPANT_DIR / OCCUPANT_FILENAME)


def write_occupant_record(checkout_dir: str, record: OccupantRecord) -> None:
    """Atomically write *record* as the occupant marker for *checkout_dir*.

    Best-effort: any failure is swallowed so a degraded filesystem can never
    fail the claim this record documents.  A missing occupant marker is
    always treated as "unoccupied" by the occupancy guard, so a failed
    write only weakens protection — it never blocks a legitimate agent.
    """
    try:
        path = occupant_marker_path(checkout_dir)
        parent = os.path.dirname(path)
        os.makedirs(parent, exist_ok=True)
        payload = json.dumps(record.to_dict(), indent=2, sort_keys=True)

        fd, temp_path = tempfile.mkstemp(dir=parent, prefix=".occupant.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(temp_path, path)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
    except Exception:
        return


def read_occupant_record(checkout_dir: str) -> OccupantRecord | None:
    """Read the occupant marker from *checkout_dir*, or return ``None``.

    A missing or malformed marker is treated as absent so the occupancy
    guard falls back to "unoccupied" rather than raising.
    """
    path = occupant_marker_path(checkout_dir)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return OccupantRecord.from_dict(data)
    except (TypeError, ValueError, KeyError):
        return None


def clear_occupant_record(checkout_dir: str) -> None:
    """Best-effort removal of the occupant marker for *checkout_dir*."""
    try:
        os.unlink(occupant_marker_path(checkout_dir))
    except OSError:
        return


def new_occupant_record(
    *,
    pid: int,
    workflow: str,
    project: str,
    workspace_num: int,
    artifacts_timestamp: str | None = None,
    agent_name: str | None = None,
    cl_name: str | None = None,
) -> OccupantRecord:
    """Build an :class:`OccupantRecord` claimed at the current wall-clock time."""
    return OccupantRecord(
        pid=pid,
        workflow=workflow,
        project=project,
        workspace_num=workspace_num,
        artifacts_timestamp=artifacts_timestamp,
        agent_name=agent_name,
        cl_name=cl_name,
        claimed_at=time.time(),
    )


__all__ = [
    "OCCUPANT_DIR",
    "OCCUPANT_FILENAME",
    "OccupantRecord",
    "clear_occupant_record",
    "new_occupant_record",
    "occupant_marker_path",
    "read_occupant_record",
    "write_occupant_record",
]
