"""Shared test helpers for dev-update execution."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sase.dev_update.models import (
    DevCommandResult,
    DevReconcileStep,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateRootPlan,
)
from sase.version._models import VersionPackageRecord


def record(name: str) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role="host",
        display_version="0.5.0+1.gaaaaaaaaa",
        distribution_version="0.5.0",
        source_version="0.5.0",
        import_module=None,
        import_path=None,
        code_directory=None,
        source_root="/repo",
        distribution_location=None,
        install_type="editable",
        git=None,
    )


def package(name: str, *, status: str = "actionable") -> DevUpdatePackagePlan:
    return DevUpdatePackagePlan(
        record=record(name),
        status=status,  # type: ignore[arg-type]
        reason="behind upstream by 2 commit(s)"
        if status == "actionable"
        else "already current",
        current_version="0.5.0+1.gaaaaaaaaa",
        latest_version="0.5.0+3.gbbbbbbbbb",
        git_root="/repo",
        upstream="origin/main",
        remote="origin",
        remote_branch="main",
        ahead=0,
        behind=2,
    )


def root(path: str = "/repo") -> DevUpdateRootPlan:
    return DevUpdateRootPlan(
        git_root=path,
        status="actionable",
        reason="behind upstream by 2 commit(s)",
        upstream="origin/main",
        remote="origin",
        remote_branch="main",
        packages=("sase",),
        ahead=0,
        behind=2,
    )


def plan(*, reconcile: tuple[DevReconcileStep, ...] = ()) -> DevUpdatePlan:
    return DevUpdatePlan(
        packages=(package("sase"),),
        roots=(root(),),
        reconcile_steps=reconcile,
    )


def stale_core_package() -> DevUpdatePackagePlan:
    return DevUpdatePackagePlan(
        record=record("sase-core-rs"),
        status="actionable",
        reason=(
            "installed sase-core-rs is a published wheel; dev installs use "
            "the editable build from the local checkout"
        ),
        current_version="0.4.1",
        latest_version="0.5.0",
    )


class FakeRunner:
    def __init__(
        self, responses: dict[tuple[str, ...], DevCommandResult] | None = None
    ) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[tuple[str, ...], Path | None]] = []

    def __call__(
        self, argv: Sequence[str], *, cwd: Path | None = None
    ) -> DevCommandResult:
        command = tuple(argv)
        self.calls.append((command, cwd))
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


class SequenceRunner(FakeRunner):
    def __init__(
        self,
        sequences: dict[tuple[str, ...], list[DevCommandResult]],
        responses: dict[tuple[str, ...], DevCommandResult] | None = None,
    ) -> None:
        super().__init__(responses)
        self.sequences = sequences

    def __call__(
        self, argv: Sequence[str], *, cwd: Path | None = None
    ) -> DevCommandResult:
        command = tuple(argv)
        if command in self.sequences and self.sequences[command]:
            self.calls.append((command, cwd))
            return self.sequences[command].pop(0)
        return super().__call__(argv, cwd=cwd)
