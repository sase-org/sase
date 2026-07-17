"""Tests for follow-up prompt artifact aggregation onto parent agents.

When the user sends feedback to an agent, the ``followup_prompt-<hash>.md``
artifact is registered against the child feedback agent's directory. The
parent's ARTIFACTS list aggregates these so the prompt is locatable from
the same place as other parent-level artifacts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.widgets.prompt_panel._artifact_files import artifact_file_paths
from sase.core.artifact_file_facade import store_explicit_artifact_file


class _StubAgent:
    """Minimal Agent surface needed by ``artifact_file_paths``."""

    def __init__(
        self,
        artifacts_dir: str,
        *,
        workspace_dir: str | None = None,
        followup_agents: list[_StubAgent] | None = None,
    ) -> None:
        self._artifacts_dir = artifacts_dir
        self.workspace_dir = workspace_dir
        self.followup_agents = followup_agents or []

    def get_artifacts_dir(self) -> str:
        return self._artifacts_dir


def _make_agent_artifacts_dir(home: Path, timestamp: str) -> Path:
    artifacts_dir = (
        home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / timestamp
    )
    artifacts_dir.mkdir(parents=True)
    return artifacts_dir


def test_parent_aggregates_followup_prompt_from_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    parent_dir = _make_agent_artifacts_dir(home, "20260510115700")
    child_dir = _make_agent_artifacts_dir(home, "20260510115740")

    followup_source = child_dir / "followup_prompt.md"
    followup_source.write_text("feedback body", encoding="utf-8")
    stored = store_explicit_artifact_file(
        followup_source,
        child_dir,
        label="Full feedback prompt",
        kind="markdown",
    )

    child = _StubAgent(str(child_dir))
    parent = _StubAgent(str(parent_dir), followup_agents=[child])

    parent_paths = [a.actual_path for a in artifact_file_paths(parent)]  # type: ignore[arg-type]
    child_paths = [a.actual_path for a in artifact_file_paths(child)]  # type: ignore[arg-type]

    expected_stored = str(Path(stored.path).resolve(strict=False))
    assert expected_stored in parent_paths
    assert expected_stored in child_paths


def test_parent_does_not_aggregate_non_followup_child_artifact_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    parent_dir = _make_agent_artifacts_dir(home, "20260510120000")
    child_dir = _make_agent_artifacts_dir(home, "20260510120100")

    followup_source = child_dir / "followup_prompt.md"
    followup_source.write_text("feedback body", encoding="utf-8")
    followup_artifact = store_explicit_artifact_file(
        followup_source,
        child_dir,
        label="Full feedback prompt",
        kind="markdown",
    )

    other_source = child_dir / "report.md"
    other_source.write_text("# child-only report\n", encoding="utf-8")
    other_artifact = store_explicit_artifact_file(
        other_source,
        child_dir,
        label="Child report",
        kind="markdown",
    )

    child = _StubAgent(str(child_dir))
    parent = _StubAgent(str(parent_dir), followup_agents=[child])

    parent_paths = [a.actual_path for a in artifact_file_paths(parent)]  # type: ignore[arg-type]

    expected_followup = str(Path(followup_artifact.path).resolve(strict=False))
    expected_other = str(Path(other_artifact.path).resolve(strict=False))
    assert expected_followup in parent_paths
    assert expected_other not in parent_paths


def test_parent_with_no_followups_unaffected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    parent_dir = _make_agent_artifacts_dir(home, "20260510130000")

    parent = _StubAgent(str(parent_dir), followup_agents=[])
    assert artifact_file_paths(parent) == []  # type: ignore[arg-type]


def test_parent_tolerates_child_with_missing_artifacts_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    parent_dir = _make_agent_artifacts_dir(home, "20260510140000")
    good_child_dir = _make_agent_artifacts_dir(home, "20260510140100")

    followup_source = good_child_dir / "followup_prompt.md"
    followup_source.write_text("feedback body", encoding="utf-8")
    stored = store_explicit_artifact_file(
        followup_source,
        good_child_dir,
        label="Full feedback prompt",
        kind="markdown",
    )

    bad_child_dir = (
        home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / "missing"
    )
    bad_child = _StubAgent(str(bad_child_dir))
    good_child = _StubAgent(str(good_child_dir))
    parent = _StubAgent(str(parent_dir), followup_agents=[bad_child, good_child])

    parent_paths = [a.actual_path for a in artifact_file_paths(parent)]  # type: ignore[arg-type]
    expected_stored = str(Path(stored.path).resolve(strict=False))
    assert expected_stored in parent_paths
