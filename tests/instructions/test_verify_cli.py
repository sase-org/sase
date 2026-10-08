"""CLI, windowing, capping, schema, and doctor tests for the scoreboard."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sase.doctor.runner import DoctorContext, build_doctor_registry
from sase.instructions import run_index as run_mod
from sase.instructions.models import ProviderRow, SessionObservation, VerifyReport
from sase.instructions.render import _report_to_json_dict
from sase.main.parser import create_parser
from tests.main.parser_help_helpers import flat_help, parser_for


def _report() -> VerifyReport:
    observations = (
        SessionObservation(
            provider="codex",
            run_name="synthetic",
            session_id="rollout",
            contract_count=2,
            home=True,
            project=True,
            directive=True,
            native_full_count=2,
        ),
    )
    rows = (
        ProviderRow(
            provider="codex",
            runs=1,
            sessions=1,
            contract="2×",
            home="✓",
            project="✓",
            directive="✓",
            native_full="2",
            foreign="—",
            helpers="0 spawns",
        ),
    )
    return VerifyReport(
        provider_rows=rows,
        observations=observations,
        filters={"limit": 20},
        generated_at="2026-10-01T00:00:00+00:00",
    )


def test_verify_parser_options_are_alphabetical_with_short_aliases() -> None:
    """Every ``verify`` value-taking option keeps its short alias."""
    args = create_parser().parse_args(
        [
            "instructions",
            "verify",
            "-a",
            "some-agent",
            "-c",
            "-H",
            "-j",
            "-n",
            "5",
            "-p",
            "codex",
            "-p",
            "claude",
            "-s",
            "24h",
            "-u",
            "2026-10-02T00:00:00Z",
        ]
    )
    assert args.instructions_subcommand == "verify"
    assert args.agent == "some-agent"
    assert args.coverage is True
    assert args.helpers is True
    assert args.json is True
    assert args.limit == 5
    assert args.provider == ["codex", "claude"]
    assert args.since == "24h"
    assert args.until == "2026-10-02T00:00:00Z"


def test_verify_help_documents_flags() -> None:
    """``verify -h`` names every option and the reporting contract."""
    help_text = flat_help(parser_for(("sase", "instructions", "verify")).format_help())
    for flag in (
        "-a, --agent",
        "-c, --coverage",
        "-H, --helpers",
        "-j, --json",
        "-n, --limit",
        "-p, --provider",
        "-s, --since",
        "-u, --until",
    ):
        assert flag in help_text
    assert "reports; it does not gate" in help_text


def test_json_schema_shape() -> None:
    """``-j`` prints ``schema_version: 1`` with filters and provider rows."""
    payload = _report_to_json_dict(_report(), include_observations=False)
    assert payload["schema_version"] == 1
    assert payload["generated_at"] == "2026-10-01T00:00:00+00:00"
    assert payload["filters"] == {"limit": 20}
    assert payload["providers"][0]["provider"] == "codex"
    assert "observations" not in payload

    detailed = _report_to_json_dict(_report(), include_observations=True)
    assert detailed["observations"][0]["contract_count"] == 2


def test_window_excludes_later_run_sessions_in_same_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later run's Codex sessions never leak into an earlier run's window."""
    from sase.instructions.run_index import ScoredRun

    sessions_root = tmp_path / "sessions"
    day = sessions_root / "2026" / "10" / "01"
    day.mkdir(parents=True)
    early = {
        "timestamp": "2026-10-01T12:00:00Z",
        "ordinal": 0,
        "type": "session_meta",
        "payload": {
            "session_id": "early",
            "timestamp": "2026-10-01T12:00:00Z",
            "cwd": "/work/synthetic",
        },
    }
    late = {
        "timestamp": "2026-10-01T15:00:00Z",
        "ordinal": 0,
        "type": "session_meta",
        "payload": {
            "session_id": "late",
            "timestamp": "2026-10-01T15:00:00Z",
            "cwd": "/work/synthetic",
        },
    }
    (day / "rollout-early.jsonl").write_text(json.dumps(early) + "\n", encoding="utf-8")
    (day / "rollout-late.jsonl").write_text(json.dumps(late) + "\n", encoding="utf-8")
    monkeypatch.setattr(run_mod, "_codex_sessions_root", lambda: sessions_root)
    run = ScoredRun(
        provider="codex",
        name="synthetic",
        workspace_dir="/work/synthetic",
        artifact_dir="/work/synthetic",
        started_at=datetime(2026, 10, 1, 11, 0, tzinfo=UTC),
        ended_at=datetime(2026, 10, 1, 13, 0, tzinfo=UTC),
        project=None,
    )
    matches = run_mod.find_codex_sessions(run)
    assert [path.stem for path in matches] == ["rollout-early"]


