"""Scoreboard manifest coverage, section diff, and doctor tests (E2 phase 6).

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
from typing import Any

import pytest

from sase.instructions import _runs as run_mod
from sase.instructions import coverage as coverage_mod
from sase.instructions._runs import ScoredRun
from sase.instructions.manifests import RunManifest
from tests.instructions.fixture_shadow import (
    fixture_bundle,
    write_shadow_error,
    write_shadow_run,
)

RENDERED = "2026-10-06T12:00:00Z"
COVERED_START = datetime(2026, 10, 6, 12, 1, tzinfo=UTC)
UNCOVERED_START = datetime(2026, 10, 6, 11, 59, tzinfo=UTC)
RUN_START = datetime(2026, 10, 6, 11, 0, tzinfo=UTC)
RUN_END = datetime(2026, 10, 6, 13, 0, tzinfo=UTC)
WORKSPACE = "/work/synthetic"
SESSION_TS = "2026-10-06T12:01:00Z"


def _run(
    provider: str,
    name: str,
    artifacts: Path,
    *,
    workspace: str = WORKSPACE,
    started_at: datetime = RUN_START,
) -> ScoredRun:
    return ScoredRun(
        provider=provider,
        name=name,
        workspace_dir=workspace,
        artifact_dir=str(artifacts),
        started_at=started_at,
        ended_at=RUN_END,
        project="fixture",
    )


def _record(manifest: dict[str, Any], artifacts: Path, seq: int = 0) -> Any:
    entry = RunManifest(
        seq=seq,
        provider=str(manifest["facts"]["provider"]),
        bundle_path=artifacts / "instructions" / f"{seq:02d}-x.md",
        manifest_path=artifacts / "instructions" / f"{seq:02d}-x.json",
        manifest=manifest,
    )
    record = coverage_mod.record_from_entry(entry, artifacts)
    assert record is not None
    return record


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
    record = _record(manifest, artifacts)
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
    record = _record(manifest, artifacts)
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
    record = _record(manifest, artifacts)
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
        _record(first, artifacts, seq=0),
        _record(second, artifacts, seq=1),
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
        _record(claude_manifest, artifacts, seq=0),
        _record(codex_manifest, artifacts, seq=1),
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
        _run("agy", "agent-f", covered_dir),
        _run("agy", "agent-g", bare_dir),
    ]
    records = [_record(covered_manifest, covered_dir)]
    verdicts = coverage_mod.cover_agy_runs(runs, records)
    assert [(item.run_name, item.covered) for item in verdicts] == [
        ("agent-f", True),
        ("agent-g", False),
    ]


def test_real_writer_round_trip_covers_and_diffs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real compiler output reads back valid and covers its session."""
    from tests.instructions.fixture_shadow import write_real_shadow_run

    monkeypatch.setenv("SASE_INSTRUCTIONS_HOME", str(tmp_path / "ihome"))
    artifacts, _, bundle = write_real_shadow_run(tmp_path, provider="claude")
    entries = coverage_mod.run_manifest_records(artifacts)
    assert len(entries) == 1
    record = entries[0]
    assert record.provider == "claude"
    assert record.rendered_at == datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    session = coverage_mod.RootSession(
        provider="claude",
        run_name="agent-real",
        artifact_dir=str(artifacts),
        workspace_dir=WORKSPACE,
        session_id="root-real",
        session_start=COVERED_START,
    )
    verdicts = coverage_mod.cover_sessions([session], entries)
    assert [item.covered for item in verdicts] == [True]
    manifest = dict(record.manifest)
    contract = _contract_body(bundle, manifest)
    claude_dir = tmp_path / "claude"
    _write_claude_diff_session(claude_dir, "root-real", [contract, contract])
    monkeypatch.setattr(run_mod, "claude_project_dir", lambda _cwd: claude_dir)
    run = _run("claude", "agent-real", artifacts)
    diff = coverage_mod.section_diff_for_session(session, run, entries)
    assert diff.unavailable is False
    assert all(row.layer != "frame" for row in diff.rows)
    contract_rows = [
        row
        for row in diff.rows
        if "final_declaration" in row.id and row.layer == "package"
    ]
    assert contract_rows
    assert all(row.observed == 2 and row.native == 2 for row in contract_rows)


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
    records = [_record(ordinary, artifacts, seq=0), _record(repair, artifacts, seq=1)]
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
    counts = coverage_mod.count_run_errors([_run("codex", "agent-j", artifacts)])
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
    monkeypatch.setattr(run_mod, "codex_sessions_root", lambda: codex_root)
    grok_dir = tmp_path / "grok-cwd"
    grok_dir.mkdir(parents=True)
    session_dir = grok_dir / "session-k"
    session_dir.mkdir()
    (session_dir / "prompt_context.json").write_text(
        json.dumps({"working_directory": WORKSPACE, "build_timestamp_utc": SESSION_TS}),
        encoding="utf-8",
    )
    monkeypatch.setattr(run_mod, "grok_cwd_dir", lambda _cwd: grok_dir)
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
        _run("claude", "agent-k", claude_artifacts),
        _run("codex", "agent-k", tmp_path / "codex-run"),
        _run("grok", "agent-k", tmp_path / "grok-run"),
        _run("muse", "agent-k", muse_artifacts),
    ]
    sessions = coverage_mod.root_sessions(runs)
    by_provider = {item.provider: item for item in sessions}
    assert set(by_provider) == {"claude", "codex", "grok", "muse"}
    for item in sessions:
        assert item.session_start == datetime(2026, 10, 6, 12, 1, tzinfo=UTC)


