"""Scoreboard session-coverage verdicts (split from test_scoreboard_coverage).

Manifests and bundles come from :mod:`tests.instructions.fixture_shadow`
(wire-shaped ``NN-<provider>.md`` / ``.json`` pairs); session files are
synthetic provider records with controlled timestamps. The reader-entry
seam (:func:`record_from_entry`) keeps matching tests independent of the
Rust wire binding.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sase.instructions import run_index as run_mod
from sase.instructions import coverage as coverage_mod
from tests.instructions._scoreboard_support import (
    COVERED_START,
    RENDERED,
    SESSION_TS,
    UNCOVERED_START,
    WORKSPACE,
    make_record,
    make_run,
)
from tests.instructions.fixture_shadow import (
    write_shadow_error,
    write_shadow_run,
)


def _write_claude_session(
    directory: Path, stem: str, *, start_ts: str = SESSION_TS
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.jsonl"
    path.write_text(json.dumps({"timestamp": start_ts, "type": "marker"}) + "\n")
    return path


def test_full_coverage_single_session(tmp_path: Path) -> None:
    """A manifest rendered before the session start covers it (1/1)."""
    artifacts, manifest, _ = write_shadow_run(tmp_path, rendered_at=RENDERED)
    record = make_record(manifest, artifacts)
    session = coverage_mod.RootSession(
        provider="codex",
        run_name="agent-a",
        artifact_dir=str(artifacts),
        workspace_dir=WORKSPACE,
        session_id="rollout-x",
        session_start=COVERED_START,
    )
    verdicts = coverage_mod.cover_sessions([session], [record])
    assert [(item.covered, item.purpose) for item in verdicts] == [(True, "ordinary")]
    covered, total = coverage_mod.provider_session_coverage(
        "codex", [session], verdicts
    )
    assert (covered, total) == (1, 1)
    assert coverage_mod.coverage_label(covered, total) == "1/1"


def test_uncovered_session_before_manifest(tmp_path: Path) -> None:
    """A session that starts before any manifest is uncovered (0/1)."""
    artifacts, manifest, _ = write_shadow_run(tmp_path, rendered_at=RENDERED)
    record = make_record(manifest, artifacts)
    session = coverage_mod.RootSession(
        provider="codex",
        run_name="agent-b",
        artifact_dir=str(artifacts),
        workspace_dir=WORKSPACE,
        session_id="rollout-y",
        session_start=UNCOVERED_START,
    )
    verdicts = coverage_mod.cover_sessions([session], [record])
    assert [item.covered for item in verdicts] == [False]
    covered, total = coverage_mod.provider_session_coverage(
        "codex", [session], verdicts
    )
    assert coverage_mod.coverage_label(covered, total) == "0/1"


def test_skew_allows_seconds_late_manifest(tmp_path: Path) -> None:
    """A manifest seconds after the session start still covers within skew."""
    artifacts, manifest, _ = write_shadow_run(tmp_path, rendered_at=RENDERED)
    record = make_record(manifest, artifacts)
    session = coverage_mod.RootSession(
        provider="codex",
        run_name="agent-c",
        artifact_dir=str(artifacts),
        workspace_dir=WORKSPACE,
        session_id="rollout-z",
        session_start=datetime(2026, 10, 6, 11, 59, 58, tzinfo=UTC),
    )
    assert coverage_mod.cover_sessions([session], [record])[0].covered is True


def test_latest_manifest_wins(tmp_path: Path) -> None:
    """The latest covering manifest supplies the verdict purpose."""
    artifacts, first, _ = write_shadow_run(
        tmp_path, purpose="ordinary", rendered_at="2026-10-06T11:58:00Z", seq=0
    )
    _, second, _ = write_shadow_run(
        tmp_path,
        purpose="conflict_repair",
        rendered_at="2026-10-06T11:59:00Z",
        seq=1,
        artifacts_dir=artifacts,
    )
    records = [
        make_record(first, artifacts, seq=0),
        make_record(second, artifacts, seq=1),
    ]
    session = coverage_mod.RootSession(
        provider="codex",
        run_name="agent-d",
        artifact_dir=str(artifacts),
        workspace_dir=WORKSPACE,
        session_id="rollout-w",
        session_start=COVERED_START,
    )
    verdicts = coverage_mod.cover_sessions([session], records)
    assert verdicts[0].covered is True
    assert verdicts[0].purpose == "conflict_repair"
    assert verdicts[0].manifest_seq == 1


def test_fallback_run_covers_two_providers(tmp_path: Path) -> None:
    """One run's retry under another provider covers both providers."""
    artifacts = tmp_path / "run-fallback"
    _, claude_manifest, _ = write_shadow_run(
        tmp_path, provider="claude", seq=0, artifacts_dir=artifacts
    )
    _, codex_manifest, _ = write_shadow_run(
        tmp_path, provider="codex", seq=1, artifacts_dir=artifacts
    )
    records = [
        make_record(claude_manifest, artifacts, seq=0),
        make_record(codex_manifest, artifacts, seq=1),
    ]
    sessions = [
        coverage_mod.RootSession(
            provider="claude",
            run_name="agent-e",
            artifact_dir=str(artifacts),
            workspace_dir=WORKSPACE,
            session_id="root-e",
            session_start=COVERED_START,
        ),
        coverage_mod.RootSession(
            provider="codex",
            run_name="agent-e",
            artifact_dir=str(artifacts),
            workspace_dir=WORKSPACE,
            session_id="rollout-e",
            session_start=COVERED_START,
        ),
    ]
    verdicts = coverage_mod.cover_sessions(sessions, records)
    assert [item.covered for item in verdicts] == [True, True]
    assert coverage_mod.provider_session_coverage("claude", sessions, verdicts) == (
        1,
        1,
    )
    assert coverage_mod.provider_session_coverage("codex", sessions, verdicts) == (
        1,
        1,
    )


