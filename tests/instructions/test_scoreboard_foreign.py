"""Unrecorded sessions are foreign to the run that did not launch them."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.instructions.coverage_records import (
    ManifestRecord,
    matching_manifests,
    session_is_foreign,
)
from sase.instructions.coverage_sessions import RootSession
from sase.instructions.coverage_summary import cover_sessions, provider_session_coverage
from sase.instructions.models import SessionObservation
from sase.instructions.render import render_foreign_sessions
from sase.instructions.run_index import ScoredRun
from tests.instructions._scoreboard_support import make_record, make_run
from tests.instructions.fixture_shadow import write_shadow_run


def _explicit_record(
    artifacts: Path,
    manifest: dict[str, object],
    *,
    session_ids: list[str],
    provider: str = "claude",
) -> ManifestRecord:
    manifest["delivery"]["status"] = "explicit"
    manifest["delivery"]["session_ids"] = session_ids
    (artifacts / "instructions" / f"00-{provider}.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return make_record(manifest, artifacts)


def _session(
    artifacts: Path,
    *,
    session_id: str,
    provider: str = "claude",
    run_name: str = "agent-root",
    markers: tuple[tuple[str, str], ...] = (),
    start: datetime | None = None,
) -> RootSession:
    return RootSession(
        provider=provider,
        run_name=run_name,
        artifact_dir=str(artifacts),
        workspace_dir="/work/synthetic",
        session_id=session_id,
        session_start=start or datetime(2026, 10, 6, 12, 1, tzinfo=UTC),
        bundle_markers=markers,
    )


def test_unlisted_markerless_sessions_are_foreign(tmp_path: Path) -> None:
    """Listed marked root stays; nested marker-less sessions are foreign."""
    artifacts, manifest, _ = write_shadow_run(tmp_path, provider="claude")
    record = _explicit_record(artifacts, manifest, session_ids=["root-session"])
    invocation = str(record.invocation_id)
    sha12 = str(record.bundle_sha256)[:12]
    listed = _session(
        artifacts,
        session_id="root-session",
        markers=((sha12, invocation),),
    )
    nested_a = _session(artifacts, session_id="nested-a")
    nested_b = _session(artifacts, session_id="nested-b")
    records = [record]
    assert session_is_foreign(listed, records) is False
    assert session_is_foreign(nested_a, records) is True
    assert session_is_foreign(nested_b, records) is True
    sessions = [listed, nested_a, nested_b]
    verdicts = cover_sessions(sessions, records)
    assert [item.session_id for item in verdicts] == ["root-session"]
    assert provider_session_coverage("claude", sessions, verdicts) == (1, 1)


def test_empty_session_ids_still_time_match(tmp_path: Path) -> None:
    """A record that recorded no ids keeps the legacy time-match path."""
    artifacts, manifest, _ = write_shadow_run(tmp_path, provider="claude")
    record = _explicit_record(artifacts, manifest, session_ids=[])
    session = _session(artifacts, session_id="markerless")
    assert session_is_foreign(session, [record]) is False
    assert matching_manifests(session, [record]) == [record]


def test_codex_rollout_stem_matches_recorded_thread_id(tmp_path: Path) -> None:
    """A marker-less Codex stem ending in the recorded thread id matches."""
    artifacts, manifest, _ = write_shadow_run(tmp_path, provider="codex")
    thread = "01a13d94-c6ae-70c0-bb68-e268763dfae7"
    record = _explicit_record(
        artifacts, manifest, session_ids=[thread], provider="codex"
    )
    stem = f"rollout-2026-10-14T23-22-02-{thread}"
    session = _session(artifacts, session_id=stem, provider="codex")
    assert session_is_foreign(session, [record]) is False
    assert matching_manifests(session, [record]) == [record]


def test_unlisted_only_session_warns_no_matching_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit record whose only session is unlisted still WARNs."""
    from sase.doctor import checks_instructions
    from sase.doctor.runner import DoctorContext
    from sase.instructions import coverage_records, coverage_sessions, run_index

    artifacts, manifest, _ = write_shadow_run(tmp_path, provider="claude")
    record = _explicit_record(artifacts, manifest, session_ids=["listed-root"])
    run = make_run("claude", "agent-miss", artifacts)
    session = _session(artifacts, session_id="unlisted", run_name=run.name)
    monkeypatch.setattr(run_index, "enumerate_runs", lambda **_kwargs: [run])
    monkeypatch.setattr(
        coverage_records, "run_manifest_records", lambda _adir: [record]
    )
    monkeypatch.setattr(coverage_sessions, "root_sessions", lambda _runs: [session])
    monkeypatch.setattr(
        "sase.instructions.verify.collect_observations", lambda _runs: []
    )
    monkeypatch.setattr(
        "sase.instructions.manifests.read_run_manifests", lambda _adir: []
    )
    check = checks_instructions._check_instructions_conformance(
        DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")
    )
    assert check.status == "WARN"
    assert "no matching root session" in check.summary


