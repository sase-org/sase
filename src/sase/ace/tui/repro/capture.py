"""Passive Agents-tab repro capture ring buffer."""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .redact import redact_bundle
from .invariants import check_bundle_invariants
from .schema import (
    AgentIdentity,
    ReproAppState,
    ReproAssertions,
    ReproBundle,
    ReproLoadState,
    ReproLoadStep,
    ReproManifest,
    ReproScreen,
    SCHEMA_VERSION,
    identity_to_json,
)
from .serialize import serialize_agent_rows

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..models.agent import Agent, AgentType
    from ..models.agent_loader import AgentLoadState

log = logging.getLogger(__name__)

DEFAULT_CAPTURE_CAPACITY = 120


@dataclass
class _PendingCycle:
    sequence: int
    label: str
    load_state: ReproLoadState
    agent_rows: list[Any]
    metadata: dict[str, Any]
    screen: ReproScreen = field(default_factory=ReproScreen)


class AgentsTabReproCaptureRing:
    """Bounded in-memory capture store for Agents-tab load/apply cycles."""

    def __init__(self, *, capacity: int = DEFAULT_CAPTURE_CAPACITY) -> None:
        self.capacity = max(1, capacity)
        self.repro_id = uuid4().hex[:12]
        self._steps: deque[ReproLoadStep] = deque(maxlen=self.capacity)
        self._pending: _PendingCycle | None = None
        self._sequence = 0

    @property
    def steps(self) -> list[ReproLoadStep]:
        return list(self._steps)

    def record_loader_result(
        self,
        app: Any,
        *,
        load_state: AgentLoadState | None,
        agents: Iterable[Agent],
        dismissed_from_loader: Iterable[Agent],
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        source: str,
    ) -> None:
        self._sequence += 1
        agent_list = list(agents)
        dismissed_list = list(dismissed_from_loader)
        metadata = _collect_common_metadata(app)
        metadata.update(
            {
                "phase": "loader_result",
                "source": source,
                "repro_id": self.repro_id,
                "sequence": self._sequence,
                "on_agents_tab": on_agents_tab,
                "selected_identity_before": _identity_to_json(selected_identity),
                "loaded_row_count": len(agent_list),
                "dismissed_from_loader_count": len(dismissed_list),
                "captured_at_epoch": time.time(),
            }
        )
        self._pending = _PendingCycle(
            sequence=self._sequence,
            label=f"{source} load/apply {self._sequence}",
            load_state=_serialize_load_state(load_state),
            agent_rows=serialize_agent_rows(agent_list),
            metadata=metadata,
        )
        _trace_capture_event("agents.repro.loader_result", self.repro_id, metadata)

    def record_app_projection(
        self,
        app: Any,
        *,
        load_state: AgentLoadState | None,
        source: str,
    ) -> None:
        pending = self._pending
        if pending is None:
            self._sequence += 1
            pending = _PendingCycle(
                sequence=self._sequence,
                label=f"{source} projection {self._sequence}",
                load_state=_serialize_load_state(load_state),
                agent_rows=serialize_agent_rows(
                    getattr(app, "_agents_with_children", [])
                ),
                metadata={
                    **_collect_common_metadata(app),
                    "phase": "app_projection",
                    "source": source,
                    "repro_id": self.repro_id,
                    "sequence": self._sequence,
                },
            )

        metadata = dict(pending.metadata)
        metadata.update(_collect_common_metadata(app))
        metadata.update(
            {
                "phase": "app_projection",
                "source": source,
                "visible_row_count": len(getattr(app, "_agents", [])),
                "unfiltered_row_count": len(getattr(app, "_agents_with_children", [])),
                "selected_identity_after": _identity_to_json(_selected_identity(app)),
                "captured_after_apply_at_epoch": time.time(),
            }
        )
        step = ReproLoadStep(
            step_id=f"capture_{pending.sequence:04d}",
            label=pending.label,
            load_state=pending.load_state,
            agent_rows=pending.agent_rows,
            app_state=_build_app_state(app),
            screen=pending.screen,
            metadata=metadata,
        )
        self._steps.append(step)
        self._pending = None
        _trace_capture_event("agents.repro.app_projection", self.repro_id, metadata)

    def to_bundle(
        self,
        *,
        screen: ReproScreen | None = None,
        commit_safe: bool,
    ) -> ReproBundle:
        steps = list(self._steps)
        if screen is not None and steps:
            last = steps[-1]
            steps[-1] = ReproLoadStep(
                step_id=last.step_id,
                label=last.label,
                load_state=last.load_state,
                agent_rows=last.agent_rows,
                app_state=last.app_state,
                screen=screen,
                metadata=last.metadata,
            )
        bundle = ReproBundle(
            manifest=ReproManifest(
                schema_version=SCHEMA_VERSION,
                name=f"agents-tab-capture-{self.repro_id}",
                created_at=datetime.now(UTC).isoformat(),
                source="in_tui_ring_buffer",
                commit_safe=commit_safe,
                description="Passive Agents-tab load/apply capture.",
            ),
            load_steps=steps,
            assertions=ReproAssertions(),
        )
        if commit_safe:
            bundle = redact_bundle(bundle, commit_safe=True)
        return bundle


