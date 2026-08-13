"""Launch the follow-up agent into a monitor's lane once it goes terminal.

Reuses the same ``%id(<suffix>, family=<parent>)`` family-attach machinery a
user-typed directive would trigger (:mod:`sase.agent.family_attach`): the
monitor's lane is resolved to a family-attach plan, encoded into the child's
launch environment, and the child's own runner boot adopts the resulting name,
family, and role when it starts -- exactly as it would for an interactive
``%id(@, family=acme)`` launch.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from sase.agent.family_attach import (
    FAMILY_ATTACH_ENV,
    FamilyAttachDirective,
    FamilyAttachError,
    resolve_family_attach_plan,
)
from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.agent.launcher import spawn_agent_subprocess
from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.core.agent_artifact_paths import canonical_agent_artifact_path
from sase.core.agent_launch_facade import reserve_launch_timestamp_batch
from sase.workflows.utils import get_project_file_path

from .followup_prompt import compose_followup_prompt
from .output import OutputCapture

#: How long to wait for the starter's own ``done.json`` before composing the
#: follow-up prompt without a ``#fork:`` prefix. Injectable so tests do not
#: have to wait out the real budget for the common "no starter" case.
DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS = 60.0
_STARTER_SETTLE_POLL_SECONDS = 0.5


def launch_followup_agent(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    monitor_state: str,
    exit_code: int | None,
    elapsed_seconds: float,
    capture: OutputCapture,
    project_name: str,
    timeout_kind: str | None = None,
    settle_timeout_seconds: float = DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS,
) -> bool:
    """Launch the agent named by ``monitor_next_action`` into the same lane.

    Returns whether the launch succeeded. On failure, ``monitor_followup_error``
    is recorded on the monitor member's own metadata; the caller is
    responsible for releasing the workspace claim and notifying.
    """
    next_action = str(meta.get("monitor_next_action") or "")
    lane = str(meta.get("agent_family") or "")
    if not next_action or not lane:
        return False

    parent_timestamp = meta.get("parent_timestamp")
    starter_name, starter_role = _starter_identity(project_name, parent_timestamp)
    settled = _wait_for_starter(
        project_name,
        parent_timestamp,
        timeout_seconds=settle_timeout_seconds,
    )

    prompt = compose_followup_prompt(
        starter_name=starter_name if settled else None,
        command=str(meta.get("monitor_command") or ""),
        cwd=str(meta.get("monitor_cwd") or ""),
        reason=str(meta.get("monitor_reason") or ""),
        monitor_state=monitor_state,
        exit_code=exit_code,
        started_at=meta.get("run_started_at"),
        stopped_at=meta.get("stopped_at"),
        elapsed_seconds=elapsed_seconds,
        timeout_seconds=float(meta.get("monitor_timeout_seconds") or 0.0),
        idle_timeout_seconds=float(meta.get("monitor_idle_timeout_seconds") or 0.0),
        timeout_kind=timeout_kind or meta.get("monitor_timeout_kind"),
        monitor_id=str(meta.get("monitor_id") or ""),
        output_text=capture.retained_text(),
        tail_lines=int(meta.get("monitor_tail_lines") or 200),
        total_bytes=capture.total_bytes,
        output_truncated=capture.truncated,
        next_action=next_action,
    )

    try:
        plan = resolve_family_attach_plan(
            FamilyAttachDirective(parent=lane, suffix="@"),
            project_name=project_name,
        )
        plan = replace(
            plan,
            parent_is_running=False,
            agent_family_role=starter_role or plan.agent_family_role,
        )
        env = {
            INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
            FAMILY_ATTACH_ENV: json.dumps(asdict(plan), sort_keys=True),
        }
        timestamp = reserve_launch_timestamp_batch(1)[0]
        spawn_agent_subprocess(
            cl_name=str(meta.get("cl_name") or plan.agent_name),
            project_file=get_project_file_path(project_name),
            workspace_dir=str(meta.get("workspace_dir") or ""),
            workspace_num=int(meta.get("workspace_num") or 0),
            workflow_name=f"ace(run)-{timestamp}",
            prompt=prompt,
            timestamp=timestamp,
            project_name=project_name,
            extra_env=env,
            retry_transfer_from_pid=os.getpid(),
        )
    except (FamilyAttachError, RuntimeError, OSError, ValueError) as exc:
        meta["monitor_followup_error"] = str(exc)
        update_meta_field(artifacts_dir, "monitor_followup_error", str(exc))
        return False

    meta["monitor_followup_agent"] = plan.agent_name
    update_meta_field(artifacts_dir, "monitor_followup_agent", plan.agent_name)
    return True


def _starter_artifacts_dir(project_name: str, parent_timestamp: object) -> str | None:
    if not isinstance(parent_timestamp, str) or not parent_timestamp:
        return None
    return str(canonical_agent_artifact_path(project_name, "ace-run", parent_timestamp))


def _read_meta_str(artifacts_dir: str, key: str) -> str | None:
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with meta_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return None
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


def _starter_identity(
    project_name: str, parent_timestamp: object
) -> tuple[str | None, str | None]:
    starter_dir = _starter_artifacts_dir(project_name, parent_timestamp)
    if starter_dir is None:
        return None, None
    return (
        _read_meta_str(starter_dir, "name"),
        _read_meta_str(starter_dir, "agent_family_role"),
    )


def _wait_for_starter(
    project_name: str,
    parent_timestamp: object,
    *,
    timeout_seconds: float,
) -> bool:
    """Poll (bounded) for the starter's terminal marker before forking its chat.

    Two agents must never be live in one lane at once, and ``#fork`` needs
    the starter's chat to already be saved. Returns ``False`` -- continue
    without the ``#fork`` prefix -- rather than dropping the follow-up.
    """
    starter_dir = _starter_artifacts_dir(project_name, parent_timestamp)
    if starter_dir is None:
        return False
    done_path = Path(starter_dir) / "done.json"
    deadline = time.monotonic() + timeout_seconds
    while not done_path.exists() and time.monotonic() < deadline:
        time.sleep(_STARTER_SETTLE_POLL_SECONDS)
    return done_path.exists()


__all__ = ["DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS", "launch_followup_agent"]