def test_listed_root_plus_nested_sessions_conformance_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nested unlisted sessions do not fail conformance when the root matches."""
    from sase.doctor import checks_instructions
    from sase.doctor.runner import DoctorContext
    from sase.instructions import coverage_records, coverage_sessions, run_index

    artifacts, manifest, _ = write_shadow_run(tmp_path, provider="claude")
    record = _explicit_record(artifacts, manifest, session_ids=["root-session"])
    invocation = str(record.invocation_id)
    sha12 = str(record.bundle_sha256)[:12]
    run = make_run("claude", "agent-ok", artifacts)
    listed = _session(
        artifacts,
        session_id="root-session",
        run_name=run.name,
        markers=((sha12, invocation),),
    )
    nested = _session(artifacts, session_id="nested-p", run_name=run.name)
    monkeypatch.setattr(run_index, "enumerate_runs", lambda **_kwargs: [run])
    monkeypatch.setattr(
        coverage_records, "run_manifest_records", lambda _adir: [record]
    )
    monkeypatch.setattr(
        coverage_sessions, "root_sessions", lambda _runs: [listed, nested]
    )
    monkeypatch.setattr(
        "sase.instructions.verify.collect_observations",
        lambda _runs: [
            SessionObservation(
                provider="claude",
                run_name=run.name,
                session_id="root-session",
                contract_count=1,
                bundle_count=1,
                delivery="explicit",
            )
        ],
    )
    monkeypatch.setattr(
        "sase.instructions.manifests.read_run_manifests", lambda _adir: []
    )
    check = checks_instructions._check_instructions_conformance(
        DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")
    )
    assert check.status == "OK"


def test_foreign_nested_sessions_dropped_from_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unlisted marker-less sessions leave the verify observation set."""
    from sase.instructions import _verify_collection
    from sase.instructions import coverage_records, coverage_sessions

    artifacts, manifest, _ = write_shadow_run(tmp_path, provider="claude")
    record = _explicit_record(artifacts, manifest, session_ids=["root-session"])
    run = ScoredRun(
        provider="claude",
        name="agent-drop",
        workspace_dir="/work/synthetic",
        artifact_dir=str(artifacts),
        started_at=datetime(2026, 10, 6, 11, tzinfo=UTC),
        ended_at=None,
        project=None,
    )
    listed = _session(artifacts, session_id="root-session", run_name=run.name)
    nested = _session(artifacts, session_id="nested-p", run_name=run.name)
    root_obs = SessionObservation(
        provider="claude",
        run_name=run.name,
        session_id="root-session",
        contract_count=1,
    )
    nested_obs = SessionObservation(
        provider="claude",
        run_name=run.name,
        session_id="nested-p",
        contract_count=2,
        foreign="auto-memory",
    )
    monkeypatch.setattr(
        _verify_collection,
        "observe_claude",
        lambda *_args, **_kwargs: [root_obs, nested_obs],
    )
    monkeypatch.setattr(
        coverage_sessions, "root_sessions", lambda _runs: [listed, nested]
    )
    monkeypatch.setattr(
        coverage_records, "run_manifest_records", lambda _adir: [record]
    )
    kept = _verify_collection.collect_observations([run])
    assert [item.session_id for item in kept] == ["root-session"]


def test_verify_a_prints_foreign_line(tmp_path: Path) -> None:
    """``verify -a`` labels an unlisted session instead of scoring it."""
    session = _session(tmp_path, session_id="nested-p", run_name="research.4g")
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=120)
    render_foreign_sessions([session], console=console)
    text = buf.getvalue()
    assert "research.4g/nested-p:" in text
    assert "⊘ foreign — not recorded by this run; not scored" in text
