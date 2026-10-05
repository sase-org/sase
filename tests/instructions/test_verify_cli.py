"""CLI, windowing, capping, schema, and doctor tests for the scoreboard."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sase.doctor.runner import DoctorContext, build_doctor_registry
from sase.instructions import _runs as run_mod
from sase.instructions.models import ProviderRow, SessionObservation, VerifyReport
from sase.instructions.render import report_to_json_dict
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
    payload = report_to_json_dict(_report(), include_observations=False)
    assert payload["schema_version"] == 1
    assert payload["generated_at"] == "2026-10-01T00:00:00+00:00"
    assert payload["filters"] == {"limit": 20}
    assert payload["providers"][0]["provider"] == "codex"
    assert "observations" not in payload

    detailed = report_to_json_dict(_report(), include_observations=True)
    assert detailed["observations"][0]["contract_count"] == 2


def test_window_excludes_later_run_sessions_in_same_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later run's Codex sessions never leak into an earlier run's window."""
    from sase.instructions._runs import ScoredRun

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
    monkeypatch.setattr(run_mod, "codex_sessions_root", lambda: sessions_root)
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
        run_mod.grok_cwd_dir("/work/synthetic/").name
        == run_mod.grok_cwd_dir("/work/synthetic").name
    )


def test_parse_when_accepts_durations_and_iso() -> None:
    """``--since``/``--until`` accept durations and ISO timestamps."""
    now = datetime(2026, 10, 5, tzinfo=UTC)
    assert run_mod.parse_when("24h", now=now) == now - timedelta(hours=24)
    assert run_mod.parse_when("7d", now=now) == now - timedelta(days=7)
    assert run_mod.parse_when("2026-10-01T00:00:00Z", now=now) == datetime(
        2026, 10, 1, tzinfo=UTC
    )


def test_doctor_registry_includes_instructions_deep_checks(tmp_path: Path) -> None:
    """Both scoreboard IDs join the deep set."""
    context = DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")
    registry = build_doctor_registry(context)
    deep_ids = {spec.id for spec in registry.list_deep_checks()}
    assert {"instructions.delivery", "instructions.helpers"} <= deep_ids


def test_doctor_delivery_skips_without_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The delivery check SKIPs when there are no runs."""
    from sase.doctor import checks_instructions

    monkeypatch.setattr(run_mod, "enumerate_runs", lambda **_kwargs: [])
    context = DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")
    check = checks_instructions.check_instructions_delivery(context)
    assert check.status == "SKIP"


def test_doctor_helpers_warns_on_accepted_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The helpers check WARNs on any accepted helper declaration."""
    from sase.doctor import checks_instructions
    from sase.instructions._runs import ScoredRun

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
    check = checks_instructions.check_instructions_helpers(context)
    assert check.status == "WARN"
