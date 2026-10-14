"""Hidden-run enumeration, named-agent resolution, and helper manifests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sase.agent.names._common import NamedAgent
from sase.instructions import coverage as coverage_mod
from sase.instructions import run_index as run_mod
from sase.instructions.manifests import read_run_manifests
from sase.instructions.run_index import UnknownAgentError
from sase.main.instructions_handler import (
    _agent_base_facts,
    _run_instructions_render,
    _run_instructions_verify,
)
from sase.main.parser import create_parser
from tests.instructions._scoreboard_support import COVERED_START, WORKSPACE, make_record
from tests.instructions.fixture_shadow import write_helper_shadow, write_shadow_run


@pytest.fixture(autouse=True)
def _passthrough_manifest_normalize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.core.instruction_manifest.normalize_instruction_manifest",
        lambda payload: payload,
    )


def _named(name: str, artifacts: Path) -> NamedAgent:
    return NamedAgent(
        name=name, artifacts_dir=str(artifacts), is_done=True, outcome="dismissed"
    )


def _write_agent_meta(
    artifacts: Path,
    *,
    name: str,
    provider: str,
    started_at: str,
    manifest: dict[str, object] | None = None,
) -> None:
    latest: dict[str, object] | None = None
    if manifest is not None:
        bundle = (
            manifest.get("bundle") if isinstance(manifest.get("bundle"), dict) else {}
        )
        delivery = (
            manifest.get("delivery")
            if isinstance(manifest.get("delivery"), dict)
            else {}
        )
        latest = {
            "seq": delivery.get("invocation_seq", 0),
            "provider": provider,
            "purpose": "ordinary",
            "sha256": bundle.get("sha256") if isinstance(bundle, dict) else "",
            "common_digest": bundle.get("common_digest")
            if isinstance(bundle, dict)
            else "",
            "manifest": f"instructions/00-{provider}.json",
        }
    payload = {
        "name": name,
        "llm_provider": provider,
        "workspace_dir": WORKSPACE,
        "run_started_at": started_at,
    }
    if latest is not None:
        payload["instructions"] = {"count": 1, "latest": latest}
    (artifacts / "agent_meta.json").write_text(json.dumps(payload), encoding="utf-8")


def test_read_run_manifests_returns_helper_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Helper files are separate records linked by parent_invocation_id."""
    monkeypatch.setattr(
        "sase.core.instruction_manifest.normalize_instruction_manifest",
        lambda payload: payload,
    )
    artifacts, root, _ = write_shadow_run(tmp_path, provider="claude")
    parent_id = str(root["delivery"]["invocation_id"])
    helper, _ = write_helper_shadow(
        artifacts, provider="claude", parent_invocation_id=parent_id
    )
    records = read_run_manifests(artifacts)
    assert [record.is_helper for record in records] == [False, True]
    assert records[0].seq == records[1].seq == 0
    assert records[1].actor == "native_helper"
    assert records[1].parent_invocation_id == parent_id
    assert records[1].manifest is not None
    assert records[1].manifest["facts"]["actor"] == "native_helper"
    assert records[1].manifest["delivery"]["status"] == "explicit"
    assert helper["delivery"]["parent_invocation_id"] == parent_id


def test_helper_manifests_do_not_cover_root_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root session matching ignores native_helper records."""
    monkeypatch.setattr(
        "sase.core.instruction_manifest.normalize_instruction_manifest",
        lambda payload: payload,
    )
    artifacts, root, _ = write_shadow_run(tmp_path, provider="claude")
    write_helper_shadow(
        artifacts,
        provider="claude",
        parent_invocation_id=str(root["delivery"]["invocation_id"]),
    )
    records = [
        record
        for record in (
            coverage_mod.record_from_entry(entry, artifacts)
            for entry in read_run_manifests(artifacts)
        )
        if record is not None
    ]
    session = coverage_mod.RootSession(
        provider="claude",
        run_name="agent-h",
        artifact_dir=str(artifacts),
        workspace_dir=WORKSPACE,
        session_id="root",
        session_start=COVERED_START,
    )
    matches = coverage_mod.matching_manifests(session, records)
    assert [item.is_helper for item in matches] == [False]
    assert all(item.actor != "native_helper" for item in matches)


def test_enumerate_runs_named_agent_skips_since_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An explicit name is not dropped by ``--since`` and skips the listing."""
    artifacts, manifest, _ = write_shadow_run(tmp_path, provider="codex")
    _write_agent_meta(
        artifacts,
        name="old.dismissed",
        provider="codex",
        started_at="2026-01-01T00:00:00Z",
        manifest=manifest,
    )
    listing_calls: list[object] = []

    def fail_listing(**kwargs: object) -> None:
        listing_calls.append(kwargs)
        raise AssertionError("listing_snapshot must not run for a named agent")

    monkeypatch.setattr(
        "sase.agent.listing_snapshot.listing_snapshot",
        fail_listing,
    )
    monkeypatch.setattr(
        "sase.agent.names.find_named_agent",
        lambda name, **_kwargs: _named(name, artifacts),
    )
    now = datetime(2026, 10, 5, tzinfo=UTC)
    scored = run_mod.enumerate_runs(
        limit_per_provider=10,
        since=now - timedelta(days=7),
        until=None,
        project=None,
        agent="old.dismissed",
        providers=(),
    )
    assert listing_calls == []
    assert [run.name for run in scored] == ["old.dismissed"]
    assert scored[0].artifact_dir == str(artifacts)


