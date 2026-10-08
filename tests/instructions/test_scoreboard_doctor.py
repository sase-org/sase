"""Scoreboard doctor and JSON-report tests (split from test_scoreboard_coverage).

Manifests and bundles come from :mod:`tests.instructions.fixture_shadow`
(wire-shaped ``NN-<provider>.md`` / ``.json`` pairs); session files are
synthetic provider records with controlled timestamps.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sase.instructions import coverage as coverage_mod
from tests.instructions._scoreboard_support import (
    COVERED_START,
    RENDERED,
    UNCOVERED_START,
    WORKSPACE,
    make_record,
    make_run,
)
from tests.instructions.fixture_shadow import (
    write_shadow_error,
    write_shadow_run,
)


def _doctor_context(tmp_path: Path):
    from sase.doctor.runner import DoctorContext

    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")


def test_doctor_coverage_skips_without_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The coverage check SKIPs when the window holds no manifests."""
    from sase.doctor import checks_instructions
    from sase.instructions import run_index as run_mod

    monkeypatch.setattr(run_mod, "enumerate_runs", lambda **_kwargs: [])
    check = checks_instructions.check_instructions_coverage(_doctor_context(tmp_path))
    assert check.status == "SKIP"


def test_doctor_coverage_warns_on_uncovered_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The coverage check WARNs naming uncovered sessions and error runs."""
    from sase.doctor import checks_instructions
    from sase.instructions import run_index as run_mod
    from sase.instructions.manifests import RunManifest

    artifacts, manifest, _ = write_shadow_run(tmp_path, rendered_at=RENDERED)
    write_shadow_error(artifacts, provider="codex", seq=1)
    run = make_run(
        "codex",
        "agent-s",
        artifacts,
        started_at=datetime(2026, 10, 6, 12, 30, tzinfo=UTC),
    )
    record = make_record(manifest, artifacts)
    session = coverage_mod.RootSession(
        provider="codex",
        run_name="agent-s",
        artifact_dir=str(artifacts),
        workspace_dir=WORKSPACE,
        session_id="rollout-s",
        session_start=UNCOVERED_START,
    )
    monkeypatch.setattr(run_mod, "enumerate_runs", lambda **_kwargs: [run])
    monkeypatch.setattr(coverage_mod, "run_manifest_records", lambda _adir: [record])
    monkeypatch.setattr(coverage_mod, "root_sessions", lambda _runs: [session])
    error_entry = RunManifest(
        seq=1,
        provider="unknown",
        bundle_path=None,
        manifest_path=None,
        manifest=None,
        error={"provider": "codex"},
    )
    monkeypatch.setattr(
        "sase.instructions.manifests.read_run_manifests", lambda _adir: [error_entry]
    )
    check = checks_instructions.check_instructions_coverage(_doctor_context(tmp_path))
    assert check.status == "WARN"
    assert "agent-s/rollout-s" in check.summary
    assert "agent-s seq 1" in check.summary


def test_doctor_coverage_ok_when_fully_covered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The coverage check is OK when every session has a manifest."""
    from sase.doctor import checks_instructions
    from sase.instructions import run_index as run_mod

    artifacts, manifest, _ = write_shadow_run(tmp_path, rendered_at=RENDERED)
    run = make_run("codex", "agent-t", artifacts)
    record = make_record(manifest, artifacts)
    session = coverage_mod.RootSession(
        provider="codex",
        run_name="agent-t",
        artifact_dir=str(artifacts),
        workspace_dir=WORKSPACE,
        session_id="rollout-t",
        session_start=COVERED_START,
    )
    monkeypatch.setattr(run_mod, "enumerate_runs", lambda **_kwargs: [run])
    monkeypatch.setattr(coverage_mod, "run_manifest_records", lambda _adir: [record])
    monkeypatch.setattr(coverage_mod, "root_sessions", lambda _runs: [session])
    monkeypatch.setattr(
        "sase.instructions.manifests.read_run_manifests", lambda _adir: []
    )
    check = checks_instructions.check_instructions_coverage(_doctor_context(tmp_path))
    assert check.status == "OK"


def test_json_carries_coverage_and_section_diff(tmp_path: Path) -> None:
    """``-j`` keeps ``schema_version: 1`` with additive coverage keys."""
    from sase.instructions.models import ProviderRow, SessionObservation, VerifyReport
    from sase.instructions.render import report_to_json_dict

    artifacts, manifest, bundle = write_shadow_run(tmp_path)
    record = make_record(manifest, artifacts)
    session = coverage_mod.RootSession(
        provider="codex",
        run_name="agent-u",
        artifact_dir=str(artifacts),
        workspace_dir=WORKSPACE,
        session_id="rollout-u",
        session_start=COVERED_START,
    )
    verdicts = coverage_mod.cover_sessions([session], [record])
    covered, total = coverage_mod.provider_session_coverage(
        "codex", [session], verdicts
    )
    report = VerifyReport(
        provider_rows=(
            ProviderRow(
                provider="codex",
                runs=1,
                sessions=1,
                contract="2×",
                coverage=coverage_mod.coverage_label(covered, total),
            ),
        ),
        observations=(
            SessionObservation(
                provider="codex",
                run_name="agent-u",
                session_id="rollout-u",
                contract_count=2,
            ),
        ),
        filters={},
        generated_at="2026-10-06T00:00:00+00:00",
    )
    block = coverage_mod.purpose_coverage_rows([session], [record])
    diff = coverage_mod.SectionDiff(
        session_id="rollout-u",
        run_name="agent-u",
        manifest_path="instructions/00-codex.json",
        purpose="ordinary",
        unavailable=False,
        rows=(
            coverage_mod.SectionDiffRow(
                id="proj.core.gotchas",
                layer="project",
                observed=1,
                native=1,
                explicit=0,
            ),
        ),
    )
    payload = report_to_json_dict(
        report,
        include_observations=True,
        coverage_block=block,
        section_diffs={("agent-u", "rollout-u"): diff},
    )
    assert payload["schema_version"] == 1
    assert payload["providers"][0]["coverage"] == "1/1"
    assert payload["coverage"]["rows"][0]["provider"] == "codex"
    assert payload["coverage"]["rows"][0]["covered"] == 1
    assert payload["observations"][0]["section_diff"]["rows"][0]["id"] == (
        "proj.core.gotchas"
    )
    plain = report_to_json_dict(report, include_observations=False)
    assert "coverage" not in plain
    assert "observations" not in plain
