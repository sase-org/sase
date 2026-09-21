"""Progress-event tests for the dev-update backends.

Uses a recording :class:`UpdateProgress` fake plus a streaming-capable
command runner to assert event order, statuses, details, and output
routing for planning, execution, and reconciliation.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from sase.dev_update import prebuild
from sase.dev_update.execute import execute_dev_update
from sase.dev_update.models import (
    DevCommandResult,
    DevReconcileStep,
    DevUpdatePlan,
    OutputSink,
)
from sase.dev_update.plan import plan_dev_update
import sase.dev_update.plan as plan_mod
from sase.dev_update.progress import (
    format_merge_detail,
    reconcile_step_title,
    root_display_names,
)
from sase.dev_update.code_swap_lock import code_swap_reader_lock
from sase.main.update_handler_support import call_plan_dev_update
from sase.update_progress import StepSpec, StepStatus
from sase.version._git import GitUpstreamStatus
from sase.version._models import (
    GitProbeResult,
    GitVersionMetadata,
    VersionPackageRecord,
)
from tests.dev_update._execute_helpers import FakeRunner, package, plan


class RecordingProgress:
    """In-memory :class:`UpdateProgress` recording every event in order."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def declare(self, specs: Sequence[StepSpec]) -> None:
        self.events.append(
            ("declare", tuple((spec.id, spec.title, spec.parent_id) for spec in specs))
        )

    def start(
        self, id: str, *, title: str | None = None, detail: str | None = None
    ) -> None:
        self.events.append(("start", id, title, detail))

    def output(self, id: str, stream: str, line: str) -> None:
        self.events.append(("output", id, stream, line))

    def finish(self, id: str, status: StepStatus, *, detail: str | None = None) -> None:
        self.events.append(("finish", id, status, detail))

    def command(self, id: str, argv: Sequence[str], cwd: str | None = None) -> None:
        self.events.append(("command", id, tuple(argv), cwd))

    def finalize(self, status_for_pending: StepStatus = "skipped") -> None:
        self.events.append(("finalize", status_for_pending))

    def output_sink(self, id: str) -> OutputSink:
        def sink(stream: str, line: str) -> None:
            self.output(id, stream, line)

        return sink

    def finishes(self, id: str) -> list[tuple]:
        return [event for event in self.events if event[:2] == ("finish", id)]

    def outputs(self, id: str) -> list[tuple]:
        return [event for event in self.events if event[:2] == ("output", id)]


class StreamingRunner(FakeRunner):
    """Fake runner that accepts ``on_output`` and replays canned lines."""

    def __init__(
        self,
        responses: dict[tuple[str, ...], DevCommandResult] | None = None,
        *,
        emit: dict[tuple[str, ...], list[tuple[str, str]]] | None = None,
        sequences: dict[tuple[str, ...], list[DevCommandResult]] | None = None,
    ) -> None:
        super().__init__(responses)
        self.emit = emit or {}
        self.sequences = sequences or {}
        self.sink_calls: list[tuple[tuple[str, ...], bool]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        on_output: OutputSink | None = None,
    ) -> DevCommandResult:
        command = tuple(argv)
        self.calls.append((command, cwd))
        self.env_calls.append((command, cwd, dict(env) if env is not None else None))
        self.timeout_calls.append((command, timeout))
        self.sink_calls.append((command, on_output is not None))
        if on_output is not None:
            for stream, line in self.emit.get(command, []):
                on_output(stream, line)
        if command in self.sequences and self.sequences[command]:
            return self.sequences[command].pop(0)
        if command in self.responses:
            return self.responses[command]
        if command[:5] == ("git", "-C", "/repo", "status", "--porcelain"):
            return DevCommandResult(0, stdout="")
        if command[:6] == (
            "git",
            "-C",
            "/repo",
            "rev-list",
            "--left-right",
            "--count",
        ):
            return DevCommandResult(0, stdout="0 2")
        if command[:5] == ("git", "-C", "/repo", "rev-parse", "HEAD"):
            return DevCommandResult(0, stdout="abc123\n")
        return DevCommandResult(0)


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


def test_execute_success_streams_output_into_running_steps() -> None:
    step = DevReconcileStep(
        kind="uv_tool_install",
        label="Reinstall uv-tool editable Python packages",
        command=("uv", "tool", "install", "sase"),
        cwd="/repo",
    )
    runner = StreamingRunner(
        emit={("uv", "tool", "install", "sase"): [("stderr", "Resolved 3 packages")]},
    )
    progress = RecordingProgress()

    result = execute_dev_update(plan(reconcile=(step,)), run=runner, progress=progress)

    assert result.changed is True
    assert progress.events[0] == (
        "declare",
        (
            ("merge", "Fast-forward checkouts", None),
            ("merge:/repo", "Fast-forward repo", "merge"),
            ("reconcile:0", "Reinstall editable Python packages", None),
        ),
    )
    assert progress.finishes("merge") == [("finish", "merge", "done", None)]
    merge_finish = progress.finishes("merge:/repo")
    assert len(merge_finish) == 1
    assert merge_finish[0][2] == "done"
    assert merge_finish[0][3] is not None and "→" in merge_finish[0][3]
    assert progress.finishes("reconcile:0") == [("finish", "reconcile:0", "done", None)]
    assert progress.outputs("reconcile:0") == [
        ("output", "reconcile:0", "stderr", "Resolved 3 packages")
    ]
    assert (
        "command",
        "merge:/repo",
        ("git", "-C", "/repo", "status", "--porcelain"),
        None,
    ) in progress.events
    assert all(used for _, used in runner.sink_calls)


