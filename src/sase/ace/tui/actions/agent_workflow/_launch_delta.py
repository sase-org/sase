"""Launch-result to Agents-tab artifact-delta bridge."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult


def _artifact_dir_from_output_path(output_path: str) -> Path | None:
    """Recover an artifact timestamp dir when an output path already points at it."""
    if not output_path:
        return None
    path = Path(output_path).expanduser()
    candidates = [path, path.parent]
    from sase.core.agent_artifact_paths import parse_agent_artifact_path

    for candidate in candidates:
        if parse_agent_artifact_path(candidate) is not None:
            return candidate
        parts = candidate.parts
        if (
            len(parts) >= 4
            and parts[-1].isdigit()
            and len(parts[-1]) == 14
            and parts[-3] == "artifacts"
        ):
            return candidate
    return None


def artifact_dir_from_launch_result(result: AgentLaunchResult) -> Path | None:
    """Return the exact artifact directory created by a launch result."""
    project_name = result.project_name
    if not project_name and result.project_file:
        project_name = Path(result.project_file).expanduser().parent.name
    if project_name and result.timestamp:
        from sase.artifacts import convert_timestamp_to_artifacts_format
        from sase.core.agent_artifact_paths import canonical_agent_artifact_path

        return canonical_agent_artifact_path(
            project_name,
            "ace-run",
            convert_timestamp_to_artifacts_format(result.timestamp),
        )
    return _artifact_dir_from_output_path(result.output_path)


class LaunchDeltaMixin:
    """Mixin converting successful launches into exact Agents-tab deltas."""

    def _handle_launch_results_delta(
        self,
        results: Sequence[AgentLaunchResult | None],
        *,
        source: str = "launch",
    ) -> None:
        """Schedule a bounded reconcile for newly launched agent artifacts."""
        present_results = [result for result in results if result is not None]
        if len(present_results) != len(results) or not present_results:
            self._fallback_launch_refresh("missing_launch_result", source=source)
            return

        artifact_dirs: list[Path] = []
        for result in present_results:
            artifact_dir = artifact_dir_from_launch_result(result)
            if artifact_dir is None:
                self._fallback_launch_refresh("missing_artifact_dir", source=source)
                return
            artifact_dirs.append(artifact_dir)

        schedule_delta = getattr(self, "_schedule_agent_artifact_delta_refresh", None)
        if callable(schedule_delta):
            schedule_delta(artifact_dirs, source=source)
            return
        self._fallback_launch_refresh("delta_read_failure", source=source)

    def _fallback_launch_refresh(self, reason: str, *, source: str = "launch") -> None:
        """Record a launch-delta fallback and schedule the broad refresh path."""
        try:
            from ..agents._refresh_trace import record_agents_refresh_trace

            record_agents_refresh_trace(
                self,
                stage="fallback",
                source=source,
                data_cost="tier1_broad_load",
                fallback_reason=reason,
            )
        except Exception:
            pass

        schedule_refresh = getattr(self, "_schedule_agents_async_refresh", None)
        if callable(schedule_refresh):
            schedule_refresh(source=source)
            return
        request_refresh = getattr(self, "request_agents_refresh", None)
        if callable(request_refresh):
            request_refresh(source)


__all__ = [
    "LaunchDeltaMixin",
    "artifact_dir_from_launch_result",
]
