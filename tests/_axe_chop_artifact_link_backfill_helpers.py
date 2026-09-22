"""Shared helpers for artifact_link_backfill chop script tests."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

import sase.scripts.sase_chop_artifact_link_backfill as backfill_chop
from sase.axe.chop_script_context import ChopScriptContext
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger
from sase.core.project_lifecycle_wire import ProjectRecordWire


@pytest.fixture(autouse=True)
def _default_no_publication_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        backfill_chop,
        "machine_document_sidecar_roots",
        lambda *_args, **_kwargs: ((), ()),
    )
    monkeypatch.setattr(
        backfill_chop,
        "sweep_artifact_link_publication_retries",
        lambda *_args, **_kwargs: SimpleNamespace(
            attempted=0,
            published=0,
            deferred=0,
            failed=0,
            aged=0,
            discovered=0,
            cleared=0,
            diagnostics=(),
            details=(),
        ),
    )


def _runtime(tmp_path: Path) -> BuiltinChopRuntime:
    return _runtime_with_logs(tmp_path)[0]


def _runtime_with_logs(
    tmp_path: Path,
) -> tuple[BuiltinChopRuntime, StringIO, StringIO]:
    stdout = StringIO()
    stderr = StringIO()
    runtime = BuiltinChopRuntime(
        name="artifact_link_backfill",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="housekeeping",
            state_dir=str(tmp_path / "state"),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
        ),
        log=ChopLogger(stdout=stdout, stderr=stderr),
    )
    return runtime, stdout, stderr


def _project(tmp_path: Path, *, name: str = "proj") -> SimpleNamespace:
    workspace_dir = tmp_path / "projects" / name
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        is_project=True,
        workspace_dir=str(workspace_dir),
        project_name=name,
    )


def _record(
    tmp_path: Path, *, project_name: str, display_name: str | None = None
) -> ProjectRecordWire:
    workspace_dir = tmp_path / "projects" / project_name
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return ProjectRecordWire(
        schema_version=3,
        project_name=project_name,
        project_dir=str(tmp_path / ".sase" / project_name),
        project_file=str(tmp_path / ".sase" / project_name / f"{project_name}.sase"),
        archive_file=None,
        workspace_dir=str(workspace_dir),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
        is_project=True,
        vcs_kind="gh",
    )
