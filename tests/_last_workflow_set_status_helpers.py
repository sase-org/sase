"""Shared helpers for ``tools/last_workflow_set_status`` test modules.

The script has no ``.py`` suffix, so callers load it through
``importlib.machinery.SourceFileLoader``. The underscore prefix on this
module name keeps pytest from collecting it as a test file.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tools" / "last_workflow_set_status"


def load_script() -> types.ModuleType:
    """Load the suffix-less tool script as a module."""
    loader = importlib.machinery.SourceFileLoader(
        "last_workflow_set_status", str(SCRIPT_PATH)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def fake_runner(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    capture: list[list[str]] | None = None,
    env_capture: list[dict[str, str] | None] | None = None,
):
    def _run(argv, env_overrides=None):
        if capture is not None:
            capture.append(list(argv))
        if env_capture is not None:
            env_capture.append(
                dict(env_overrides) if env_overrides is not None else None
            )
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return _run


def make_run(
    script: types.ModuleType,
    *,
    workflow: str,
    sha: str,
    status: str = "completed",
    conclusion: str = "success",
    attempt: int = 1,
    created_at: str = "2026-05-11T12:00:00Z",
    updated_at: str | None = None,
    workflow_id: int | None = None,
    database_id: int | None = None,
    title: str = "",
    url: str = "",
    branch: str = "master",
):
    return script.WorkflowRun(
        database_id=database_id
        if database_id is not None
        else hash((workflow, sha, attempt)) & 0xFFFFFFFF,
        workflow_name=workflow,
        workflow_database_id=workflow_id
        if workflow_id is not None
        else hash(workflow) & 0xFFFF,
        head_sha=sha,
        head_branch=branch,
        status=status,
        conclusion=conclusion,
        created_at=created_at,
        updated_at=updated_at if updated_at is not None else created_at,
        event="push",
        attempt=attempt,
        display_title=title,
        url=url,
    )


class StubClient:
    """In-test replacement for ``GhClient`` that returns canned data."""

    def __init__(
        self,
        *,
        runs: list[Any] | None = None,
        default_branch_value: str = "master",
        raise_on_default_branch: Exception | None = None,
        raise_on_list_runs: Exception | None = None,
        jobs_by_run: dict[int, Any] | None = None,
        check_runs_by_sha: dict[str, Any] | None = None,
        annotations_by_check_run: dict[int, Any] | None = None,
        logs_by_run: dict[int, Any] | None = None,
    ) -> None:
        self._runs = runs or []
        self._default_branch = default_branch_value
        self._raise_default = raise_on_default_branch
        self._raise_list = raise_on_list_runs
        self._jobs_by_run = jobs_by_run or {}
        self._check_runs_by_sha = check_runs_by_sha or {}
        self._annotations_by_check_run = annotations_by_check_run or {}
        self._logs_by_run = logs_by_run or {}
        self.list_runs_calls: list[dict[str, Any]] = []
        self.list_jobs_calls: list[int] = []
        self.list_sha_check_runs_calls: list[str] = []
        self.list_check_run_annotations_calls: list[int] = []
        self.fetch_failed_log_calls: list[int] = []

    def default_branch(self) -> str:
        if self._raise_default is not None:
            raise self._raise_default
        return self._default_branch

    def list_runs(self, *, branch: str, events: Any, limit: int) -> list[Any]:
        if self._raise_list is not None:
            raise self._raise_list
        self.list_runs_calls.append(
            {"branch": branch, "events": tuple(events), "limit": limit}
        )
        return list(self._runs)

    def list_jobs(self, run_id: int) -> list[Any]:
        self.list_jobs_calls.append(run_id)
        value = self._jobs_by_run.get(run_id, [])
        if isinstance(value, Exception):
            raise value
        return list(value)

    def list_sha_check_runs(self, sha: str) -> list[Any]:
        self.list_sha_check_runs_calls.append(sha)
        value = self._check_runs_by_sha.get(sha, [])
        if isinstance(value, Exception):
            raise value
        return list(value)

    def list_check_run_annotations(self, check_run: Any) -> list[Any]:
        self.list_check_run_annotations_calls.append(check_run.check_run_id)
        value = self._annotations_by_check_run.get(check_run.check_run_id, [])
        if isinstance(value, Exception):
            raise value
        return list(value)

    def fetch_failed_log(self, run_id: int) -> str:
        self.fetch_failed_log_calls.append(run_id)
        value = self._logs_by_run.get(run_id, "")
        if isinstance(value, Exception):
            raise value
        return value


def install_stub(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    stub: StubClient,
) -> None:
    def _factory(*_args: Any, **_kwargs: Any) -> StubClient:
        return stub

    monkeypatch.setattr(script, "GhClient", _factory)


def make_job(
    script: types.ModuleType,
    *,
    name: str,
    conclusion: str = "failure",
    status: str = "completed",
    database_id: int = 0,
    url: str = "",
    steps: tuple[Any, ...] = (),
) -> Any:
    return script.Job(
        database_id=database_id or (hash(name) & 0xFFFFFFFF),
        name=name,
        status=status,
        conclusion=conclusion,
        url=url,
        steps=steps,
    )


def make_check_run(
    script: types.ModuleType,
    *,
    name: str,
    check_run_id: int,
    conclusion: str = "failure",
    status: str = "completed",
) -> Any:
    return script.CheckRun(
        check_run_id=check_run_id,
        name=name,
        status=status,
        conclusion=conclusion,
    )


def make_annotation(
    script: types.ModuleType,
    *,
    check_run: Any,
    path: str = "src/example.py",
    start_line: int = 12,
    title: str = "boom",
    message: str = "It exploded.",
) -> Any:
    return script.Annotation(
        check_run_id=check_run.check_run_id,
        check_run_name=check_run.name,
        path=path,
        start_line=start_line,
        end_line=start_line,
        annotation_level="failure",
        title=title,
        message=message,
    )
