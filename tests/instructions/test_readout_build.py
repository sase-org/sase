"""Readout aggregation tests (split from test_readout)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sase.instructions._readout_build import (
    _delivery_mode_for_dir,
    _is_excluded_run,
    _is_research_run,
)
from sase.instructions.readout import build_readout
from sase.instructions.run_index import ScoredRun
from tests.instructions._readout_support import (
    RUN_END,
    RUN_START,
    passthrough_manifest_normalize,
    write_done,
    write_meta,
)
from tests.instructions.fixture_shadow import write_shadow_run


@pytest.fixture(autouse=True)
def _passthrough_manifest_normalize(monkeypatch: pytest.MonkeyPatch) -> None:
    passthrough_manifest_normalize(monkeypatch)


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
    write_meta(main_dir, name="coder", provider="codex")
    write_done(main_dir)
    (main_dir / "final_submission.json").write_text("{}", encoding="utf-8")
    research_dir, _, _ = write_shadow_run(
        tmp_path, provider="codex", artifacts_dir=tmp_path / "research-run"
    )
    write_meta(research_dir, name="research.7.cdx", provider="codex")
    write_done(research_dir)
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
    write_meta(mon_dir, name="x--mon", provider="claude", role="monitor")
    write_done(mon_dir)
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
    write_meta(early, name="early", provider="muse")
    write_done(early)
    (early / "final_submission.json").write_text("{}", encoding="utf-8")
    late, _, _ = write_shadow_run(
        tmp_path, provider="muse", artifacts_dir=tmp_path / "late-run"
    )
    write_meta(late, name="late", provider="muse")
    write_done(late)
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
    write_meta(artifacts, name="old", provider="grok")
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
    write_meta(first, name="one", provider="codex")
    write_done(first)
    (first / "final_submission.json").write_text("{}", encoding="utf-8")
    second, _, _ = write_shadow_run(
        tmp_path, provider="codex", artifacts_dir=tmp_path / "second-run"
    )
    write_meta(second, name="two", provider="codex")
    write_done(second)
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
