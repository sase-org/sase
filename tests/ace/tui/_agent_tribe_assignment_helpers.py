"""Shared helpers for agent tribe assignment tests."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.agents._tribe_assignment import AgentTribeAssignmentMixin
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.proc_observer import ObservedProc as ProcInfo


def _make_agent(suffix: str = "20240101120000", **overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "fix-bug",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "RUNNING",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": suffix,
        "pid": 4242,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _FakeApp(AgentTribeAssignmentMixin, AgentDisplayMixin):
    """Minimal stub of AceApp for exercising AgentTribeAssignmentMixin."""

    def __init__(self, agents: list[Agent]) -> None:
        self.current_tab: Any = "agents"  # type: ignore[assignment]
        self.current_idx = 0
        self._agents: list[Agent] = list(agents)
        self._agents_with_children: list[Agent] = list(agents)
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self.refresh_calls = 0
        self.events: list[str] = []
        self._agent_panel_index_cache: tuple[Any, Any] | None = ("agents", "index")
        self._panel_keys_cache: tuple[Any, ...] | None = ("agents", "keys")
        self._nav_stops_cache: tuple[Any, ...] | None = ("agents", "stops")

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def notify(
        self, message: str, *, severity: str = "information"
    ) -> None:  # pragma: no cover - trivial
        self.notifications.append((message, severity))

    def push_screen(
        self, modal: Any, callback: Any = None
    ) -> None:  # pragma: no cover - trivial
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _refresh_agents_display(
        self, *, list_changed: bool = False
    ) -> None:  # pragma: no cover - trivial
        self.refresh_calls += 1
        self.events.append(f"refresh:{list_changed}")

    def _invalidate_agent_panel_cache(self) -> None:
        super()._invalidate_agent_panel_cache()
        self.events.append("invalidate")

    def _submit_durable_proc(
        self,
        argv: Any,
        *,
        operation: str = "",
        request: Any = None,
        request_fingerprint: str = "",
        concurrency_keys: Any = (),
        proc_type: str | None = None,
        display_name: str | None = None,
        cl_name: str = "",
        project_file: str = "",
        duplicate_message: str | None = None,
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
        **kwargs: Any,
    ) -> ProcInfo:
        del argv, operation, request_fingerprint, concurrency_keys
        del duplicate_message, reload_on_complete, notify_on_complete, kwargs
        from sase.ops.commands.agent import _persist_directive_from_payload

        proc_info = ProcInfo(
            proc_id=f"task-{len(self.events)}",
            proc_type=proc_type or "agent-directive",
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="running",
            started_at=datetime.now(),
            display_name=display_name,
        )
        try:
            payload = dict(request or {})
            updates = payload.get("updates")
            if isinstance(updates, list):
                for item in updates:
                    if isinstance(item, dict):
                        _persist_directive_from_payload(
                            item,
                            artifacts_dir=str(
                                item.get("artifacts_dir") or project_file
                            ),
                        )
            else:
                _persist_directive_from_payload(
                    payload,
                    artifacts_dir=str(payload.get("artifacts_dir") or project_file),
                )
            result = TrackedProcResult(success=True, message="ok")
        except Exception as exc:
            result = TrackedProcResult(
                success=False,
                message=str(exc),
                error=str(exc),
            )
        proc_info.status = "success" if result.success else "error"
        proc_info.message = result.message
        proc_info.error = result.error
        if on_complete is not None:
            on_complete(
                TrackedProcCompletion(
                    proc_info=proc_info,
                    success=result.success,
                    message=result.message,
                    output="",
                    payload=result.payload,
                    error=result.error,
                )
            )
        return proc_info


def _make_clan_member(
    artifacts_dir: Path,
    *,
    clan: str = "research",
    generation: str = "g1",
    clan_tribe: str | None = "old",
    prompt: str | None = None,
    name: str = "research.lead",
) -> Agent:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "raw_xprompt.md").write_text(
        prompt
        or (
            "%id:research.lead\n"
            "%clan(research, tribe=old, summary_script=sase_clan_summary_epic)\n"
            "Lead"
        ),
        encoding="utf-8",
    )
    meta: dict[str, Any] = {
        "name": name,
        "agent_clan": clan,
        "agent_clan_generation": generation,
    }
    if clan_tribe is not None:
        meta["clan_tribe"] = clan_tribe
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return _make_agent(
        artifacts_dir=str(artifacts_dir),
        agent_name=name,
        agent_clan=clan,
        agent_clan_generation=generation,
        clan_tribe=clan_tribe,
    )


def _make_clan_container(
    *,
    clan: str = "research",
    generation: str = "g1",
    clan_tribe: str | None = "old",
) -> Agent:
    return _make_agent(
        artifacts_dir=None,
        raw_suffix=None,
        agent_name=None,
        agent_clan=clan,
        agent_clan_generation=generation,
        clan_tribe=clan_tribe,
        is_clan_container=True,
    )
