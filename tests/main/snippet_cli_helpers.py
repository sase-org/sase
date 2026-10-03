"""Shared fixtures for ``sase snippet`` CLI handler tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.content_layout import resolve_project_config_write_path
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.macro import glossary_catalog as catalog_mod
from sase.macro.models import Macro

_SORTED_SNIPPETS = """# keep this comment
timezone: UTC
ace:
  snippets:
    greet: |-
      Hello $1!$0
    wrap: |-
      #[greet]$0
"""


def project_record(
    workspace: Path, *, display_name: str = "demo", key: str = "gh_demo__app"
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=key,
        project_dir=f"/tmp/projects/{key}",
        project_file=f"/tmp/projects/{key}/{key}.sase",
        archive_file=None,
        workspace_dir=str(workspace),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=["demo"],
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
    )


def install_writable_snippet_project(
    tmp_path: Path,
    monkeypatch: Any,
    body: str | None = _SORTED_SNIPPETS,
    *,
    display_name: str = "demo",
    macros: dict[str, Macro] | None = None,
) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    config_path = resolve_project_config_write_path(workspace)
    if body is not None:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(
        catalog_mod,
        "list_project_records",
        lambda *_a, **_kw: [project_record(workspace, display_name=display_name)],
    )
    monkeypatch.setattr(
        "sase.macro.loader.get_all_macros",
        lambda project=None: dict(macros or {}),
    )
    return config_path
