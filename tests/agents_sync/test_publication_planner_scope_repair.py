"""Regression tests for evidence-based planner publication scope repair."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import replace
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from sase.agents.cli_sync import handle_agents_sync
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import (
    PUBLICATION_SCOPE_LINKED,
    PUBLICATION_SCOPE_REVISION,
    AgentPublicationOutboxItem,
)
from sase.agents_sync._publication_planner_scope_repair_apply import (
    apply_project_planner_scopes,
)
from sase.agents_sync._publication_planner_scope_repair_classification import (
    classify_project_planner_scopes,
)
from sase.agents_sync._publication_planner_scope_repair_models import (
    REPAIR_PLANNER_SCOPES_AUDIT_FILENAME,
    PlannerScopeRepairReport,
    PlannerScopeRowReport,
)
from sase.main.parser import create_parser

_ARCHIVE_COMMIT = "b" * 40


def _item(
    local_agent: str,
    revision: str,
    *,
    scope: str = PUBLICATION_SCOPE_REVISION,
    artifacts_dir: Path | None = None,
    created_at: float = 1_000.0,
    attempts: int = 0,
    last_error: str | None = None,
    quarantined: bool = False,
    quarantined_at: float | None = None,
    terminal: bool = False,
    terminal_reason: str | None = None,
    run_id: str | None = None,
) -> AgentPublicationOutboxItem:
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent=local_agent,
        global_agent=f"alice.athena.{local_agent}",
        primary_revision=revision,
        local_hood=local_agent,
        scope=scope,
        artifacts_dir=None if artifacts_dir is None else str(artifacts_dir),
        created_at=created_at,
        attempts=attempts,
        last_error=last_error,
        quarantined=quarantined,
        quarantined_at=quarantined_at,
        terminal=terminal,
        terminal_reason=terminal_reason,
        run_id=run_id,
    )


def _target(tmp_path: Path) -> ProjectTarget:
    primary = tmp_path / "primary"
    primary.mkdir()
    sidecar = tmp_path / "agents"
    sidecar.mkdir()
    return ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        sidecar,
        "unused",
        "primary",
    )


def _write_metadata(
    artifacts_dir: Path,
    *,
    name: str,
    approved: bool,
    workspace_head: str,
) -> None:
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": name,
                "plan_approved": approved,
                "workspace_head": workspace_head,
            }
        ),
        encoding="utf-8",
    )


def test_report_proves_only_matching_planner_metadata_and_nearby_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report scans revision rows and leaves real, linked, and unproven rows alone."""

    import sase.agents_sync._publication_planner_scope_repair_classification as classifier

    target = _target(tmp_path)
    approved_sha = "a" * 40
    metadata_dir = tmp_path / "approved-planner"
    _write_metadata(
        metadata_dir,
        name="sase-1q4.land--plan",
        approved=True,
        workspace_head=approved_sha,
    )
    rejected_dir = tmp_path / "unapproved-planner"
    _write_metadata(
        rejected_dir,
        name="sase-1q5.land--plan",
        approved=False,
        workspace_head="c" * 40,
    )
    approved = _item("sase-1q4.land", approved_sha, artifacts_dir=metadata_dir)
    archived = _item("bob-cli-eg.land", "d" * 40, created_at=1_005.0)
    real_commit = _item(
        "real-commit",
        "e" * 40,
        created_at=2_000.0,
        run_id="run-1",
    )
    rejected = _item(
        "sase-1q5.land",
        "c" * 40,
        artifacts_dir=rejected_dir,
    )
    linked = _item("already-linked", "f" * 40, scope=PUBLICATION_SCOPE_LINKED)
    rows = (approved, archived, real_commit, rejected, linked)
    before = tuple(item.to_json_dict() for item in rows)
    monkeypatch.setattr(classifier, "list_agent_publications", lambda _key: rows)

    def git_runner(
        cwd: Path,
        args: list[str],
        *,
        network: bool,
        op: str,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == target.sidecar_path
        assert args[0] == "log"
        assert network is False
        assert op.endswith("archive_log")
        output = (
            f"1000\t{_ARCHIVE_COMMIT}\t"
            "chore(agents): archive prompt for "
            "alice.athena.bob-cli-eg.land--plan\n"
            f"1000\t{'c' * 40}\t"
            "chore(agents): archive prompt for unrelated--plan\n"
        )
        return subprocess.CompletedProcess(args, 0, output, "")

    report = classify_project_planner_scopes(
        target,
        git_runner=git_runner,
    )

    assert [row.local_agent for row in report.rows] == [
        "sase-1q4.land",
        "bob-cli-eg.land",
        "real-commit",
        "sase-1q5.land",
    ]
    metadata, archive, real, unapproved = report.rows
    assert metadata.eligible and metadata.evidence_kind == "planner_metadata"
    assert archive.eligible and archive.evidence_kind == "planner_archive_commit"
    assert archive.evidence_commit == _ARCHIVE_COMMIT
    assert not real.eligible
    assert not unapproved.eligible
    assert report.changed == 2
    assert report.applied is False
    assert report.evidence_error is None
    assert before == tuple(item.to_json_dict() for item in rows)
    assert "report only" in report.diagnostics()[-1]


def test_archive_commit_outside_window_is_not_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-agent archive commit must be near the outbox creation time."""

    import sase.agents_sync._publication_planner_scope_repair_classification as classifier

    target = _target(tmp_path)
    row = _item("bob-cli-er.land", "a" * 40, created_at=1_100.0)
    monkeypatch.setattr(classifier, "list_agent_publications", lambda _key: (row,))

    def git_runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool,
        op: str,
    ) -> subprocess.CompletedProcess[str]:
        assert network is False
        return subprocess.CompletedProcess(
            args,
            0,
            f"1000\t{_ARCHIVE_COMMIT}\t"
            "chore(agents): archive prompt for bob-cli-er.land--plan\n",
            "",
        )

    report = classify_project_planner_scopes(target, git_runner=git_runner)

    assert len(report.rows) == 1
    assert not report.rows[0].eligible


def test_apply_changes_only_scope_and_audits_each_proven_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply preserves identity, retry history, and lifecycle fields."""

    import sase.agents_sync._publication_planner_scope_repair_apply as application

    target = _target(tmp_path)
    metadata_row = _item(
        "planner-one",
        "a" * 40,
        attempts=3,
        last_error="required page exists without the requested primary revision",
        quarantined=True,
        quarantined_at=900.0,
    )
    archive_row = _item(
        "planner-two",
        "b" * 40,
        attempts=2,
        last_error="retired reason",
        terminal=True,
        terminal_reason="retired reason",
    )
    unproven_row = _item("commit-run", "c" * 40, run_id="run-1")
    current = [metadata_row, archive_row, unproven_row]
    mutation_calls: list[str] = []

    def mutate(
        project_key: str,
        update: Callable[
            [tuple[AgentPublicationOutboxItem, ...]],
            tuple[AgentPublicationOutboxItem, ...],
        ],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        assert project_key == "proj"
        mutation_calls.append(project_key)
        current[:] = update(tuple(current))
        return tuple(current)

    audit_root = tmp_path / "sase-projects"
    monkeypatch.setattr(application, "mutate_publication_outbox", mutate)
    monkeypatch.setattr(application, "sase_projects_dir", lambda: audit_root)
    rows = (
        PlannerScopeRowReport(
            metadata_row.global_agent,
            metadata_row.local_agent,
            metadata_row.primary_revision,
            True,
            "planner_metadata",
            None,
            "approved planner metadata matches the row revision",
        ),
        PlannerScopeRowReport(
            archive_row.global_agent,
            archive_row.local_agent,
            archive_row.primary_revision,
            True,
            "planner_archive_commit",
            _ARCHIVE_COMMIT,
            "matching --plan archive commit is within 10 seconds",
        ),
        PlannerScopeRowReport(
            unproven_row.global_agent,
            unproven_row.local_agent,
            unproven_row.primary_revision,
            False,
            None,
            None,
            "no planner proof",
        ),
    )
    report = PlannerScopeRepairReport("proj", "Project", False, rows, 2)

    applied = apply_project_planner_scopes(target, report)

    assert applied.applied is True
    assert applied.changed == 2
    assert applied.audit_path is not None
    assert [item.scope for item in current] == [
        PUBLICATION_SCOPE_LINKED,
        PUBLICATION_SCOPE_LINKED,
        PUBLICATION_SCOPE_REVISION,
    ]
    assert current[0] == replace(metadata_row, scope=PUBLICATION_SCOPE_LINKED)
    assert current[1] == replace(archive_row, scope=PUBLICATION_SCOPE_LINKED)
    assert current[0].attempts == metadata_row.attempts
    assert current[0].last_error == metadata_row.last_error
    assert current[0].quarantined is True
    assert current[0].quarantined_at == metadata_row.quarantined_at
    assert current[1].attempts == archive_row.attempts
    assert current[1].terminal is True
    assert current[1].terminal_reason == archive_row.terminal_reason
    assert current[2] == unproven_row

    audit_path = audit_root / "proj" / REPAIR_PLANNER_SCOPES_AUDIT_FILENAME
    audit = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert len(audit) == 2
    assert {entry["old_scope"] for entry in audit} == {PUBLICATION_SCOPE_REVISION}
    assert {entry["new_scope"] for entry in audit} == {PUBLICATION_SCOPE_LINKED}
    assert {entry["evidence_kind"] for entry in audit} == {
        "planner_metadata",
        "planner_archive_commit",
    }
    assert mutation_calls == ["proj"]

    no_candidates = PlannerScopeRepairReport("proj", "Project", False, (), 0)
    repeated = apply_project_planner_scopes(target, no_candidates)
    assert repeated.applied is True
    assert repeated.changed == 0
    assert mutation_calls == ["proj"]
    assert len(audit_path.read_text().splitlines()) == 2


def test_parser_accepts_planner_scope_repair_and_rejects_conflicts() -> None:
    """The new mode requires one project and cannot mix with other sync actions."""

    args = create_parser().parse_args(
        ["agent", "sync", "-P", "-p", "sase", "--apply", "--json"]
    )
    assert args.repair_planner_scopes is True
    assert args.project == ["sase"]
    assert args.apply is True

    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", "--repair-planner-scopes"])
    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "extra",
    [
        ["--check"],
        ["--drop-retired"],
        ["--repair-digests"],
        ["--repair-manifest"],
        ["--repair-revisions"],
        ["--repair-states"],
        ["--retry-quarantined"],
        ["--retry-retired"],
        ["--retry-quarantined", "--retry-limit", "1"],
    ],
)
def test_parser_rejects_planner_scope_mode_conflicts(extra: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(
            ["agent", "sync", "--repair-planner-scopes", "-p", "sase", *extra]
        )
    assert exc_info.value.code == 2


def test_planner_scope_repair_cli_emits_stable_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI dispatch uses the report mode and propagates the project result."""

    args = argparse.Namespace(
        project=["sase"],
        json=True,
        apply=False,
        repair_planner_scopes=True,
    )
    from sase.agents_sync.models import SyncOutcome

    with patch(
        "sase.agents.cli_sync.repair_planner_publication_scopes",
        return_value=(SyncOutcome("proj", "Project", diagnostics=("report only",)),),
    ) as repair:
        exit_code = handle_agents_sync(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "repair-planner-scopes"
    assert payload["projects"][0]["diagnostics"] == ["report only"]
    assert exit_code == 0
    repair.assert_called_once_with(("sase",), apply=False)