def test_agy_scored_per_run(tmp_path: Path) -> None:
    """agy coverage counts runs with at least one agy manifest."""
    covered_dir, covered_manifest, _ = write_shadow_run(tmp_path, provider="agy", seq=0)
    bare_dir = tmp_path / "run-agy-bare"
    (bare_dir / "instructions").mkdir(parents=True)
    runs = [
        make_run("agy", "agent-f", covered_dir),
        make_run("agy", "agent-g", bare_dir),
    ]
    records = [make_record(covered_manifest, covered_dir)]
    verdicts = coverage_mod.cover_agy_runs(runs, records)
    assert [(item.run_name, item.covered) for item in verdicts] == [
        ("agent-f", True),
        ("agent-g", False),
    ]


def test_purpose_rows_name_uncovered_pairs_and_latency(
    tmp_path: Path,
) -> None:
    """``-c`` rows group by purpose with uncovered pairs and warm/cold p95."""
    artifacts, ordinary, _ = write_shadow_run(
        tmp_path, purpose="ordinary", render_ms=10.0, cache="hit", seq=0
    )
    _, repair, _ = write_shadow_run(
        tmp_path,
        purpose="conflict_repair",
        render_ms=40.0,
        cache="miss",
        seq=1,
        artifacts_dir=artifacts,
    )
    write_shadow_error(artifacts, provider="codex", seq=2)
    records = [
        make_record(ordinary, artifacts, seq=0),
        make_record(repair, artifacts, seq=1),
    ]
    sessions = [
        coverage_mod.RootSession(
            provider="codex",
            run_name="agent-h",
            artifact_dir=str(artifacts),
            workspace_dir=WORKSPACE,
            session_id="rollout-h",
            session_start=COVERED_START,
        ),
        coverage_mod.RootSession(
            provider="codex",
            run_name="agent-i",
            artifact_dir=str(artifacts),
            workspace_dir=WORKSPACE,
            session_id="rollout-i",
            session_start=UNCOVERED_START,
        ),
    ]
    rows = coverage_mod.purpose_coverage_rows(
        sessions, records, error_counts={"codex": 1}
    )
    by_purpose = {row.purpose: row for row in rows}
    assert by_purpose["ordinary"].manifests == 1
    assert by_purpose["ordinary"].sessions == 2
    assert by_purpose["ordinary"].covered == 1
    assert by_purpose["ordinary"].uncovered == (("agent-i", "rollout-i"),)
    assert by_purpose["ordinary"].errors == 1
    assert by_purpose["ordinary"].warm_p50 == 10.0
    assert by_purpose["ordinary"].cold_p50 is None
    assert by_purpose["conflict_repair"].cold_p50 == 40.0
    assert by_purpose["conflict_repair"].warm_p50 is None


def test_count_run_errors_reads_error_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``.error.json`` files count per run provider without raising."""
    artifacts, _, _ = write_shadow_run(tmp_path)
    write_shadow_error(artifacts, provider="codex", seq=1)
    monkeypatch.setattr(
        "sase.core.instruction_manifest.normalize_instruction_manifest",
        lambda payload: payload,
    )
    counts = coverage_mod.count_run_errors([make_run("codex", "agent-j", artifacts)])
    assert counts == {"codex": 1}


def test_root_session_starts_from_provider_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Session starts come from each provider's own session records."""
    claude_dir = tmp_path / "claude"
    _write_claude_session(claude_dir, "root-k")
    monkeypatch.setattr(run_mod, "claude_project_dir", lambda _cwd: claude_dir)
    codex_root = tmp_path / "codex"
    day = codex_root / "2026" / "10" / "06"
    day.mkdir(parents=True)
    (day / "rollout-k.jsonl").write_text(
        json.dumps(
            {
                "type": "session_meta",
                "timestamp": SESSION_TS,
                "payload": {
                    "session_id": "k",
                    "timestamp": SESSION_TS,
                    "cwd": WORKSPACE,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(run_mod, "_codex_sessions_root", lambda: codex_root)
    grok_dir = tmp_path / "grok-cwd"
    grok_dir.mkdir(parents=True)
    session_dir = grok_dir / "session-k"
    session_dir.mkdir()
    (session_dir / "prompt_context.json").write_text(
        json.dumps({"working_directory": WORKSPACE, "build_timestamp_utc": SESSION_TS}),
        encoding="utf-8",
    )
    monkeypatch.setattr(run_mod, "_grok_cwd_dir", lambda _cwd: grok_dir)
    muse_log = tmp_path / "muse.jsonl"
    muse_log.write_text(json.dumps({"timestamp": SESSION_TS}) + "\n")
    muse_artifacts = tmp_path / "muse-run"
    muse_artifacts.mkdir()
    (muse_artifacts / "run_metadata.json").write_text(
        json.dumps({"muse_session_id": "muse-k"})
    )
    import sase.llm_provider._muse_session_usage as muse_usage

    monkeypatch.setattr(muse_usage, "find_muse_session_log", lambda _sid: muse_log)
    claude_artifacts = tmp_path / "claude-run"
    claude_artifacts.mkdir()
    runs = [
        make_run("claude", "agent-k", claude_artifacts),
        make_run("codex", "agent-k", tmp_path / "codex-run"),
        make_run("grok", "agent-k", tmp_path / "grok-run"),
        make_run("muse", "agent-k", muse_artifacts),
    ]
    sessions = coverage_mod.root_sessions(runs)
    by_provider = {item.provider: item for item in sessions}
    assert set(by_provider) == {"claude", "codex", "grok", "muse"}
    for item in sessions:
        assert item.session_start == datetime(2026, 10, 6, 12, 1, tzinfo=UTC)
