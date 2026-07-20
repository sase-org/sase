"""Shared deliberately-mismatched project display regression model."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.project_display_names import ProjectDisplaySnapshot


@dataclass(frozen=True, slots=True)
class ProjectDisplayLayout:
    """Opt-in on-disk layout for one mismatch regression case."""

    projects_root: Path
    project_dir: Path
    project_file: Path
    workspace_dir: Path


@dataclass(frozen=True, slots=True)
class ProjectDisplayCase:
    """Canonical identity and projected labels that can never match by accident."""

    project_key: str = "gh_acme__widgets"
    project_label: str = "widgets"
    changespec_key: str = "gh_acme__widgets_feature"
    changespec_label: str = "widgets_feature"
    parent_key: str = "gh_acme__widgets_parent"
    parent_label: str = "widgets_parent"
    snapshot: ProjectDisplaySnapshot = field(init=False)

    def __post_init__(self) -> None:
        if self.project_key == self.project_label:
            raise ValueError("project display regression case requires key != label")
        if self.changespec_key == self.changespec_label:
            raise ValueError(
                "project display regression case requires ChangeSpec key != label"
            )
        object.__setattr__(
            self,
            "snapshot",
            ProjectDisplaySnapshot({self.project_key: self.project_label}),
        )

    def changespec(self, suffix: str) -> tuple[str, str]:
        """Return canonical and projected ChangeSpec names for *suffix*."""
        return (f"{self.project_key}_{suffix}", f"{self.project_label}_{suffix}")

    def project_record(
        self,
        *,
        projects_root: Path | None = None,
        workspace_dir: Path | None = None,
        state: str = "enabled",
    ) -> ProjectRecordWire:
        """Build a lifecycle record without creating any filesystem entries."""
        root = projects_root or Path("/tmp/projects")
        project_dir = root / self.project_key
        workspace = workspace_dir or Path("/tmp/workspaces") / self.project_key
        return ProjectRecordWire(
            schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
            project_name=self.project_key,
            project_dir=str(project_dir),
            project_file=str(project_dir / f"{self.project_key}.sase"),
            archive_file=None,
            workspace_dir=str(workspace),
            state=state,
            state_explicit=False,
            system_managed=False,
            active_claim_count=0,
            launchable=state == "enabled",
            aliases=[],
            warnings=[],
            parse_warnings=[],
            display_name=self.project_label,
        )

    def write_project_layout(
        self,
        projects_root: Path,
        *,
        workspace_dir: Path | None = None,
        extra_content: str = "",
    ) -> ProjectDisplayLayout:
        """Create an opt-in ProjectSpec/workspace layout for integration tests."""
        workspace = workspace_dir or projects_root.parent / "primary"
        workspace.mkdir(parents=True, exist_ok=True)
        project_dir = projects_root / self.project_key
        project_dir.mkdir(parents=True, exist_ok=True)
        project_file = project_dir / f"{self.project_key}.sase"
        content = (
            f"PROJECT_NAME: {self.project_label}\n"
            f"WORKSPACE_DIR: {workspace}\n"
            f"{extra_content}"
        )
        project_file.write_text(content, encoding="utf-8")
        return ProjectDisplayLayout(
            projects_root=projects_root,
            project_dir=project_dir,
            project_file=project_file,
            workspace_dir=workspace,
        )


__all__ = ["ProjectDisplayCase", "ProjectDisplayLayout"]
