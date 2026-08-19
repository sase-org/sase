"""Shared helpers for ``sase project`` handler tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
    normalize_project_lifecycle_state,
    normalize_project_lifecycle_state_filter,
)
from sase import project_aliases
from sase.main import project_handler_lifecycle
from sase.running_field._model import WorkspaceClaim


def _write_project(projects_root: Path, name: str, content: str) -> Path:
    project_dir = projects_root / name
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / f"{name}.sase"
    project_file.write_text(content, encoding="utf-8")
    return project_file


def _fake_apply_project_lifecycle_update(content: str, state: str) -> str:
    lines = content.splitlines(keepends=True)
    state_line = f"PROJECT_STATE: {normalize_project_lifecycle_state(state)}\n"
    for index, line in enumerate(lines):
        if line.startswith("PROJECT_STATE:"):
            lines[index] = state_line
            return "".join(lines)

    insert_index = len(lines)
    for index, line in enumerate(lines):
        if line.startswith(("RUNNING:", "NAME:")):
            insert_index = index
            break
    lines.insert(insert_index, state_line)
    return "".join(lines)


def _fake_apply_project_aliases_update(content: str, aliases: list[str]) -> str:
    lines = content.splitlines(keepends=True)
    normalized = sorted({alias.strip() for alias in aliases if alias.strip()})
    for index, line in enumerate(lines):
        if line.startswith("PROJECT_ALIASES:"):
            if normalized:
                lines[index] = f"PROJECT_ALIASES: {', '.join(normalized)}\n"
            else:
                del lines[index]
            return "".join(lines)

    if not normalized:
        return content

    insert_index = len(lines)
    for index, line in enumerate(lines):
        if line.startswith(("RUNNING:", "NAME:")):
            insert_index = index
            break
    lines.insert(insert_index, f"PROJECT_ALIASES: {', '.join(normalized)}\n")
    return "".join(lines)


def _fake_apply_project_name_update(content: str, name: str | None) -> str:
    lines = content.splitlines(keepends=True)
    normalized = (name or "").strip()
    for index, line in enumerate(lines):
        if line.startswith("PROJECT_NAME:"):
            if normalized:
                lines[index] = f"PROJECT_NAME: {normalized}\n"
            else:
                del lines[index]
            return "".join(lines)

    if not normalized:
        return content

    insert_index = len(lines)
    for index, line in enumerate(lines):
        if line.startswith(("RUNNING:", "NAME:")):
            insert_index = index
            break
    lines.insert(insert_index, f"PROJECT_NAME: {normalized}\n")
    return "".join(lines)


def _fake_list_workspace_claims_from_content(content: str) -> list[WorkspaceClaim]:
    claims: list[WorkspaceClaim] = []
    for line in content.splitlines():
        claim = WorkspaceClaim.from_line(line)
        if claim is not None:
            claims.append(claim)
    return claims


def _parse_header(
    content: str,
) -> tuple[str, bool, str | None, list[str], str | None, int]:
    state = "enabled"
    explicit = False
    workspace_dir: str | None = None
    aliases: list[str] = []
    display_name: str | None = None
    active_claim_count = 0
    before_patch = True
    in_running = False
    for line in content.splitlines():
        if line.startswith("NAME:"):
            before_patch = False
            in_running = False
        if not before_patch:
            continue
        if line.startswith("PROJECT_STATE:"):
            raw_state = line.split(":", 1)[1].strip() or "enabled"
            state = normalize_project_lifecycle_state(raw_state)
            explicit = True
        elif line.startswith("WORKSPACE_DIR:"):
            workspace_dir = line.split(":", 1)[1].strip() or None
        elif line.startswith("PROJECT_ALIASES:"):
            aliases = sorted(
                {
                    alias.strip()
                    for alias in line.split(":", 1)[1].split(",")
                    if alias.strip()
                }
            )
        elif line.startswith("PROJECT_NAME:"):
            display_name = line.split(":", 1)[1].strip() or None
        elif line.startswith("RUNNING:"):
            in_running = True
        elif in_running and WorkspaceClaim.from_line(line) is not None:
            active_claim_count += 1
        elif in_running and line and not line.startswith(" "):
            in_running = False
    return state, explicit, workspace_dir, aliases, display_name, active_claim_count


def _disk_project_records(
    root: str | Path,
    include_states: list[str] | str,
    include_home: bool = False,
) -> list[ProjectRecordWire]:
    projects_root = Path(root)
    state_set = set(normalize_project_lifecycle_state_filter(include_states))
    records: list[ProjectRecordWire] = []
    if not projects_root.is_dir():
        return records

    for project_dir in sorted(projects_root.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        if project_name == "home" and not include_home:
            continue
        project_file = project_dir / f"{project_name}.sase"
        if not project_file.is_file():
            continue
        content = project_file.read_text(encoding="utf-8")
        (
            state,
            explicit,
            workspace_dir,
            aliases,
            display_name,
            active_claim_count,
        ) = _parse_header(content)
        if state not in state_set:
            continue
        archive_file = project_dir / f"{project_name}-archive.sase"
        records.append(
            ProjectRecordWire(
                schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
                project_name=project_name,
                project_dir=str(project_dir),
                project_file=str(project_file),
                archive_file=str(archive_file) if archive_file.exists() else None,
                workspace_dir=workspace_dir,
                state=state,
                state_explicit=explicit,
                system_managed=project_name == "home",
                active_claim_count=active_claim_count,
                launchable=state == "enabled" and workspace_dir is not None,
                aliases=aliases,
                warnings=[],
                parse_warnings=[],
                display_name=display_name,
                is_project=project_name != "home" and state != "sibling",
            )
        )
    return records


@pytest.fixture
def projects_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    projects = sase_home / "projects"
    projects.mkdir(parents=True)
    return projects


@pytest.fixture
def lifecycle_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[], None]:
    def install() -> None:
        monkeypatch.setattr(
            project_handler_lifecycle,
            "list_project_records",
            _disk_project_records,
        )
        monkeypatch.setattr(
            project_handler_lifecycle,
            "apply_project_lifecycle_update",
            _fake_apply_project_lifecycle_update,
        )
        monkeypatch.setattr(
            project_aliases,
            "list_project_records",
            _disk_project_records,
        )
        monkeypatch.setattr(
            project_aliases,
            "apply_project_aliases_update",
            _fake_apply_project_aliases_update,
        )
        monkeypatch.setattr(
            project_aliases,
            "apply_project_name_update",
            _fake_apply_project_name_update,
        )
        monkeypatch.setattr(
            project_handler_lifecycle,
            "list_workspace_claims_from_content",
            _fake_list_workspace_claims_from_content,
        )

    return install