def enable_agents_tab_repro_capture(
    app: Any,
    *,
    capacity: int = DEFAULT_CAPTURE_CAPACITY,
) -> AgentsTabReproCaptureRing:
    """Enable passive capture for one app instance."""

    ring = AgentsTabReproCaptureRing(capacity=capacity)
    app._agents_repro_capture = ring
    return ring


def disable_agents_tab_repro_capture(app: Any) -> None:
    app._agents_repro_capture = None


def get_agents_tab_repro_capture(app: Any) -> AgentsTabReproCaptureRing | None:
    ring = getattr(app, "_agents_repro_capture", None)
    return ring if isinstance(ring, AgentsTabReproCaptureRing) else None


def record_agents_tab_loader_result(
    app: Any,
    *,
    load_state: AgentLoadState | None,
    agents: Iterable[Agent],
    dismissed_from_loader: Iterable[Agent],
    on_agents_tab: bool,
    selected_identity: tuple[AgentType, str, str | None] | None,
    source: str,
) -> None:
    """Record a loader result if capture is enabled; never raise."""

    ring = get_agents_tab_repro_capture(app)
    if ring is None:
        return
    try:
        ring.record_loader_result(
            app,
            load_state=load_state,
            agents=agents,
            dismissed_from_loader=dismissed_from_loader,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            source=source,
        )
    except Exception:
        log.debug("agents repro loader capture failed", exc_info=True)


def record_agents_tab_app_projection(
    app: Any,
    *,
    load_state: AgentLoadState | None,
    source: str = "apply",
) -> None:
    """Record the post-apply projection if capture is enabled; never raise."""

    ring = get_agents_tab_repro_capture(app)
    if ring is None:
        return
    try:
        ring.record_app_projection(app, load_state=load_state, source=source)
        maybe_auto_capture_agents_tab_violation(app, ring=ring)
    except Exception:
        log.debug("agents repro projection capture failed", exc_info=True)


def set_agents_tab_repro_auto_check(app: Any, *, enabled: bool) -> None:
    """Enable or disable continuous invariant checks for one app instance."""

    app._agents_repro_auto_check_enabled = enabled
    app._agents_repro_auto_capture_burst_active = False
    app._agents_repro_last_invariant_failures = []
    if enabled and get_agents_tab_repro_capture(app) is None:
        enable_agents_tab_repro_capture(app)


