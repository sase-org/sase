"""Progress-event tests for the dev-update backends.

Uses a recording :class:`UpdateProgress` fake to assert event order,
statuses, and details for planning and root merging, plus the pure
progress title and detail formatters. Execution and reconciliation
progress tests live in ``test_progress_execute.py``.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from sase.dev_update.models import (
    DevCommandResult,
    DevExecutedCommand,
    DevReconcileStep,
)
from sase.dev_update.plan import plan_dev_update
import sase.dev_update._plan_roots as plan_mod
from sase.dev_update.progress import (
    format_merge_detail,
    reconcile_step_title,
    root_display_names,
)
from sase.dev_update.roots import merge_actionable_roots
from sase.main.update_handler_support import call_plan_dev_update
from sase.version._git import GitUpstreamStatus
from sase.version._models import (
    GitProbeResult,
    GitVersionMetadata,
    VersionPackageRecord,
)
from tests.dev_update._execute_helpers import root
from tests.dev_update._progress_helpers import RecordingProgress, StreamingRunner


def _record(
    name: str,
    *,
    role: str,
    source_root: str | None,
) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role=role,  # type: ignore[arg-type]
        display_version="0.5.0+1.gaaaaaaaaa",
        distribution_version="0.5.0",
        source_version="0.5.0",
        import_module=None,
        import_path=None,
        code_directory=None,
        source_root=source_root,
        distribution_location=None,
        install_type="editable",  # type: ignore[arg-type]
        git=None,
    )


def _status(
    root: str,
    *,
    dirty: bool = False,
    behind: int | None = 2,
) -> GitUpstreamStatus:
    return GitUpstreamStatus(
        root=root,
        upstream="origin/main",
        remote="origin",
        remote_branch="main",
        detached=False,
        dirty=dirty,
        ahead=0,
        behind=behind,
    )


def _probe(_root: Path, _ref: str = "HEAD") -> GitProbeResult:
    return GitProbeResult(
        GitVersionMetadata(
            root="/repo",
            commit="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            short_commit="bbbbbbbbb",
            tag="v0.5.0",
            distance=4,
            dirty=False,
        )
    )


def test_plan_emits_check_timeline_with_per_root_children(
    monkeypatch,
) -> None:
    host = _record("sase", role="host", source_root="/repo/behind")
    plugin = _record("sase-github", role="plugin", source_root="/repo/current")
    statuses = {
        "/repo/behind": _status("/repo/behind", behind=3),
        "/repo/current": _status("/repo/current", behind=0),
    }
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda root: statuses[str(root)]
    )
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", lambda _status: None)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)
    progress = RecordingProgress()

    dev_plan = plan_dev_update([host, plugin], host_record=host, progress=progress)

    assert dev_plan.roots[0].status == "actionable"
    assert progress.events[0] == (
        "declare",
        (
            ("check", "Check for updates", None),
            ("check:/repo/behind", "behind", "check"),
            ("check:/repo/current", "current", "check"),
        ),
    )
    assert ("start", "check", None, None) in progress.events
    assert progress.finishes("check:/repo/behind") == [
        ("finish", "check:/repo/behind", "done", "behind 3 · origin/main")
    ]
    assert progress.finishes("check:/repo/current") == [
        ("finish", "check:/repo/current", "done", "current")
    ]
    assert progress.finishes("check") == [
        ("finish", "check", "done", "1 behind · 1 current")
    ]


def test_plan_marks_dirty_and_fetch_failed_children(
    monkeypatch,
) -> None:
    dirty = _record("sase", role="host", source_root="/repo/dirty")
    offline = _record("sase-core", role="core", source_root="/repo/offline")
    statuses = {
        "/repo/dirty": _status("/repo/dirty", dirty=True),
        "/repo/offline": _status("/repo/offline", behind=0),
    }

    def fail_fetch(_status: GitUpstreamStatus) -> None:
        raise subprocess.CalledProcessError(1, ["git"], stderr="network down")

    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda root: statuses[str(root)]
    )
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", fail_fetch)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)
    progress = RecordingProgress()

    plan_dev_update([dirty, offline], host_record=dirty, progress=progress)

    assert progress.finishes("check:/repo/dirty") == [
        ("finish", "check:/repo/dirty", "warned", "fetch failed; using cached ref")
    ]
    assert progress.finishes("check:/repo/offline") == [
        ("finish", "check:/repo/offline", "warned", "fetch failed; using cached ref")
    ]
    assert progress.finishes("check") == [("finish", "check", "warned", "2 skipped")]


def test_plan_skipped_dirty_reason_without_fetch_error(monkeypatch) -> None:
    dirty = _record("sase", role="host", source_root="/repo/dirty")
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda root: _status(str(root), dirty=True)
    )
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", lambda _status: None)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)
    progress = RecordingProgress()

    dev_plan = plan_dev_update([dirty], host_record=dirty, progress=progress)

    assert dev_plan.roots[0].reason == "checkout has local changes"
    assert progress.finishes("check:/repo/dirty") == [
        (
            "finish",
            "check:/repo/dirty",
            "skipped",
            "checkout has local changes",
        )
    ]
    assert progress.finishes("check") == [("finish", "check", "done", "1 skipped")]


def test_call_plan_dev_update_forwards_progress_only_when_accepted(
    monkeypatch,
) -> None:
    host = _record("sase", role="host", source_root="/repo")
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", lambda _status: None)
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda root: _status(str(root))
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)
    progress = RecordingProgress()

    dev_plan = call_plan_dev_update(
        plan_dev_update,
        [host],
        host_record=host,
        receipt=None,
        tool_python="/tool/bin/python",
        progress=progress,
    )

    assert dev_plan.roots[0].status == "actionable"
    assert progress.finishes("check") == [("finish", "check", "done", "1 behind")]

    def legacy_fake(
        records,
        *,
        host_record,
        receipt=None,
        tool_python=None,
        stale_core_record=None,
    ):
        return plan_dev_update(
            records,
            host_record=host_record,
            receipt=receipt,
            tool_python=tool_python,
            stale_core_record=stale_core_record,
        )

    legacy_progress = RecordingProgress()
    call_plan_dev_update(
        legacy_fake,
        [host],
        host_record=host,
        receipt=None,
        tool_python="/tool/bin/python",
        progress=legacy_progress,
    )
    assert legacy_progress.events == []


def test_merge_done_replaces_transient_merging_detail() -> None:
    runner = StreamingRunner(
        responses={
            ("git", "-C", "/repo", "rev-parse", "HEAD"): DevCommandResult(
                1, stderr="unknown revision"
            ),
        }
    )
    progress = RecordingProgress()
    commands: list[DevExecutedCommand] = []

    failure, merged, _, _ = merge_actionable_roots(
        (root(),), runner, commands, time.monotonic, progress
    )

    assert failure is None
    assert merged is True
    assert progress.finishes("merge:/repo") == [
        ("finish", "merge:/repo", "done", "fast-forwarded")
    ]


def test_root_display_names_disambiguate_collisions() -> None:
    assert root_display_names(("/repo/sase", "/repo/plugins")) == {
        "/repo/sase": "sase",
        "/repo/plugins": "plugins",
    }
    assert root_display_names(("/a/sase", "/b/sase")) == {
        "/a/sase": "a/sase",
        "/b/sase": "b/sase",
    }


def test_reconcile_step_titles_and_merge_details() -> None:
    kinds = {
        "uv_tool_install": "Reinstall editable Python packages",
        "rust_prebuild_install": "Install prebuilt Rust core",
        "rust_dev_install": "Rebuild Rust core into uv-tool venv",
        "rust_install_uv_tool": "Rebuild Rust core into uv-tool venv",
        "rust_health_check": "Verify sase-core-rs imports",
        "rust_lsp_install": "Install macro LSP",
    }
    for kind, title in kinds.items():
        step = DevReconcileStep(kind=kind, label="original label", command=("x",))  # type: ignore[arg-type]
        assert reconcile_step_title(step) == title
    fallback = DevReconcileStep(
        kind="uv_tool_install", label="custom label", command=("x",)
    )
    assert reconcile_step_title(fallback) == "Reinstall editable Python packages"

    assert format_merge_detail(None, None, None, None) is None
    assert format_merge_detail("abc123456", "def456789", None, None) == (
        "abc1234 → def4567"
    )
