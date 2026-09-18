"""Hood aggregation in the runner's wait-dependency index."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    build_wait_dependency_index,
    dependency_resolution_status,
)


def _agent(
    projects_root: Path,
    timestamp: str,
    name: str,
    *,
    done: bool,
    outcome: str = "completed",
    clan: str | None = None,
) -> Path:
    artifact_dir = projects_root / "proj/artifacts/ace-run" / timestamp
    artifact_dir.mkdir(parents=True)
    meta: dict[str, object] = {"name": name}
    if clan is not None:
        meta["agent_clan"] = clan
        meta["agent_clan_generation"] = "20260717010000"
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if done:
        (artifact_dir / "done.json").write_text(
            json.dumps({"outcome": outcome}),
            encoding="utf-8",
        )
    return artifact_dir


def test_wait_on_hood_requires_every_current_member(tmp_path: Path) -> None:
    _agent(tmp_path, "20260717010101", "research.family", done=True)
    unfinished = _agent(
        tmp_path,
        "20260717010202",
        "research.clan.member",
        done=False,
        clan="research",
    )
    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    status = dependency_resolution_status(
        index,
        [],
        wait_hoods=["research"],
        self_artifact_dir=tmp_path / "proj/artifacts/ace-run/20260717020000",
    )

    assert status.resolved is False
    assert status.blocked_on == ("hood=research",)

    (unfinished / "done.json").write_text(json.dumps({"outcome": "completed"}))
    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    assert dependency_resolution_status(
        index,
        [],
        wait_hoods=["research"],
        self_artifact_dir=tmp_path / "proj/artifacts/ace-run/20260717020000",
    ).resolved


def test_wait_on_hood_honors_component_boundaries(tmp_path: Path) -> None:
    _agent(tmp_path, "20260717010101", "researcher.one", done=False)
    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    status = dependency_resolution_status(
        index,
        [],
        wait_hoods=["research"],
        self_artifact_dir=tmp_path / "proj/artifacts/ace-run/20260717020000",
    )

    assert status.resolved
    assert status.diagnostics == (
        "%wait(hood=research) matched no current hood members",
    )


def test_wait_on_empty_hood_resolves_with_diagnostic(tmp_path: Path) -> None:
    status = dependency_resolution_status(
        WaitDependencyIndex.empty(),
        [],
        wait_hoods=["missing"],
        self_artifact_dir=tmp_path / "proj/artifacts/ace-run/20260717020000",
    )

    assert status.resolved
    assert status.diagnostics == (
        "%wait(hood=missing) matched no current hood members",
    )


def test_wait_on_hood_ignores_members_launched_after_waiter(tmp_path: Path) -> None:
    _agent(tmp_path, "20260717010101", "research.before", done=True)
    _agent(tmp_path, "20260717030101", "research.after", done=False)
    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    status = dependency_resolution_status(
        index,
        [],
        wait_hoods=["research"],
        self_artifact_dir=tmp_path / "proj/artifacts/ace-run/20260717020000",
    )

    assert status.resolved
    assert status.diagnostics == ()


def test_wait_on_hood_uses_latest_member_before_waiter(tmp_path: Path) -> None:
    _agent(
        tmp_path,
        "20260717010101",
        "research.worker",
        done=True,
        outcome="failed",
    )
    _agent(tmp_path, "20260717010202", "research.worker", done=True)
    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    status = dependency_resolution_status(
        index,
        [],
        wait_hoods=["research"],
        self_artifact_dir=tmp_path / "proj/artifacts/ace-run/20260717020000",
    )

    assert status.resolved
    assert status.diagnostics == ()


def test_failed_hood_member_is_terminal_blocker(tmp_path: Path) -> None:
    failed = _agent(
        tmp_path,
        "20260717010101",
        "research.failed",
        done=True,
        outcome="failed",
    )
    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    blockers = index.terminal_blocking_artifacts_for_hood(
        "research",
        launched_at_or_before="20260717020000",
    )

    assert [Path(candidate.artifact_dir) for candidate in blockers] == [failed]