def test_enumerate_runs_unknown_agent_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A name that resolves to nothing is an error, not an empty listing."""
    monkeypatch.setattr("sase.agent.names.find_named_agent", lambda name, **_k: None)
    with pytest.raises(UnknownAgentError, match="unknown agent missing"):
        run_mod.enumerate_runs(
            limit_per_provider=10,
            since=None,
            until=None,
            project=None,
            agent="missing",
            providers=(),
        )


def test_verify_unknown_agent_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``verify -a`` prints ``unknown agent NAME`` and exits 2."""
    monkeypatch.setattr("sase.agent.names.find_named_agent", lambda name, **_k: None)
    args = create_parser().parse_args(["instructions", "verify", "-a", "nope"])
    assert _run_instructions_verify(args) == 2
    assert "unknown agent nope" in capsys.readouterr().err


def test_render_unknown_agent_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``render -a`` uses the same unknown-agent failure."""
    monkeypatch.setattr("sase.agent.names.find_named_agent", lambda name, **_k: None)
    args = create_parser().parse_args(["instructions", "render", "-a", "nope"])
    assert _run_instructions_render(args) == 2
    assert "unknown agent nope" in capsys.readouterr().err


def test_purpose_denominator_excludes_other_purpose_sessions(
    tmp_path: Path,
) -> None:
    """Ordinary sessions are not uncovered for declaration_recovery."""
    artifacts, ordinary, _ = write_shadow_run(tmp_path, purpose="ordinary", seq=0)
    _, recovery, _ = write_shadow_run(
        tmp_path,
        purpose="declaration_recovery",
        seq=1,
        artifacts_dir=artifacts,
        rendered_at="2026-10-06T12:02:00Z",
    )
    records = [
        make_record(ordinary, artifacts, seq=0),
        make_record(recovery, artifacts, seq=1),
    ]
    sessions = [
        coverage_mod.RootSession(
            provider="codex",
            run_name="ordinary-run",
            artifact_dir=str(artifacts),
            workspace_dir=WORKSPACE,
            session_id="sess-ordinary",
            session_start=COVERED_START,
        )
    ]
    rows = coverage_mod.purpose_coverage_rows(sessions, records)
    by_purpose = {row.purpose: row for row in rows}
    assert by_purpose["ordinary"].sessions == 1
    assert by_purpose["ordinary"].covered == 1
    assert by_purpose["declaration_recovery"].sessions == 0
    assert by_purpose["declaration_recovery"].covered == 0
    assert by_purpose["declaration_recovery"].uncovered == ()


def test_verify_finds_dismissed_named_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``verify -a`` finds a dismissed agent even when the listing is empty."""
    artifacts, manifest, _ = write_shadow_run(tmp_path, provider="codex")
    _write_agent_meta(
        artifacts,
        name="gone.agent",
        provider="codex",
        started_at="2026-10-01T12:00:00Z",
        manifest=manifest,
    )
    monkeypatch.setattr(
        "sase.agent.names.find_named_agent",
        lambda name, **_k: _named(name, artifacts),
    )
    monkeypatch.setattr(
        "sase.instructions.verify.collect_observations", lambda _runs: []
    )
    monkeypatch.setattr("sase.instructions.coverage.root_sessions", lambda _runs: [])
    args = create_parser().parse_args(
        ["instructions", "verify", "-a", "gone.agent", "-j"]
    )
    assert _run_instructions_verify(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["filters"]["agent"] == "gone.agent"
    by_provider = {row["provider"]: row for row in payload["providers"]}
    assert by_provider["codex"]["runs"] == 1


def test_render_finds_dismissed_named_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``render -a`` resolves a dismissed agent through ``find_named_agent``."""
    artifacts, manifest, _ = write_shadow_run(tmp_path, provider="codex")
    _write_agent_meta(
        artifacts,
        name="gone.render",
        provider="codex",
        started_at="2026-10-01T12:00:00Z",
        manifest=manifest,
    )
    monkeypatch.setattr(
        "sase.agent.names.find_named_agent",
        lambda name, **_k: _named(name, artifacts),
    )
    facts, recorded = _agent_base_facts("gone.render", project_root=tmp_path)
    assert recorded is not None
    assert facts["provider"] == "codex"
    assert recorded["bundle"]["sha256"] == manifest["bundle"]["sha256"]
