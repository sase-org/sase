"""Textual-free Progress-stage models for the New Project wizard.

This module reduces onboarding NDJSON into checklist rows and a raw-log
tail. Every line goes through :func:`parse_event_line`; unparsable lines
stay in the raw log. This module is the non-test consumer of that parser.
It imports no Textual modules.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from sase.project_onboarding.events import parse_event_line

StepState = Literal["pending", "running", "done", "failed", "skipped"]
ResultStatus = Literal["ok", "partial", "failed", "blocked"]

__all__ = [
    "ProgressResult",
    "ProgressStep",
    "ProgressView",
    "ResultStatus",
    "StepState",
    "reduce_lines",
]


@dataclass
class ProgressStep:
    """One checklist row tracked by step id."""

    step_id: str
    label: str
    state: StepState = "pending"
    message: str = ""
    hint: str = ""


@dataclass(frozen=True, slots=True)
class ProgressResult:
    """Terminal result recorded from a ``result`` event."""

    status: ResultStatus
    project_key: str
    project_name: str
    next_argv: tuple[str, ...]
    message: str


@dataclass
class ProgressView:
    """Mutable NDJSON reducer feeding the Progress widget."""

    steps: dict[str, ProgressStep] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    raw_log: list[str] = field(default_factory=list)
    result: ProgressResult | None = None

    def feed_line(self, line: str) -> None:
        """Reduce one NDJSON log line through :func:`parse_event_line`."""
        event = parse_event_line(line)
        if event is None:
            self.raw_log.append(line.rstrip("\n"))
            return
        self.feed_event(event)

    def feed_event(self, event: Mapping[str, Any]) -> None:
        """Reduce one parsed onboarding event."""
        kind = str(event.get("event") or "")
        if kind == "plan":
            self._seed_from_plan(event.get("plan"))
        elif kind == "step":
            self._apply_step(event)
        elif kind == "result":
            self._apply_result(event)
        else:
            self.raw_log.append(str(event))

    def checklist(self) -> tuple[ProgressStep, ...]:
        """Return checklist rows in first-seen order."""
        return tuple(self.steps[step_id] for step_id in self.order)

    def raw_tail(self, limit: int = 50) -> tuple[str, ...]:
        """Return the last *limit* raw log lines."""
        return tuple(self.raw_log[-limit:])

    def mark_sase_initialized(self) -> None:
        """Append a completed init row after a successful hand-off."""
        row = self._ensure(
            {"id": "sase-init", "label": "SASE initialized"},
            "sase-init",
        )
        row.state = "done"
        row.message = ""
        row.hint = ""

    def _seed_from_plan(self, plan: Any) -> None:
        if not isinstance(plan, Mapping):
            return
        raw_steps = plan.get("steps")
        items = raw_steps if isinstance(raw_steps, list) else []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            step_id = str(item.get("id") or "")
            if not step_id:
                continue
            state = str(item.get("state") or "pending")
            row = self._ensure(item, step_id)
            if state == "skipped":
                row.state = "skipped"
            elif state == "done":
                row.state = "done"
            elif row.state in ("pending", "skipped"):
                row.state = "pending"

    def _ensure(self, item: Mapping[str, Any], step_id: str) -> ProgressStep:
        row = self.steps.get(step_id)
        if row is None:
            row = ProgressStep(
                step_id=step_id,
                label=str(item.get("label") or step_id),
            )
            self.steps[step_id] = row
            self.order.append(step_id)
        elif item.get("label"):
            row.label = str(item.get("label"))
        return row

    def _apply_step(self, event: Mapping[str, Any]) -> None:
        step_id = str(event.get("id") or "")
        if not step_id:
            return
        row = self._ensure(event, step_id)
        status = str(event.get("status") or "")
        if status == "running":
            row.state = "running"
            row.message = ""
            row.hint = ""
        elif status == "done":
            row.state = "done"
            row.message = ""
            row.hint = ""
        elif status == "failed":
            row.state = "failed"
            row.message = str(event.get("message") or "")
            row.hint = str(event.get("hint") or "")
        elif status == "skipped":
            row.state = "skipped"

    def _apply_result(self, event: Mapping[str, Any]) -> None:
        status = str(event.get("status") or "")
        if status not in ("ok", "partial", "failed", "blocked"):
            return
        project = event.get("project")
        project_map = project if isinstance(project, Mapping) else {}
        raw_argv = event.get("next_argv")
        next_argv = (
            tuple(str(item) for item in raw_argv) if isinstance(raw_argv, list) else ()
        )
        self.result = ProgressResult(
            status=status,  # type: ignore[arg-type]
            project_key=str(project_map.get("key") or ""),
            project_name=str(project_map.get("name") or ""),
            next_argv=next_argv,
            message=str(event.get("message") or ""),
        )


def reduce_lines(lines: Iterable[str]) -> ProgressView:
    """Reduce NDJSON *lines* into a :class:`ProgressView`."""
    view = ProgressView()
    for line in lines:
        view.feed_line(line)
    return view
