"""Types shared by the ``sase agent restart`` planning and execution modules.

Planning is read-only, so a refusal is an :class:`AgentRestartError` raised
before anything is killed; execution reports every later failure as an
:class:`AgentRestartOutcome` status instead.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.agent.force_reuse_launch import ForceReuseLaunchPlan
from sase.agent.names import AgentNameWipePreview, NamedAgent
from sase.agent.running import KillResult

NameReuseSource = Literal["prompt", "injected"]

ProgressFn = Callable[[str, str, str], None]


class AgentRestartError(Exception):
    """A restart that was refused before any mutation."""

    def __init__(self, *, reason: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.hint = hint


@dataclass(frozen=True)
class AgentRestartPreview:
    """Display facts collected while planning a restart."""

    status: str
    project_display: str
    patch: str | None
    workspace_num: int | None
    pid: int | None
    model: str | None
    provider: str | None
    reasoning_effort: str | None
    model_alias: str | None
    started: str | None
    elapsed: str | None
    family: str | None
    bead: str | None
    prompt_excerpt: str
    target: str
    name_reuse: str
    model_override_label: str | None
    warnings: tuple[str, ...]
    is_live: bool
    has_file_changes: bool


@dataclass(frozen=True)
class AgentRestartPlan:
    """A validated, not-yet-applied named-agent restart."""

    name: str
    lookup_name: str
    presented_name: str
    agent: NamedAgent
    artifacts_dir: Path
    project: str
    meta: dict[str, Any]
    done: dict[str, Any]
    original_prompt: str
    rewritten_prompt: str
    force_reuse_plan: ForceReuseLaunchPlan
    model_override: str | None
    preview: AgentRestartPreview
    name_reuse_source: NameReuseSource
    wipe_preview: AgentNameWipePreview


@dataclass(frozen=True)
class AgentRestartOutcome:
    """Result of applying a restart plan."""

    status: str
    name: str
    stop_action: str
    stop_result: KillResult
    launched_pid: int | None = None
    launched_workspace_num: int | None = None
    launched_artifacts_dir: str | None = None
    error: str | None = None
    recovery_command: str | None = None
    recovery_dir: str | None = None
    recovery_prompt: str | None = None
    renamed_to: str | None = None
