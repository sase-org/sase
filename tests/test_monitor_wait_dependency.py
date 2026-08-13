"""Wait-dependency semantics for monitor family and clan members."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.dismissed_agent_completion import effective_done_outcome
from sase.core.wait_dependency_resolution import build_wait_dependency_index
from tests._agent_names_fixtures import make_agent


def _monitor_member(
    tmp_path: Path,
    monitor_state: object,
    *,
    with_done_marker: bool = True,
) -> Path:
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090000",
        "monitor-lane--mon",
        workflow_name="monitor-lane",
        agent_family="monitor-lane",
        role_suffix="--mon",
    )
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "agent_clan": "monitor-clan",
            "agent_clan_generation": "20260813085900",
            "monitor_state": "running",
        }
    )
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    if with_done_marker:
        done: dict[str, object] = {"outcome": "monitored"}
        if monitor_state is not None:
            done["monitor_state"] = monitor_state
        (artifact_dir / "done.json").write_text(
            json.dumps(done),
            encoding="utf-8",
        )
    return artifact_dir


@pytest.mark.parametrize("monitor_state", ["completed", "stopped"])
def test_successful_monitor_resolves_family_and_clan(
    tmp_path: Path,
    monitor_state: str,
) -> None:
    artifact_dir = _monitor_member(tmp_path, monitor_state)

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert index.is_resolved("monitor-lane")
    family = index.family_candidate("monitor-lane")
    clan = index.clan_candidate("monitor-clan")
    assert family is not None and family.is_resolved and family.is_done
    assert clan is not None and clan.is_resolved and clan.is_done
    assert index.artifacts_by_dir[str(artifact_dir)].outcome == "completed"
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == ()


@pytest.mark.parametrize("monitor_state", ["failed", "timeout", "unknown", None])
def test_unsuccessful_monitor_blocks_and_is_reported_as_terminal(
    tmp_path: Path,
    monitor_state: str | None,
) -> None:
    artifact_dir = _monitor_member(tmp_path, monitor_state)

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("monitor-lane")
    family = index.family_candidate("monitor-lane")
    clan = index.clan_candidate("monitor-clan")
    assert family is not None and family.is_failed
    assert clan is not None and clan.is_failed
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == (
        index.artifacts_by_dir[str(artifact_dir)],
    )
    assert index.artifacts_by_dir[str(artifact_dir)].outcome == "failed"


def test_running_monitor_without_done_marker_still_blocks(
    tmp_path: Path,
) -> None:
    _monitor_member(tmp_path, "running", with_done_marker=False)

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("monitor-lane")
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == ()


@pytest.mark.parametrize(
    ("monitor_state", "expected"),
    [
        ("completed", "completed"),
        ("stopped", "completed"),
        ("failed", "failed"),
        ("timeout", "failed"),
        (None, "failed"),
        ([], "failed"),
    ],
)
def test_effective_monitor_outcome_fails_closed(
    monitor_state: object,
    expected: str,
) -> None:
    assert (
        effective_done_outcome({"outcome": "monitored", "monitor_state": monitor_state})
        == expected
    )
