"""Scoreboard section-diff tests (split from test_scoreboard_coverage).

Manifests and bundles come from :mod:`tests.instructions.fixture_shadow`
(wire-shaped ``NN-<provider>.md`` / ``.json`` pairs); session files are
synthetic provider records with controlled timestamps.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sase.instructions import run_index as run_mod
from sase.instructions import coverage as coverage_mod
from sase.instructions.run_index import ScoredRun
from tests.instructions._scoreboard_support import (
    COVERED_START,
    RENDERED,
    RUN_END,
    RUN_START,
    SESSION_TS,
    UNCOVERED_START,
    WORKSPACE,
    make_record,
    make_run,
)
from tests.instructions.fixture_shadow import write_shadow_run


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
    run = make_run("claude", "agent-real", artifacts)
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


def test_diff_contract_sections_observed_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claude contract sections show observed 2x; frame rows are skipped."""
    artifacts, manifest, bundle = write_shadow_run(tmp_path, provider="claude")
    record = make_record(manifest, artifacts)
    contract = _contract_body(bundle, manifest)
    claude_dir = tmp_path / "claude"
    _write_claude_diff_session(claude_dir, "root-m", [contract, contract])
    monkeypatch.setattr(run_mod, "claude_project_dir", lambda _cwd: claude_dir)
    run = make_run("claude", "agent-m", artifacts)
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
    record = make_record(manifest, artifacts)
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
    run = make_run("muse", "agent-n", artifacts)
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
    record = make_record(manifest, artifacts)
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
    run = make_run("grok", "agent-o", artifacts)
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
    record = make_record(manifest, artifacts)
    run = make_run("codex", "agent-p", artifacts)
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
