"""Effective gate outcome computation, including archived/dismissed completions."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.dismissed_agent_completion import effective_done_outcome
from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._dismissed_completion_helpers import (
    add_archive_identity,
    rebuild_completion_archive,
    write_dismissed_completion,
)
from tests._gate_wait_dependency_helpers import _identity_dep


@pytest.mark.parametrize(
    ("gate_state", "expected"),
    [
        ("answered", "completed"),
        ("completed", "completed"),
        ("stopped", "completed"),
        ("failed", "failed"),
        ("timeout", "failed"),
        ("lost", "failed"),
        ("unknown", "failed"),
        (None, "failed"),
        ([], "failed"),
    ],
)
def test_effective_gate_outcome_fails_closed(
    gate_state: object,
    expected: str,
) -> None:
    assert effective_done_outcome({"outcome": "gated", "gate_state": gate_state}) == (
        expected
    )


def test_effective_gate_outcome_reads_nested_family_shell() -> None:
    assert (
        effective_done_outcome(
            {
                "outcome": "gated",
                "family_shell": {"kind": "gate", "state": "answered"},
            }
        )
        == "completed"
    )
    assert (
        effective_done_outcome(
            {
                "outcome": "gated",
                "family_shell": {"kind": "monitor", "state": "completed"},
            }
        )
        == "failed"
    )


@pytest.mark.parametrize(
    ("gate_state", "expected_resolved"),
    [("answered", True), ("completed", True), ("failed", False), (None, False)],
)
def test_archived_default_gate_status_uses_gate_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_state: str | None,
    expected_resolved: bool,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260827162000",
        "archived-gate",
    )
    add_archive_identity(artifact_dir)
    extra = {} if gate_state is None else {"gate_state": gate_state}
    write_dismissed_completion(
        tmp_path,
        artifact_dir,
        "archived-gate",
        status="GATED",
        extra=extra,
    )
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert index.is_resolved("archived-gate") is expected_resolved
    assert (
        dependency_resolution_status(
            index,
            [],
            [_identity_dep(artifact_dir, name="archived-gate")],
        ).resolved
        is expected_resolved
    )
    candidate = index.artifacts_by_dir[str(artifact_dir)]
    assert candidate.archived_completion is not None
    assert candidate.is_failed is (not expected_resolved)


def test_archived_custom_gate_stop_status_remains_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260827162100",
        "archived-gate",
    )
    add_archive_identity(artifact_dir)
    write_dismissed_completion(
        tmp_path,
        artifact_dir,
        "archived-gate",
        status="REVIEWED",
        extra={"gate_stop_status": "REVIEWED", "gate_state": "answered"},
    )
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("archived-gate")
    assert index.artifacts_by_dir[str(artifact_dir)].archived_completion is None
