"""Persist a recovery bundle before a restart destroys the old run.

A restart stops the agent and wipes its name before relaunching, so the
rewritten prompt is snapshotted under ``~/.sase/restarts`` first: if the wipe
or the relaunch fails, the operator still has a command that reruns it.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from sase.agent._restart_types import AgentRestartPlan, ProgressFn
from sase.core.time import get_timezone


def prepare_recovery(
    plan: AgentRestartPlan,
    emit: ProgressFn,
) -> tuple[str | None, str | None, str | None]:
    """Return the ``(dir, command, inline prompt)`` recovery hand-back."""
    dest = _persist_recovery_bundle(plan)
    if dest is None:
        emit("recovery", "warn", "could not persist a recovery bundle")
        return None, None, plan.rewritten_prompt
    rewritten = dest / "rewritten.md"
    command = f'sase run "$(cat {rewritten})"'
    return str(dest), command, None


def _persist_recovery_bundle(plan: AgentRestartPlan) -> Path | None:
    from sase.core.paths import sase_subdir

    try:
        dest = _new_recovery_dir(plan, sase_subdir("restarts"))
        dest.mkdir(parents=True, exist_ok=True)
        _write_recovery_files(plan, dest)
    except Exception:
        return None
    if not (dest / "rewritten.md").is_file():
        return None
    return dest


def _new_recovery_dir(plan: AgentRestartPlan, root: Path) -> Path:
    stamp = datetime.now(get_timezone()).strftime("%Y%m%d%H%M%S")
    safe = plan.presented_name.replace("/", "-").replace(os.sep, "-")
    dest = root / f"{stamp}-{safe}"
    if dest.exists():
        dest = root / f"{stamp}-{safe}-{os.getpid()}"
    return dest


def _write_recovery_files(plan: AgentRestartPlan, dest: Path) -> None:
    raw_src = plan.artifacts_dir / "raw_xprompt.md"
    if raw_src.is_file():
        shutil.copy2(raw_src, dest / "raw_xprompt.md")
    else:
        (dest / "raw_xprompt.md").write_text(plan.original_prompt, encoding="utf-8")
    (dest / "rewritten.md").write_text(plan.rewritten_prompt, encoding="utf-8")
    meta_src = plan.artifacts_dir / "agent_meta.json"
    if meta_src.is_file():
        shutil.copy2(meta_src, dest / "agent_meta.json")
    else:
        (dest / "agent_meta.json").write_text(
            json.dumps(plan.meta, indent=2) + "\n", encoding="utf-8"
        )
    restarted_at = datetime.now(get_timezone()).isoformat()
    payload = {
        "name": plan.name,
        "project": plan.project,
        "artifacts_dir": str(plan.artifacts_dir),
        "timestamps": {
            "restarted_at": restarted_at,
            "source": plan.artifacts_dir.name,
        },
    }
    (dest / "restart.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