def test_execute_prebuild_hit_skips_rebuild_with_progress() -> None:
    prebuild_command = ("python", "-m", "sase.dev_update.prebuild", "consume")
    rust_command = ("just", "rust-dev-install-uv-tool")
    update_plan = plan(
        reconcile=(
            DevReconcileStep(
                kind="rust_prebuild_install",
                label="Install prebuilt Rust dev artifacts into the uv-tool venv",
                command=prebuild_command,
                cwd="/host",
            ),
            DevReconcileStep(
                kind="rust_dev_install",
                label="Rebuild Rust dev artifacts into the uv-tool venv",
                command=rust_command,
                cwd="/host",
            ),
            DevReconcileStep(
                kind="rust_health_check",
                label="Verify sase-core-rs imports in the uv-tool venv",
                command=("/tool/bin/python", "-c", "import sase_core_rs"),
            ),
        )
    )
    runner = StreamingRunner(
        responses={
            prebuild_command: DevCommandResult(
                0,
                stdout=prebuild._outcome_marker(  # noqa: SLF001
                    prebuild._RustPrebuildConsumeOutcome(  # noqa: SLF001
                        True,
                        "hit",
                        set_key="cache-key",
                    )
                ),
            )
        }
    )
    progress = RecordingProgress()

    result = execute_dev_update(update_plan, run=runner, progress=progress)

    assert result.changed is True
    assert progress.finishes("reconcile:0") == [
        ("finish", "reconcile:0", "done", "cache hit")
    ]
    assert progress.finishes("reconcile:1") == [
        ("finish", "reconcile:1", "skipped", "prebuilt artifacts used")
    ]
    assert progress.finishes("reconcile:2") == [("finish", "reconcile:2", "done", None)]
    assert rust_command not in [call[0] for call in runner.calls]


def test_execute_preflight_dirty_failure_marks_child_failed() -> None:
    runner = StreamingRunner(
        responses={
            ("git", "-C", "/repo", "status", "--porcelain"): DevCommandResult(
                0, stdout=" M src/sase/__init__.py"
            )
        }
    )
    progress = RecordingProgress()

    result = execute_dev_update(plan(), run=runner, progress=progress)

    assert result.changed is False
    assert progress.finishes("merge:/repo")[0][2] == "failed"
    assert "local changes" in progress.finishes("merge:/repo")[0][3]
    assert progress.finishes("merge")[0][2] == "failed"


def test_execute_code_swap_deferral_warns_merge() -> None:
    progress = RecordingProgress()

    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ):
        result = execute_dev_update(plan(), run=StreamingRunner(), progress=progress)

    assert result.changed is False
    assert progress.finishes("merge") == [
        ("finish", "merge", "warned", result.outcomes[0].reason)
    ]


def test_execute_noop_plan_emits_no_events() -> None:
    update_plan = DevUpdatePlan(
        packages=(package("sase", status="skipped"),),
        roots=(),
        reconcile_steps=(),
    )
    progress = RecordingProgress()

    result = execute_dev_update(update_plan, run=StreamingRunner(), progress=progress)

    assert result.changed is False
    assert progress.events == []


def test_execute_health_check_repair_has_child_row() -> None:
    health_command = ("/tool/bin/python", "-c", "import sase_core_rs")
    repair_command = ("uv", "pip", "install", "--force-reinstall", "sase-core-rs")
    update_plan = plan(
        reconcile=(
            DevReconcileStep(
                kind="rust_health_check",
                label="Verify sase-core-rs imports in the uv-tool venv",
                command=health_command,
                repair_command=repair_command,
                repair_label="Restore published sase-core-rs wheel",
            ),
        )
    )
    runner = StreamingRunner(
        sequences={
            health_command: [
                DevCommandResult(1, stderr="No module named sase_core_rs"),
                DevCommandResult(0, stdout="0.3.7\n"),
            ],
        },
        emit={repair_command: [("stderr", "Installed sase-core-rs")]},
    )
    progress = RecordingProgress()

    result = execute_dev_update(update_plan, run=runner, progress=progress)

    assert result.changed is True
    assert result.outcomes[0].status == "failed"
    assert progress.finishes("reconcile:0:repair") == [
        ("finish", "reconcile:0:repair", "done", None)
    ]
    assert progress.outputs("reconcile:0:repair") == [
        ("output", "reconcile:0:repair", "stderr", "Installed sase-core-rs")
    ]
    assert progress.finishes("reconcile:0")[0][2] == "warned"


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
        "rust_lsp_install": "Install xprompt LSP",
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
