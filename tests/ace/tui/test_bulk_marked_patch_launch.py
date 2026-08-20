"""Durable fan-out for marked-Patch bulk launch (sase-p6)."""

from __future__ import annotations

import os
from typing import Any

import pytest

from sase.ace.patch import Patch
from tests.ace.tui._agent_launch_helpers import _FakeApp


def _patch(*, name: str, file_path: str) -> Patch:
    return Patch(
        name=name,
        description="d",
        parent=None,
        status="WIP",
        file_path=file_path,
        line_number=1,
    )


class _BulkApp(_FakeApp):
    def __init__(self) -> None:
        super().__init__()
        self._artifacts_marked_targets: dict[str, set[str]] = {
            "patches": {"alpha", "beta"}
        }
        self.refresh_calls = 0
        self._reject_cl: str | None = None

    def _refresh_display(self) -> None:
        self.refresh_calls += 1

    def _submit_launch_proc(self, **kwargs: Any) -> bool:
        if self._reject_cl and kwargs.get("cl_name") == self._reject_cl:
            return False
        return super()._submit_launch_proc(**kwargs)


def _patch_bulk_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    missing: str | None = None,
) -> None:
    real_isfile = os.path.isfile

    def fake_isfile(path: object) -> bool:
        path_s = str(path)
        if missing is not None and path_s == missing:
            return False
        if path_s.endswith(".sase"):
            return True
        return real_isfile(path)

    monkeypatch.setattr(os.path, "isfile", fake_isfile)
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda _project_file: "gh",
    )
    monkeypatch.setattr(
        "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
        lambda count: [f"ts-{i}" for i in range(count)],
    )


def test_marked_patch_submit_fans_out_one_launch_per_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_bulk_dependencies(monkeypatch)
    app = _BulkApp()
    app._bulk_patches = [
        _patch(name="alpha", file_path="/tmp/proj/alpha.sase"),
        _patch(name="beta", file_path="/tmp/proj/beta.sase"),
    ]

    app._launch_resolved_prompt("shared prompt")

    assert app._bulk_patches is None
    assert app._artifacts_marked_targets["patches"] == set()
    assert app.refresh_calls == 1
    assert [task["cl_name"] for task in app.launch_tasks] == ["alpha", "beta"]
    assert [task["prompt"] for task in app.launch_tasks] == [
        "#gh:alpha shared prompt",
        "#gh:beta shared prompt",
    ]
    assert [task["dedup_key"] for task in app.launch_tasks] == [
        "launch:ace(run)-ts-0",
        "launch:ace(run)-ts-1",
    ]
    assert ("Launching 2 agent(s)...", None) in app.notifications


def test_marked_patch_submit_reports_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_bulk_dependencies(monkeypatch)
    app = _BulkApp()
    app._bulk_patches = [
        _patch(name="alpha", file_path="/tmp/proj/alpha.sase"),
        _patch(name="gone", file_path=""),
        _patch(name="beta", file_path="/tmp/proj/beta.sase"),
    ]

    app._launch_resolved_prompt("shared prompt")

    assert [task["cl_name"] for task in app.launch_tasks] == ["alpha", "beta"]
    assert (
        "Started 2 agent(s), 1 failed",
        "warning",
    ) in app.notifications


def test_marked_patch_submit_counts_rejected_durable_proc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_bulk_dependencies(monkeypatch)
    app = _BulkApp()
    app._reject_cl = "beta"
    app._bulk_patches = [
        _patch(name="alpha", file_path="/tmp/proj/alpha.sase"),
        _patch(name="beta", file_path="/tmp/proj/beta.sase"),
    ]

    app._launch_resolved_prompt("shared prompt")

    assert [task["cl_name"] for task in app.launch_tasks] == ["alpha"]
    assert (
        "Started 1 agent(s), 1 failed",
        "warning",
    ) in app.notifications