def test_capped_reads_are_marked_partial(tmp_path: Path) -> None:
    """Any capped observation is marked ``partial``."""
    path = tmp_path / "transcript.jsonl"
    path.write_text('{"type": "user"}\n' * 100, encoding="utf-8")
    records, partial = run_mod.read_jsonl_capped(path, max_bytes=10)
    assert partial is True
    assert records == []

    text_path = tmp_path / "prompt.txt"
    text_path.write_text("x" * 100, encoding="utf-8")
    text, text_partial = run_mod.read_text_capped(text_path, max_bytes=10)
    assert text_partial is True
    assert len(text) == 10


def test_session_roots_ignore_trailing_slash(tmp_path: Path) -> None:
    """Run workspace dirs carry a trailing slash; session roots do not."""
    assert (
        run_mod.claude_project_dir("/work/synthetic/").name
        == run_mod.claude_project_dir("/work/synthetic").name
    )
    assert (
        run_mod._grok_cwd_dir("/work/synthetic/").name
        == run_mod._grok_cwd_dir("/work/synthetic").name
    )


def test_parse_when_accepts_durations_and_iso() -> None:
    """``--since``/``--until`` accept durations and ISO timestamps."""
    now = datetime(2026, 10, 5, tzinfo=UTC)
    assert run_mod.parse_when("30m", now=now) == now - timedelta(minutes=30)
    assert run_mod.parse_when("24h", now=now) == now - timedelta(hours=24)
    assert run_mod.parse_when("7d", now=now) == now - timedelta(days=7)
    assert run_mod.parse_when("2w", now=now) == now - timedelta(weeks=2)
    assert run_mod.parse_when("2026-10-01T00:00:00Z", now=now) == datetime(
        2026, 10, 1, tzinfo=UTC
    )
    with pytest.raises(ValueError):
        run_mod.parse_when("24", now=now)
    with pytest.raises(ValueError):
        run_mod.parse_when("30months", now=now)


def test_verify_rejects_bare_since_with_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A bare ``-s 24`` is a clean CLI error (exit 2), not a traceback."""
    from sase.main.instructions_handler import _run_instructions_verify
    from sase.main.parser import create_parser

    args = create_parser().parse_args(["instructions", "verify", "-s", "24"])
    assert _run_instructions_verify(args) == 2
    captured = capsys.readouterr()
    assert "invalid --since/--until value" in captured.err


def test_enumerate_runs_queries_each_provider_with_candidate_filter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``enumerate_runs`` issues one bounded query per wanted provider."""
    from sase.core.agent_scan_wire import (
        AgentArtifactScanOptionsWire,
        AgentArtifactScanStatsWire,
        AgentArtifactScanWire,
    )

    calls: list[dict[str, object]] = []

    def fake_listing_snapshot(
        *,
        project: str | None = None,
        requested_limit: int | None = None,
        candidate_filter: dict[str, object] | None = None,
        **_kwargs: object,
    ) -> tuple[AgentArtifactScanWire, object]:
        calls.append(
            {
                "project": project,
                "requested_limit": requested_limit,
                "candidate_filter": candidate_filter,
            }
        )
        return (
            AgentArtifactScanWire(
                schema_version=1,
                projects_root=str(tmp_path),
                options=AgentArtifactScanOptionsWire(),
                stats=AgentArtifactScanStatsWire(),
                records=[],
            ),
            object(),
        )

    monkeypatch.setattr(
        "sase.agent.listing_snapshot.listing_snapshot", fake_listing_snapshot
    )
    run_mod.enumerate_runs(
        limit_per_provider=10,
        since=None,
        until=None,
        project="sase",
        agent=None,
        providers=("grok", "codex"),
    )
    assert len(calls) == 2
    assert calls[0]["candidate_filter"] == {
        "kind": "equals",
        "field": "provider",
        "value": "grok",
    }
    assert calls[1]["candidate_filter"] == {
        "kind": "equals",
        "field": "provider",
        "value": "codex",
    }
    assert calls[0]["requested_limit"] == 10
    assert calls[0]["project"] == "sase"