def maybe_auto_capture_agents_tab_violation(
    app: Any,
    *,
    ring: AgentsTabReproCaptureRing,
) -> Path | None:
    """Auto-flush one bundle at the start of each invariant violation burst."""

    if not bool(getattr(app, "_agents_repro_auto_check_enabled", False)):
        return None

    report = check_bundle_invariants(ring.to_bundle(commit_safe=True))
    latest_step_id = ring.steps[-1].step_id if ring.steps else None
    current_failures = [
        failure for failure in report.failures if failure.step_id == latest_step_id
    ]
    if not current_failures:
        app._agents_repro_auto_capture_burst_active = False
        app._agents_repro_last_invariant_failures = []
        return None

    app._agents_repro_last_invariant_failures = current_failures
    if bool(getattr(app, "_agents_repro_auto_capture_burst_active", False)):
        return None

    bundle_path = capture_agents_tab_repro_bundle_to_default_dir(
        app,
        reason="auto",
        commit_safe=True,
    )
    app._agents_repro_auto_capture_burst_active = True
    notify = getattr(app, "_notify_agents_repro_auto_capture", None)
    if callable(notify):
        notify(bundle_path)
    return bundle_path


def capture_agents_tab_repro_bundle(
    app: Any,
    output_dir: str | Path,
    *,
    commit_safe: bool = True,
) -> Path:
    """Flush the current ring buffer to ``output_dir`` and return bundle path."""

    ring = get_agents_tab_repro_capture(app)
    if ring is None:
        ring = enable_agents_tab_repro_capture(app)
        ring.record_app_projection(
            app,
            load_state=getattr(app, "_agent_load_state", None),
            source="manual_flush",
        )

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    screen = _capture_screen(app, output)
    bundle = ring.to_bundle(screen=screen, commit_safe=commit_safe)
    bundle_path = output / "agents_tab_repro.json"
    bundle_path.write_text(
        json.dumps(bundle.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _trace_capture_event(
        "agents.repro.bundle_written",
        ring.repro_id,
        {"path": str(bundle_path), "steps": len(bundle.load_steps)},
    )
    return bundle_path


def capture_agents_tab_repro_bundle_to_default_dir(
    app: Any,
    *,
    reason: str,
    commit_safe: bool = True,
) -> Path:
    """Capture into the configured repro base dir using a unique bundle id."""

    ring = get_agents_tab_repro_capture(app)
    repro_id = getattr(ring, "repro_id", uuid4().hex[:12])
    capture_id = uuid4().hex[:6]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        _resolve_agents_repro_base_dir(app)
        / f"{timestamp}-{_safe_reason(reason)}-{repro_id}-{capture_id}"
    )
    return capture_agents_tab_repro_bundle(
        app,
        output_dir,
        commit_safe=commit_safe,
    )


def _resolve_agents_repro_base_dir(app: Any) -> Path:
    configured = str(getattr(app, "_agents_repro_output_dir", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    env_base = os.environ.get("SASE_HOME")
    if env_base:
        return Path(env_base).expanduser() / "repros"
    return Path.home() / ".sase" / "repros"


def _safe_reason(reason: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in reason)
    return cleaned.strip("-") or "capture"


def _serialize_load_state(load_state: AgentLoadState | None) -> ReproLoadState:
    if load_state is None:
        return ReproLoadState(
            tier="tier2",
            complete_history=True,
            artifact_source="source_scan",
            used_artifact_index=False,
        )
    return ReproLoadState(
        tier=load_state.tier,
        complete_history=load_state.complete_history,
        artifact_source=load_state.artifact_source,
        used_artifact_index=load_state.used_artifact_index,
        index_error=load_state.index_error,
        full_history=load_state.full_history,
        agent_search_active=load_state.agent_search_active,
        snapshot_records=load_state.snapshot_records,
        loaded_agent_count=load_state.loaded_agent_count,
        loaded_workflow_step_count=load_state.loaded_workflow_step_count,
        artifact_dirs_visited=load_state.artifact_dirs_visited,
        marker_files_parsed=load_state.marker_files_parsed,
        prompt_step_markers_parsed=load_state.prompt_step_markers_parsed,
        index_missing=load_state.index_missing,
    )


def _build_app_state(app: Any) -> ReproAppState:
    return ReproAppState(
        visible_identities=[
            _schema_identity(agent.identity) for agent in getattr(app, "_agents", [])
        ],
        selected_identity=_selected_identity(app),
        dismissed_identities=[
            _schema_identity(identity)
            for identity in sorted(
                getattr(app, "_dismissed_agents", set()),
                key=lambda item: (str(item[1]), str(item[2]), str(item[0])),
            )
        ],
        flattened_parent_timestamps=[],
        agents_seen_complete_history=bool(
            getattr(app, "_agents_seen_complete_history", False)
        ),
    )


def _collect_common_metadata(app: Any) -> dict[str, Any]:
    fold_manager = getattr(app, "_fold_manager", None)
    fold_states = getattr(fold_manager, "_states", {})
    group_registry = getattr(app, "_group_fold_registry", None)
    query = getattr(app, "_agent_search_query", "") or ""
    return {
        "current_tab": getattr(app, "current_tab", None),
        "current_idx": getattr(app, "current_idx", None),
        "agents_seen_complete_history": bool(
            getattr(app, "_agents_seen_complete_history", False)
        ),
        "agents_refresh_pending": bool(getattr(app, "_agents_refresh_pending", False)),
        "agents_refresh_pending_full_history": bool(
            getattr(app, "_agents_refresh_pending_full_history", False)
        ),
        "agents_refresh_scheduled": bool(
            getattr(app, "_agents_refresh_scheduled", False)
        ),
        "agents_refresh_scheduled_full_history": bool(
            getattr(app, "_agents_refresh_scheduled_full_history", False)
        ),
        "hide_non_run_agents": bool(getattr(app, "hide_non_run_agents", False)),
        "hidden_count": int(getattr(app, "_hidden_count", 0) or 0),
        "grouping_mode": str(getattr(app, "_grouping_mode", "")),
        "group_fold_collapsed": [
            list(key) for key in sorted(getattr(group_registry, "collapsed", set()))
        ],
        "group_fold_version": getattr(group_registry, "version", 0),
        "workflow_fold_states": {
            str(key): getattr(value, "value", str(value))
            for key, value in sorted(fold_states.items())
        },
        "agent_search_query_active": bool(query),
        "agent_search_query_length": len(query),
    }


def _capture_screen(app: Any, output_dir: Path) -> ReproScreen:
    text = ""
    svg_path: str | None = None
    try:
        size = getattr(app, "size", None)
        height = int(getattr(size, "height", 0) or 0)
        if height and getattr(app, "screen", None) is not None:
            text = "\n".join(app.screen.render_line(y).text for y in range(height))
    except Exception:
        log.debug("agents repro screen text capture failed", exc_info=True)

    try:
        export_screenshot = getattr(app, "export_screenshot", None)
        if callable(export_screenshot):
            svg = export_screenshot(title="agents-tab-repro", simplify=True)
            svg_file = output_dir / "screen.svg"
            svg_file.write_text(svg, encoding="utf-8")
            svg_path = svg_file.name
    except Exception:
        log.debug("agents repro SVG capture failed", exc_info=True)
    return ReproScreen(text=text, svg_path=svg_path)


def _selected_identity(app: Any) -> AgentIdentity | None:
    agents = getattr(app, "_agents", [])
    current_idx = int(getattr(app, "current_idx", 0) or 0)
    if getattr(app, "current_tab", None) == "agents":
        if 0 <= current_idx < len(agents):
            return _schema_identity(agents[current_idx].identity)
        return None
    identity = getattr(app, "_agents_last_identity", None)
    return None if identity is None else _schema_identity(identity)


def _schema_identity(identity: tuple[Any, str, str | None]) -> AgentIdentity:
    agent_type = identity[0]
    value = getattr(agent_type, "value", agent_type)
    if value not in ("run", "workflow"):
        value = str(value)
    return (value, identity[1], identity[2])  # type: ignore[return-value]


def _identity_to_json(
    identity: tuple[Any, str, str | None] | None,
) -> list[str | None] | None:
    if identity is None:
        return None
    return identity_to_json(_schema_identity(identity))


def _trace_capture_event(event: str, repro_id: str, fields: dict[str, Any]) -> None:
    try:
        from ..util.trace import trace_event

        trace_event(event, repro_id=repro_id, **fields)
    except Exception:
        log.debug("agents repro trace event failed", exc_info=True)