def _contract_body(bundle: str, manifest: dict[str, Any]) -> str:
    from sase.instructions import fingerprints as fp

    blob = bundle.encode("utf-8")
    for section in manifest["sections"]:
        if section["status"] != "included":
            continue
        body = blob[section["offset"] : section["offset"] + section["length"]]
        if fp.CONTRACT_HEADING in body.decode("utf-8"):
            return body.decode("utf-8")
    raise AssertionError("no contract section in fixture bundle")


def _write_claude_diff_session(directory: Path, stem: str, bodies: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    files = [
        {"path": f"/work/synthetic/CLAUDE-{index}.md", "content": body}
        for index, body in enumerate(bodies)
    ]
    lines = [
        json.dumps({"timestamp": SESSION_TS, "type": "marker"}),
        json.dumps(
            {
                "type": "attachment",
                "attachment": {"type": "instructions", "files": files},
            }
        ),
    ]
    (directory / f"{stem}.jsonl").write_text("\n".join(lines) + "\n")


def test_diff_contract_sections_observed_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claude contract sections show observed 2x; frame rows are skipped."""
    artifacts, manifest, bundle = write_shadow_run(tmp_path, provider="claude")
    record = _record(manifest, artifacts)
    contract = _contract_body(bundle, manifest)
    claude_dir = tmp_path / "claude"
    _write_claude_diff_session(claude_dir, "root-m", [contract, contract])
    monkeypatch.setattr(run_mod, "claude_project_dir", lambda _cwd: claude_dir)
    run = _run("claude", "agent-m", artifacts)
    session = coverage_mod.RootSession(
        provider="claude",
        run_name="agent-m",
        artifact_dir=str(artifacts),
        workspace_dir=WORKSPACE,
        session_id="root-m",
        session_start=COVERED_START,
    )
    diff = coverage_mod.section_diff_for_session(
        session, run, [record], bundle_text=bundle
    )
    assert diff.unavailable is False
    assert diff.purpose == "ordinary"
    assert all(row.layer != "frame" for row in diff.rows)
    contract_rows = [row for row in diff.rows if row.id == "pkg.root.final_declaration"]
    assert len(contract_rows) == 1
    assert contract_rows[0].observed == 2
    assert contract_rows[0].native == 2
    assert contract_rows[0].explicit == 0


def test_diff_muse_home_sections_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Muse native loads carry no home-layer bodies, so home rows read 0."""
    artifacts, manifest, bundle = write_shadow_run(tmp_path, provider="muse")
    record = _record(manifest, artifacts)
    contract = _contract_body(bundle, manifest)
    muse_log = tmp_path / "muse.jsonl"
    muse_log.write_text(
        "\n".join(
            [
                json.dumps({"timestamp": SESSION_TS}),
                json.dumps(
                    {
                        "payload": {
                            "source": "rules_file",
                            "text": contract,
                        }
                    }
                ),
            ]
        )
        + "\n"
    )
    (artifacts / "run_metadata.json").write_text(
        json.dumps({"muse_session_id": "muse-n"})
    )
    import sase.llm_provider._muse_session_usage as muse_usage

    monkeypatch.setattr(muse_usage, "find_muse_session_log", lambda _sid: muse_log)
    run = _run("muse", "agent-n", artifacts)
    session = coverage_mod.RootSession(
        provider="muse",
        run_name="agent-n",
        artifact_dir=str(artifacts),
        workspace_dir=WORKSPACE,
        session_id="muse-n",
        session_start=COVERED_START,
    )
    diff = coverage_mod.section_diff_for_session(
        session, run, [record], bundle_text=bundle
    )
    assert diff.unavailable is False
    home_rows = [row for row in diff.rows if row.layer == "home"]
    assert home_rows
    assert all(row.observed == 0 for row in home_rows)


def test_diff_grok_home_sections_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Grok native loads carry no home-layer bodies, so home rows read 0."""
    artifacts, manifest, bundle = write_shadow_run(tmp_path, provider="grok")
    record = _record(manifest, artifacts)
    contract = _contract_body(bundle, manifest)
    grok_dir = tmp_path / "grok-cwd"
    grok_dir.mkdir(parents=True)
    session_dir = grok_dir / "session-o"
    session_dir.mkdir()
    (session_dir / "prompt_context.json").write_text(
        json.dumps(
            {
                "working_directory": WORKSPACE,
                "build_timestamp_utc": SESSION_TS,
                "agents_md_files": [{"content": contract}],
            }
        )
    )
    (session_dir / "system_prompt.txt").write_text(
        "<human_rules>SASE single-turn instructions for Grok: fixture.</human_rules>"
    )
    monkeypatch.setattr(run_mod, "grok_cwd_dir", lambda _cwd: grok_dir)
    run = _run("grok", "agent-o", artifacts)
    session = coverage_mod.RootSession(
        provider="grok",
        run_name="agent-o",
        artifact_dir=str(artifacts),
        workspace_dir=WORKSPACE,
        session_id="session-o",
        session_start=COVERED_START,
    )
    diff = coverage_mod.section_diff_for_session(
        session, run, [record], bundle_text=bundle
    )
    assert diff.unavailable is False
    home_rows = [row for row in diff.rows if row.layer == "home"]
    assert home_rows
    assert all(row.observed == 0 for row in home_rows)


def test_diff_partial_and_missing_manifest_are_unavailable(
    tmp_path: Path,
) -> None:
    """Partial observations zero the counts; missing manifests stay empty."""
    artifacts, manifest, bundle = write_shadow_run(tmp_path)
    record = _record(manifest, artifacts)
    run = _run("codex", "agent-p", artifacts)
    session = coverage_mod.RootSession(
        provider="codex",
        run_name="agent-p",
        artifact_dir=str(artifacts),
        workspace_dir=WORKSPACE,
        session_id="rollout-p",
        session_start=COVERED_START,
    )
    partial = coverage_mod.section_diff_for_session(
        session, run, [record], partial=True, bundle_text=bundle
    )
    assert partial.unavailable is True
    assert partial.rows
    assert all(row.observed == 0 for row in partial.rows)
    missing = coverage_mod.section_diff_for_session(
        coverage_mod.RootSession(
            provider="codex",
            run_name="agent-p",
            artifact_dir=str(artifacts),
            workspace_dir=WORKSPACE,
            session_id="rollout-q",
            session_start=UNCOVERED_START,
        ),
        run,
        [record],
        bundle_text=bundle,
    )
    assert missing.unavailable is True
    assert missing.rows == ()
    assert missing.manifest_path is None


def test_diff_skips_frame_and_heading_only_sections() -> None:
    """Frame layers and heading-only bodies never become diff rows."""
    bundle = "## Frame\n\nFrame body.\n\n## Only Heading\n\n# Note\n\nBody.\n\n"
    frame_len = len(b"## Frame\n\nFrame body.\n\n")
    heading_len = len(b"## Only Heading\n\n")
    note_text = "# Note\n\nBody.\n\n"
    manifest = {
        "facts": {"provider": "codex", "purpose": "ordinary"},
        "delivery": {"rendered_at": RENDERED},
        "sections": [
            {
                "id": "frame.title",
                "layer": "frame",
                "status": "included",
                "offset": 0,
                "length": frame_len,
            },
            {
                "id": "pkg.sase.empty",
                "layer": "package",
                "status": "included",
                "offset": frame_len,
                "length": heading_len,
            },
            {
                "id": "proj.core.note",
                "layer": "project",
                "status": "included",
                "offset": frame_len + heading_len,
                "length": len(note_text.encode("utf-8")),
            },
        ],
    }
    record = coverage_mod.ManifestRecord(
        artifact_dir="/nonexistent",
        seq=0,
        provider="codex",
        purpose="ordinary",
        rendered_at=coverage_mod.parse_time(RENDERED),
        render_ms=None,
        cache=None,
        manifest_path="",
        manifest=manifest,
    )
    run = ScoredRun(
        provider="codex",
        name="agent-r",
        workspace_dir=WORKSPACE,
        artifact_dir="/nonexistent",
        started_at=RUN_START,
        ended_at=RUN_END,
        project=None,
    )
    session = coverage_mod.RootSession(
        provider="codex",
        run_name="agent-r",
        artifact_dir="/nonexistent",
        workspace_dir=WORKSPACE,
        session_id="rollout-r",
        session_start=COVERED_START,
    )
    diff = coverage_mod.section_diff_for_session(
        session, run, [record], bundle_text=bundle
    )
    assert [row.id for row in diff.rows] == ["proj.core.note"]


def _doctor_context(tmp_path: Path):
    from sase.doctor.runner import DoctorContext

    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")


def test_doctor_coverage_skips_without_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The coverage check SKIPs when the window holds no manifests."""
    from sase.doctor import checks_instructions
    from sase.instructions import _runs as run_mod

    monkeypatch.setattr(run_mod, "enumerate_runs", lambda **_kwargs: [])
    check = checks_instructions.check_instructions_coverage(_doctor_context(tmp_path))
    assert check.status == "SKIP"


def test_doctor_coverage_warns_on_uncovered_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The coverage check WARNs naming uncovered sessions and error runs."""
    from sase.doctor import checks_instructions
    from sase.instructions import _runs as run_mod
    from sase.instructions.manifests import RunManifest

    artifacts, manifest, _ = write_shadow_run(tmp_path, rendered_at=RENDERED)
    write_shadow_error(artifacts, provider="codex", seq=1)
    run = _run(
        "codex",
        "agent-s",
        artifacts,
        started_at=datetime(2026, 10, 6, 12, 30, tzinfo=UTC),
    )
    record = _record(manifest, artifacts)
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
    from sase.instructions import _runs as run_mod

    artifacts, manifest, _ = write_shadow_run(tmp_path, rendered_at=RENDERED)
    run = _run("codex", "agent-t", artifacts)
    record = _record(manifest, artifacts)
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
    record = _record(manifest, artifacts)
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
