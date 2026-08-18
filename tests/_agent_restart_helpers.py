"""Shared fixtures for ``sase agent restart`` tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from sase.agent.force_reuse_launch import ForceReuseLaunchPlan
from sase.agent.names import AgentNameWipePreview, NamedAgent
from sase.agent.restart import (
    AgentRestartPlan,
    AgentRestartPreview,
)
from sase.agent.running import KillResult
from tests._agent_names_fixtures import make_agent

DEFAULT_PROMPT = "%id:02p\n#gh:sase\nDo the work"


def make_restartable_agent(
    base: Path,
    *,
    name: str = "02p",
    project: str = "gh_sase-org__sase",
    suffix: str = "20260818120000",
    done: bool = False,
    outcome: str | None = None,
    pid: int | None = 481920,
    raw_prompt: str | None = DEFAULT_PROMPT,
    agent_family: str | None = None,
    role_suffix: str | None = None,
    extra_meta: dict[str, object] | None = None,
) -> Path:
    """Materialize a fake agent artifacts dir that planning can read."""
    return make_agent(
        base,
        project,
        suffix,
        name,
        done=done,
        outcome=outcome,
        pid=pid,
        agent_family=agent_family,
        role_suffix=role_suffix,
        raw_prompt=raw_prompt,
        extra_meta=extra_meta,
    )


def named_agent_for(path: Path, *, name: str = "02p", done: bool = False) -> NamedAgent:
    return NamedAgent(
        name=name,
        artifacts_dir=str(path),
        is_done=done,
        outcome="completed" if done else None,
    )


def dummy_force_plan(
    prompt: str = "%id:02p\n#gh:sase\nDo the work",
    owner_names: list[str] | None = None,
) -> ForceReuseLaunchPlan:
    return ForceReuseLaunchPlan(
        rewritten_prompt=prompt,
        owner_names=owner_names or ["02p"],
        segment_envs=[None],
    )


def dummy_preview(**overrides: Any) -> AgentRestartPreview:
    fields: dict[str, Any] = {
        "status": "RUNNING",
        "project_display": "sase",
        "patch": None,
        "workspace_num": 12,
        "pid": 481920,
        "model": "opus",
        "provider": "claude",
        "reasoning_effort": None,
        "model_alias": None,
        "started": "2m ago",
        "elapsed": "2m0s",
        "family": None,
        "bead": None,
        "prompt_excerpt": "Do the work",
        "target": "#gh:sase",
        "name_reuse": "forced (%id(!02p)) · from prompt",
        "model_override_label": None,
        "warnings": ("Restarting a running agent discards its in-flight work.",),
        "is_live": True,
        "has_file_changes": False,
    }
    fields.update(overrides)
    return AgentRestartPreview(**fields)


def dummy_wipe_preview(
    artifacts_dir: Path | None = None,
    **overrides: Any,
) -> AgentNameWipePreview:
    fields: dict[str, Any] = {
        "artifact_dirs": (str(artifacts_dir),) if artifacts_dir is not None else (),
        "bundle_paths": (),
        "names": ("02p",),
        "container_kind": None,
    }
    fields.update(overrides)
    return AgentNameWipePreview(**fields)


def dummy_plan(
    artifacts_dir: Path,
    *,
    done: bool = False,
    **overrides: Any,
) -> AgentRestartPlan:
    name = str(overrides.pop("name", "02p"))
    agent = overrides.pop(
        "agent",
        named_agent_for(artifacts_dir, name=name, done=done),
    )
    preview = overrides.pop("preview", dummy_preview(is_live=not done))
    fields: dict[str, Any] = {
        "name": name,
        "lookup_name": name,
        "presented_name": name,
        "agent": agent,
        "artifacts_dir": artifacts_dir,
        "project": "gh_sase-org__sase",
        "meta": {"name": name, "model": "opus"},
        "done": {},
        "original_prompt": DEFAULT_PROMPT,
        "rewritten_prompt": "%id:!02p\n#gh:sase\nDo the work",
        "force_reuse_plan": dummy_force_plan(),
        "model_override": None,
        "preview": preview,
        "name_reuse_source": "prompt",
        "wipe_preview": dummy_wipe_preview(artifacts_dir),
    }
    fields.update(overrides)
    return AgentRestartPlan(**fields)


def successful_kill(**overrides: Any) -> KillResult:
    fields: dict[str, Any] = {
        "success": True,
        "message": "Killed agent '02p' (PID 481920)",
        "reason": None,
        "status": "killed",
        "pid": 481920,
        "changed": True,
        "artifacts_dir": "/tmp/02p",
        "project": "gh_sase-org__sase",
        "timestamp": "20260818120000",
    }
    fields.update(overrides)
    return KillResult(**fields)


def failed_kill(**overrides: Any) -> KillResult:
    fields: dict[str, Any] = {
        "success": False,
        "message": "Permission denied killing agent '02p' (PID 481920)",
        "reason": "permission_denied",
        "status": "permission_denied",
        "pid": 481920,
        "changed": False,
        "artifacts_dir": "/tmp/02p",
        "project": "gh_sase-org__sase",
        "timestamp": "20260818120000",
    }
    fields.update(overrides)
    return KillResult(**fields)


def dummy_launch_result(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "pid": 492011,
        "workspace_num": 14,
        "workspace_dir": "/tmp/ws",
        "output_path": "/tmp/out",
        "artifacts_dir": "/tmp/new-02p",
        "agent_name": "02p",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def mutation_spies() -> dict[str, MagicMock]:
    """Return mocks that record wipe/kill/launch so tests can prove a no-op."""
    return {
        "kill": MagicMock(side_effect=AssertionError("kill_named_agent was called")),
        "dismiss": MagicMock(
            side_effect=AssertionError("dismiss_named_agent was called")
        ),
        "apply": MagicMock(
            side_effect=AssertionError("apply_force_reuse_launch was called")
        ),
        "launch": MagicMock(
            side_effect=AssertionError("launch_agents_from_cwd was called")
        ),
    }
