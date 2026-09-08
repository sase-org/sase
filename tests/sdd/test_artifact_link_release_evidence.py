"""Tests for durable run-scoped artifact-link release evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd.artifact_link_release_evidence import (
    ARTIFACT_LINK_RELEASE_EVIDENCE_FILENAME,
    artifact_link_run_has_release_evidence,
    record_artifact_link_release_evidence,
)
from tests._conftest_environment import redirect_sase_home


def test_recorded_evidence_is_visible_for_the_exact_run_and_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")

    assert (
        artifact_link_run_has_release_evidence(
            project_key="gh_sase-org__sase", run_id="run-1", agent_id="reader"
        )
        is False
    )

    record_artifact_link_release_evidence(
        project_key="gh_sase-org__sase",
        run_id="run-1",
        agent_id="reader",
        qualifying_repo_ids=("/tmp/plans",),
    )

    assert (
        artifact_link_run_has_release_evidence(
            project_key="gh_sase-org__sase", run_id="run-1", agent_id="reader"
        )
        is True
    )


def test_evidence_does_not_release_a_different_run_or_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    record_artifact_link_release_evidence(
        project_key="gh_sase-org__sase",
        run_id="run-1",
        agent_id="reader",
        qualifying_repo_ids=("/tmp/plans",),
    )

    assert (
        artifact_link_run_has_release_evidence(
            project_key="gh_sase-org__sase", run_id="run-2", agent_id="reader"
        )
        is False
    )
    assert (
        artifact_link_run_has_release_evidence(
            project_key="gh_sase-org__sase", run_id="run-1", agent_id="someone-else"
        )
        is False
    )


def test_blank_run_id_or_agent_id_never_qualifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    record_artifact_link_release_evidence(
        project_key="gh_sase-org__sase",
        run_id="run-1",
        agent_id="reader",
        qualifying_repo_ids=("/tmp/plans",),
    )

    assert (
        artifact_link_run_has_release_evidence(
            project_key="gh_sase-org__sase", run_id="", agent_id="reader"
        )
        is False
    )
    assert (
        artifact_link_run_has_release_evidence(
            project_key="gh_sase-org__sase", run_id="run-1", agent_id=""
        )
        is False
    )


def test_malformed_evidence_lines_are_skipped_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    record_artifact_link_release_evidence(
        project_key="gh_sase-org__sase",
        run_id="run-1",
        agent_id="reader",
        qualifying_repo_ids=("/tmp/plans",),
    )
    from sase.core.paths import sase_projects_dir

    path = (
        sase_projects_dir()
        / "gh_sase-org__sase"
        / ARTIFACT_LINK_RELEASE_EVIDENCE_FILENAME
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not-json\n")
        handle.write("[]\n")

    assert (
        artifact_link_run_has_release_evidence(
            project_key="gh_sase-org__sase", run_id="run-1", agent_id="reader"
        )
        is True
    )