def test_enumerate_runs_widens_limit_when_filtered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Agent/since/until post-filters raise the per-provider query to 200."""
    from sase.core.agent_scan_wire import (
        AgentArtifactScanOptionsWire,
        AgentArtifactScanStatsWire,
        AgentArtifactScanWire,
    )

    seen: list[int | None] = []

    def fake_listing_snapshot(
        *,
        requested_limit: int | None = None,
        **_kwargs: object,
    ) -> tuple[AgentArtifactScanWire, object]:
        seen.append(requested_limit)
        return (
            AgentArtifactScanWire(
                schema_version=1,
                projects_root=str(tmp_path),
                options=AgentArtifactScanOptionsWire(),
                stats=AgentArtifactScanStatsWire(),
                records=[],
            ),
            object(),
        )

    monkeypatch.setattr(
        "sase.agent.listing_snapshot.listing_snapshot", fake_listing_snapshot
    )
    now = datetime(2026, 10, 5, tzinfo=UTC)
    run_mod.enumerate_runs(
        limit_per_provider=10,
        since=now - timedelta(hours=1),
        until=None,
        project=None,
        agent=None,
        providers=("claude",),
    )
    assert seen == [200]
    seen.clear()
    run_mod.enumerate_runs(
        limit_per_provider=10,
        since=None,
        until=None,
        project=None,
        agent="some-agent",
        providers=("claude",),
    )
    assert seen == [200]


def test_enumerate_runs_finds_rare_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``-p grok`` returns Grok runs even when newest overall runs differ."""
    from sase.core.agent_scan_wire import (
        AgentArtifactRecordWire,
        AgentArtifactScanOptionsWire,
        AgentArtifactScanStatsWire,
        AgentArtifactScanWire,
        AgentMetaWire,
    )

    grok_record = AgentArtifactRecordWire(
        project_name="sase",
        project_dir=str(tmp_path),
        project_file=str(tmp_path / "sase.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / "grok-run"),
        timestamp="2026-10-01T12:00:00Z",
        agent_meta=AgentMetaWire(
            name="grok-run",
            llm_provider="grok",
            workspace_dir="/work/synthetic",
        ),
    )
    (tmp_path / "grok-run").mkdir(parents=True, exist_ok=True)
    (tmp_path / "grok-run" / "agent_meta.json").write_text(
        json.dumps(
            {
                "workspace_dir": "/work/synthetic",
                "name": "grok-run",
                "run_started_at": "2026-10-01T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    def fake_listing_snapshot(
        *,
        candidate_filter: dict[str, object] | None = None,
        **_kwargs: object,
    ) -> tuple[AgentArtifactScanWire, object]:
        records = []
        if candidate_filter is not None and candidate_filter.get("value") == "grok":
            records = [grok_record]
        return (
            AgentArtifactScanWire(
                schema_version=1,
                projects_root=str(tmp_path),
                options=AgentArtifactScanOptionsWire(),
                stats=AgentArtifactScanStatsWire(),
                records=records,
            ),
            object(),
        )

    monkeypatch.setattr(
        "sase.agent.listing_snapshot.listing_snapshot", fake_listing_snapshot
    )
    scored = run_mod.enumerate_runs(
        limit_per_provider=10,
        since=None,
        until=None,
        project=None,
        agent=None,
        providers=("grok",),
    )
    assert [run.provider for run in scored] == ["grok"]


def test_listing_snapshot_ands_candidate_filter_with_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller ``candidate_filter`` is ANDed with the project filter."""
    from sase.agent.listing_snapshot import listing_snapshot
    from sase.core.agent_scan_wire import (
        AgentArtifactIndexQueryWire,
        AgentArtifactScanOptionsWire,
        AgentArtifactScanStatsWire,
        AgentArtifactScanWire,
    )

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = AgentArtifactScanWire(
        schema_version=1,
        projects_root=str(tmp_path),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[],
    )
    seen: list[AgentArtifactIndexQueryWire] = []

    def fake_query(
        path: Path,
        projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        seen.append(query)
        return snapshot

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(
        "sase.core.agent_scan_facade.query_agent_artifact_index_bounded",
        fake_query,
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot.sase_projects_dir", lambda: tmp_path
    )
    listing_snapshot(
        project="sase",
        requested_limit=10,
        candidate_filter={"kind": "equals", "field": "provider", "value": "grok"},
    )
    assert seen[0].candidate_filter == {
        "kind": "all",
        "filters": [
            {"kind": "equals", "field": "project", "value": "sase"},
            {"kind": "equals", "field": "provider", "value": "grok"},
        ],
    }


def test_doctor_registry_includes_instructions_deep_checks(tmp_path: Path) -> None:
    """All scoreboard IDs join the deep set."""
    context = DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")
    registry = build_doctor_registry(context)
    deep_ids = {spec.id for spec in registry.list_deep_checks()}
    assert {
        "instructions.delivery",
        "instructions.helpers",
        "instructions.coverage",
    } <= deep_ids


def test_doctor_delivery_skips_without_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The delivery check SKIPs when there are no runs."""
    from sase.doctor import checks_instructions

    monkeypatch.setattr(run_mod, "enumerate_runs", lambda **_kwargs: [])
    context = DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")
    check = checks_instructions._check_instructions_delivery(context)
    assert check.status == "SKIP"


def test_doctor_helpers_warns_on_accepted_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The helpers check WARNs on any accepted helper declaration."""
    from sase.doctor import checks_instructions
    from sase.instructions.run_index import ScoredRun

    run = ScoredRun(
        provider="claude",
        name="synthetic",
        workspace_dir="/work/synthetic",
        artifact_dir="/work/synthetic",
        started_at=datetime(2026, 10, 1, tzinfo=UTC),
        ended_at=None,
        project=None,
    )
    accepted = SessionObservation(
        provider="claude",
        run_name="synthetic",
        session_id="root/agent-gp",
        contract_count=2,
        helper_type="general-purpose",
        final_attempts=1,
        final_accepted=1,
    )
    monkeypatch.setattr(run_mod, "enumerate_runs", lambda **_kwargs: [run])
    monkeypatch.setattr(
        "sase.instructions.verify.collect_observations", lambda _runs: [accepted]
    )
    context = DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")
    check = checks_instructions._check_instructions_helpers(context)
    assert check.status == "WARN"


def test_doctor_helpers_ignores_root_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root's own accepted submit never WARNs as a helper declaration."""
    from sase.doctor import checks_instructions
    from sase.instructions.run_index import ScoredRun

    run = ScoredRun(
        provider="claude",
        name="synthetic",
        workspace_dir="/work/synthetic",
        artifact_dir="/work/synthetic",
        started_at=datetime(2026, 10, 1, tzinfo=UTC),
        ended_at=None,
        project=None,
    )
    root = SessionObservation(
        provider="claude",
        run_name="synthetic",
        session_id="root",
        contract_count=2,
        helper_type=None,
        final_attempts=1,
        final_accepted=1,
    )
    monkeypatch.setattr(run_mod, "enumerate_runs", lambda **_kwargs: [run])
    monkeypatch.setattr(
        "sase.instructions.verify.collect_observations", lambda _runs: [root]
    )
    context = DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")
    check = checks_instructions._check_instructions_helpers(context)
    assert check.status == "OK"


def test_doctor_helpers_warns_on_root_guard_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root guard denial WARNs even with no accepted declaration."""
    from sase.doctor import checks_instructions
    from sase.instructions.run_index import ScoredRun

    run = ScoredRun(
        provider="claude",
        name="synthetic",
        workspace_dir="/work/synthetic",
        artifact_dir="/work/synthetic",
        started_at=datetime(2026, 10, 1, tzinfo=UTC),
        ended_at=None,
        project=None,
    )
    denied_root = SessionObservation(
        provider="claude",
        run_name="synthetic",
        session_id="root",
        contract_count=2,
        helper_type=None,
        root_guard_denial=True,
    )
    monkeypatch.setattr(run_mod, "enumerate_runs", lambda **_kwargs: [run])
    monkeypatch.setattr(
        "sase.instructions.verify.collect_observations", lambda _runs: [denied_root]
    )
    context = DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")
    check = checks_instructions._check_instructions_helpers(context)
    assert check.status == "WARN"
