"""Tests for durable run-scoped artifact-link release evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd.artifact_link_release_evidence import (
    ARTIFACT_LINK_RELEASE_EVIDENCE_FILENAME,
    load_artifact_link_release_evidence_index,
    record_artifact_link_release_evidence,
)
from tests._conftest_environment import redirect_sase_home


def _has_evidence(*, project_key: str, run_id: str, agent_id: str) -> bool:
    return (run_id, agent_id) in load_artifact_link_release_evidence_index(project_key)


def test_recorded_evidence_is_visible_for_the_exact_run_and_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")

    assert (
        _has_evidence(
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
        _has_evidence(
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
        _has_evidence(
            project_key="gh_sase-org__sase", run_id="run-2", agent_id="reader"
        )
        is False
    )
    assert (
        _has_evidence(
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
        _has_evidence(project_key="gh_sase-org__sase", run_id="", agent_id="reader")
        is False
    )
    assert (
        _has_evidence(project_key="gh_sase-org__sase", run_id="run-1", agent_id="")
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
        _has_evidence(
            project_key="gh_sase-org__sase", run_id="run-1", agent_id="reader"
        )
        is True
    )


def test_evidence_index_holds_only_valid_non_blank_pairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from sase.core.paths import sase_projects_dir

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    project_key = "gh_sase-org__sase"
    assert load_artifact_link_release_evidence_index(project_key) == frozenset()

    record_artifact_link_release_evidence(
        project_key=project_key,
        run_id="run-1",
        agent_id="reader",
        qualifying_repo_ids=("/tmp/plans",),
    )
    record_artifact_link_release_evidence(
        project_key=project_key,
        run_id="run-2",
        agent_id="writer",
        qualifying_repo_ids=("/tmp/research",),
    )
    path = sase_projects_dir() / project_key / ARTIFACT_LINK_RELEASE_EVIDENCE_FILENAME
    malformed = (
        "{not-json",
        "[]",
        "",
        json.dumps({"run_id": "", "agent_id": "reader", "qualifying_repo_ids": ["x"]}),
        json.dumps({"run_id": "run-3", "agent_id": "", "qualifying_repo_ids": ["x"]}),
        json.dumps({"run_id": "run-4", "agent_id": "empty", "qualifying_repo_ids": []}),
        json.dumps({"run_id": "run-5", "agent_id": "odd", "qualifying_repo_ids": 7}),
    )
    with path.open("a", encoding="utf-8") as handle:
        for line in malformed:
            handle.write(f"{line}\n")

    index = load_artifact_link_release_evidence_index(project_key)

    assert index == frozenset({("run-1", "reader"), ("run-2", "writer")})
