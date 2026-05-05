"""Artifacts panel launch actions for the ace TUI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.core.artifact_wire import ARTIFACT_ROOT_ID

if TYPE_CHECKING:
    from ...changespec import ChangeSpec
    from ..models import Agent

TabName = Literal["changespecs", "agents", "axe"]


def _agent_artifact_id(agent: Agent) -> str | None:
    """Return the unified graph artifact ID for a TUI agent row."""
    if agent.agent_name:
        return agent.agent_name

    artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
    if artifacts_dir:
        path = Path(artifacts_dir).expanduser()
        if path.name and path.parent.name and path.parent.parent.name == "artifacts":
            project = path.parent.parent.parent.name
            return f"agent:{project}:{path.parent.name}:{path.name}"

    project = (
        Path(agent.project_file).expanduser().parent.name if agent.project_file else ""
    )
    workflow = agent.workflow or agent.parent_workflow or "ace-run"
    timestamp = agent.extract_artifacts_timestamp() or agent.raw_suffix
    if project and workflow and timestamp:
        return f"agent:{project}:{workflow}:{timestamp}"
    return None


class ArtifactsMixin:
    """Mixin that opens the unified artifacts modal from the current tab."""

    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    _agents: list[Agent]

    def _artifact_panel_start_id(self) -> str | None:
        """Resolve the starting artifact ID for the current ace tab."""
        if self.current_tab == "axe":
            return ARTIFACT_ROOT_ID

        if self.current_tab == "changespecs":
            if not self.changespecs:
                return None
            if not 0 <= self.current_idx < len(self.changespecs):
                return None
            return self.changespecs[self.current_idx].name

        if self.current_tab == "agents":
            agents = getattr(self, "_agents", [])
            if not 0 <= self.current_idx < len(agents):
                return None
            return _agent_artifact_id(agents[self.current_idx])

        return None

    def _artifact_panel_context(self) -> tuple[Path | None, Path | None]:
        """Return source context for a targeted graph refresh on panel open."""
        if self.current_tab == "changespecs":
            if not self.changespecs:
                return None, None
            if not 0 <= self.current_idx < len(self.changespecs):
                return None, None
            file_path = getattr(self.changespecs[self.current_idx], "file_path", None)
            if isinstance(file_path, str | Path) and file_path:
                return Path(file_path).expanduser(), None
            return None, None

        if self.current_tab == "agents":
            agents = getattr(self, "_agents", [])
            if not 0 <= self.current_idx < len(agents):
                return None, None
            agent = agents[self.current_idx]
            artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
            return None, Path(artifacts_dir).expanduser() if artifacts_dir else None

        return None, None

    def action_open_artifacts_panel(self) -> None:
        """Open the unified artifacts modal from the current tab context."""
        artifact_id = self._artifact_panel_start_id()
        if artifact_id is None:
            notify = getattr(self, "notify", None)
            if callable(notify):
                notify(
                    "No artifact context for the current selection", severity="warning"
                )
            return

        from ..modals import ArtifactPanelModal

        context_path, artifact_dir = self._artifact_panel_context()
        self.push_screen(  # type: ignore[attr-defined]
            ArtifactPanelModal(
                artifact_id=artifact_id,
                context_path=context_path,
                artifact_dir=artifact_dir,
            )
        )
