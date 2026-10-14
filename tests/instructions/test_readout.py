"""Tests for ``sase instructions readout`` classification and aggregation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sase.instructions.readout import (
    ACCEPTED,
    MISS,
    MONITOR_PLAIN,
    MONITOR_PREPARED,
    NOT_REQUIRED,
    OTHER_HANDOFF,
    PLAN_HANDOFF,
    UNKNOWN,
    build_readout,
    _classify_artifact_dir,
    _delivery_mode_for_dir,
    _is_excluded_run,
    _is_research_run,
)
from sase.instructions.run_index import ScoredRun
from sase.main.parser import create_parser
from tests.instructions.fixture_shadow import write_shadow_run
from tests.main.parser_help_helpers import (
    assert_metavar_option_documented as _assert_metavar_option_documented,
)
from tests.main.parser_help_helpers import flat_help, parser_for

RUN_START = datetime(2026, 10, 6, 11, tzinfo=UTC)
RUN_END = datetime(2026, 10, 6, 13, tzinfo=UTC)


def _write_meta(
    artifacts: Path,
    *,
    name: str,
    provider: str,
    started_at: str = "2026-10-06T11:00:00Z",
    role: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "name": name,
        "llm_provider": provider,
        "workspace_dir": "/work/synthetic",
        "run_started_at": started_at,
    }
    if role is not None:
        payload["agent_session_role"] = role
    (artifacts / "agent_meta.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_done(artifacts: Path) -> None:
    (artifacts / "done.json").write_text(
        json.dumps({"outcome": "completed", "finished_at": 1791000000}),
        encoding="utf-8",
    )


def _make_run(
    provider: str,
    name: str,
    artifacts: Path,
    *,
    started_at: datetime = RUN_START,
) -> ScoredRun:
    return ScoredRun(
        provider=provider,
        name=name,
        workspace_dir="/work/synthetic",
        artifact_dir=str(artifacts),
        started_at=started_at,
        ended_at=RUN_END,
        project="fixture",
    )


@pytest.fixture(autouse=True)
def _passthrough_manifest_normalize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.core.instruction_manifest.normalize_instruction_manifest",
        lambda payload: payload,
    )


def test_readout_parser_options_are_alphabetical_with_short_aliases() -> None:
    """Every ``readout`` value-taking option keeps its short alias."""
    args = create_parser().parse_args(
        [
            "instructions",
            "readout",
            "-j",
            "-p",
            "codex",
            "-p",
            "claude",
            "-s",
            "7d",
            "-u",
            "2026-10-02T00:00:00Z",
        ]
    )
    assert args.instructions_subcommand == "readout"
    assert args.json is True
    assert args.provider == ["codex", "claude"]
    assert args.since == "7d"
    assert args.until == "2026-10-02T00:00:00Z"


def test_readout_help_documents_flags() -> None:
    """``readout -h`` names every option and the reporting contract."""
    help_text = flat_help(parser_for(("sase", "instructions", "readout")).format_help())
    assert "-j, --json" in help_text
    _assert_metavar_option_documented(help_text, "-p", "--provider", "PROVIDER")
    _assert_metavar_option_documented(help_text, "-s", "--since", "WHEN")
    _assert_metavar_option_documented(help_text, "-u", "--until", "WHEN")
    assert "reports; it does not gate" in help_text


def test_classify_accepted_beats_handoff(tmp_path: Path) -> None:
    """An accepted submission wins even when a monitor handoff also happened."""
    artifacts = tmp_path / "accepted"
    artifacts.mkdir()
    _write_meta(artifacts, name="acc", provider="codex")
    _write_done(artifacts)
    (artifacts / "final_submission.json").write_text(
        json.dumps({"accepted_at": "2026-10-06T12:00:00Z"}), encoding="utf-8"
    )
    (artifacts / "tool_calls.jsonl").write_text(
        "sase monitor start -p verify -- just check\n", encoding="utf-8"
    )
    assert _classify_artifact_dir(artifacts) == ACCEPTED


def test_classify_plan_handoff(tmp_path: Path) -> None:
    """``sase plan propose``, ``validate``, and ``decide`` are plan handoffs."""
    for marker in ("sase plan propose", "sase plan validate", "sase plan decide"):
        artifacts = tmp_path / f"plan-{marker.split()[-1]}"
        artifacts.mkdir()
        _write_meta(artifacts, name="pln", provider="muse")
        _write_done(artifacts)
        (artifacts / "tool_calls.jsonl").write_text(f"{marker}\n", encoding="utf-8")
        assert _classify_artifact_dir(artifacts) == PLAN_HANDOFF


def test_classify_monitor_prepared_needs_real_prepare(tmp_path: Path) -> None:
    """A prepared monitor needs a real prepare before the monitor start.

    A naive ``has final_submission.json`` check misses this case entirely:
    there is no submission, yet the run handed off through a prepared
    declaration. A bare ``-h`` help call never counts as the prepare.
    """
    artifacts = tmp_path / "prepared"
    artifacts.mkdir()
    _write_meta(artifacts, name="mon", provider="codex")
    _write_done(artifacts)
    (artifacts / "tool_calls.jsonl").write_text(
        "sase final prepare /tmp/wrapper.json -j\n"
        "sase monitor start -p verify -- just check\n",
        encoding="utf-8",
    )
    assert _classify_artifact_dir(artifacts) == MONITOR_PREPARED

    help_only = tmp_path / "help-only"
    help_only.mkdir()
    _write_meta(help_only, name="mon2", provider="codex")
    _write_done(help_only)
    (help_only / "tool_calls.jsonl").write_text(
        "sase final prepare -h\nsase monitor start -p verify -- just check\n",
        encoding="utf-8",
    )
    assert _classify_artifact_dir(help_only) == MONITOR_PLAIN


def test_classify_other_handoff(tmp_path: Path) -> None:
    """Pipe, questions, and handoff count as other recognized handoffs."""
    for marker in ("sase pipe", "sase questions", "sase handoff"):
        artifacts = tmp_path / f"other-{marker.split()[-1]}"
        artifacts.mkdir()
        _write_meta(artifacts, name="oth", provider="grok")
        _write_done(artifacts)
        (artifacts / "tool_calls.jsonl").write_text(f"{marker} ...\n", encoding="utf-8")
        assert _classify_artifact_dir(artifacts) == OTHER_HANDOFF


def test_classify_not_required(tmp_path: Path) -> None:
    """``submission_required: false`` in final_context means not required."""
    artifacts = tmp_path / "notreq"
    artifacts.mkdir()
    _write_meta(artifacts, name="nr", provider="claude")
    _write_done(artifacts)
    (artifacts / "final_context.json").write_text(
        json.dumps({"submission_required": False}), encoding="utf-8"
    )
    (artifacts / "tool_calls.jsonl").write_text("", encoding="utf-8")
    assert _classify_artifact_dir(artifacts) == NOT_REQUIRED


def test_classify_miss(tmp_path: Path) -> None:
    """No declaration, handoff, or waiver is a miss."""
    artifacts = tmp_path / "miss"
    artifacts.mkdir()
    _write_meta(artifacts, name="ms", provider="claude")
    _write_done(artifacts)
    (artifacts / "final_context.json").write_text(
        json.dumps({"submission_required": True}), encoding="utf-8"
    )
    (artifacts / "tool_calls.jsonl").write_text("sase bead read\n", encoding="utf-8")
    assert _classify_artifact_dir(artifacts) == MISS


def test_delivery_mode_split(tmp_path: Path) -> None:
    """Explicit, legacy (shadow), and pre-E2 (none) modes split correctly."""
    artifacts, manifest, _ = write_shadow_run(tmp_path, provider="codex")
    mode, _ = _delivery_mode_for_dir(artifacts)
    assert mode == "legacy"
    manifest["delivery"]["status"] = "explicit"
    manifest["delivery"]["channel"] = "codex.developer_instructions"
    (artifacts / "instructions" / "00-codex.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    mode, _ = _delivery_mode_for_dir(artifacts)
    assert mode == "explicit"
    inherits = tmp_path / "inherits"
    inherits.mkdir()
    (inherits / "instructions").mkdir()
    (inherits / "instructions" / "00-codex.json").write_text(
        json.dumps(
            {
                "facts": {"purpose": "ordinary"},
                "delivery": {"status": "inherits_native"},
            }
        ),
        encoding="utf-8",
    )
    mode, _ = _delivery_mode_for_dir(inherits)
    assert mode == "legacy"
    bare = tmp_path / "bare"
    bare.mkdir()
    mode, _ = _delivery_mode_for_dir(bare)
    assert mode == "none"


def test_build_readout_groups_modes_and_research(tmp_path: Path) -> None:
    """Rows split by provider × mode, with research in its own rows."""
    main_dir, _, _ = write_shadow_run(tmp_path, provider="codex")
    _write_meta(main_dir, name="coder", provider="codex")
    _write_done(main_dir)
    (main_dir / "final_submission.json").write_text("{}", encoding="utf-8")
    research_dir, _, _ = write_shadow_run(
        tmp_path, provider="codex", artifacts_dir=tmp_path / "research-run"
    )
    _write_meta(research_dir, name="research.7.cdx", provider="codex")
    _write_done(research_dir)
    scored = [
        _make_run("codex", "coder", main_dir),
        _make_run("codex", "research.7.cdx", research_dir),
    ]
    payload = build_readout(scored, since=None, until=None, providers=())
    assert payload["schema_version"] == 1
    rows = payload["rows"]
    assert all(r["provider"] == "codex" for r in rows)
    assert any(r["is_research"] is False for r in rows)
    assert any(r["is_research"] is True for r in rows)
    assert all(r["total"] == 1 for r in rows)


def test_build_readout_excludes_monitor_and_gate(tmp_path: Path) -> None:
    """Monitor and gate turns never enter the readout."""
    mon_dir = tmp_path / "mon"
    mon_dir.mkdir()
    _write_meta(mon_dir, name="x--mon", provider="claude", role="monitor")
    _write_done(mon_dir)
    assert _is_excluded_run({"agent_session_role": "monitor"}) is True
    assert _is_excluded_run({"role_suffix": "--gate"}) is True
    assert _is_research_run("research.1.cdx", {}) is True
    assert _is_research_run("coder", {}) is False
    scored = [_make_run("claude", "x--mon", mon_dir)]
    payload = build_readout(scored, since=None, until=None, providers=())
    assert payload["rows"] == []


def test_build_readout_window_bounds(tmp_path: Path) -> None:
    """Only runs with started_at inside [since, until] are counted."""
    from datetime import timedelta

    early, _, _ = write_shadow_run(tmp_path, provider="muse")
    _write_meta(early, name="early", provider="muse")
    _write_done(early)
    (early / "final_submission.json").write_text("{}", encoding="utf-8")
    late, _, _ = write_shadow_run(
        tmp_path, provider="muse", artifacts_dir=tmp_path / "late-run"
    )
    _write_meta(late, name="late", provider="muse")
    _write_done(late)
    scored = [
        _make_run("muse", "early", early, started_at=RUN_START),
        _make_run("muse", "late", late, started_at=RUN_START + timedelta(days=30)),
    ]
    payload = build_readout(
        scored,
        since=RUN_START - timedelta(hours=1),
        until=RUN_START + timedelta(hours=1),
        providers=(),
    )
    assert sum(r["total"] for r in payload["rows"]) == 1


def test_build_readout_missing_done_is_unknown(tmp_path: Path) -> None:
    """An old run without done.json counts as unknown, not a miss."""
    from datetime import timedelta

    artifacts = tmp_path / "old-nodone"
    artifacts.mkdir()
    _write_meta(artifacts, name="old", provider="grok")
    (artifacts / "tool_calls.jsonl").write_text("sase bead read\n", encoding="utf-8")
    old_start = datetime(2026, 9, 15, tzinfo=UTC)
    scored = [
        ScoredRun(
            provider="grok",
            name="old",
            workspace_dir="/work/synthetic",
            artifact_dir=str(artifacts),
            started_at=old_start,
            ended_at=None,
            project="fixture",
        )
    ]
    payload = build_readout(
        scored, since=old_start - timedelta(hours=1), until=None, providers=()
    )
    rows = [r for r in payload["rows"] if r["provider"] == "grok"]
    assert rows
    row = rows[0]
    assert row["unknown"] == 1
    assert row["miss"] == 0
    assert row["misses"].startswith("≤0/")


def test_build_readout_memory_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Memory reads join by artifacts_dir for mean and share columns."""
    from sase.core import paths as paths_mod

    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(paths_mod, "sase_projects_dir", lambda: projects)
    first, _, _ = write_shadow_run(tmp_path, provider="codex")
    _write_meta(first, name="one", provider="codex")
    _write_done(first)
    (first / "final_submission.json").write_text("{}", encoding="utf-8")
    second, _, _ = write_shadow_run(
        tmp_path, provider="codex", artifacts_dir=tmp_path / "second-run"
    )
    _write_meta(second, name="two", provider="codex")
    _write_done(second)
    log = projects / "proj" / "memory_reads.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(
        json.dumps(
            {
                "agent_name": "one",
                "artifacts_dir": str(first),
                "timestamp": "2026-10-06T12:00:00+00:00",
            }
        )
        + "\n"
        + json.dumps(
            {
                "agent_name": "one",
                "artifacts_dir": str(first),
                "timestamp": "2026-10-06T12:01:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    scored = [
        _make_run("codex", "one", first),
        _make_run("codex", "two", second),
    ]
    payload = build_readout(scored, since=None, until=None, providers=())
    row = next(r for r in payload["rows"] if r["provider"] == "codex")
    assert row["total"] == 2
    assert row["memory_mean"] == 1.0
    assert row["memory_share"] == 0.5


def test_readout_rejects_bad_since() -> None:
    """A bare ``-s 24`` is a clean CLI error (exit 2), not a traceback."""
    from sase.main.instructions_handler import _run_instructions_readout

    args = create_parser().parse_args(["instructions", "readout", "-s", "24"])
    assert _run_instructions_readout(args) == 2
