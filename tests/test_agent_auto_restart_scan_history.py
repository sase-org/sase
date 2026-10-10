"""History enumeration, wire round-trip, and CLI tests for the scan phase.

Split from ``tests.test_agent_auto_restart_scan``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.auto_restart.history import (
    FailedCandidate,
    collect_failed_candidates,
    _parse_local_stamp,
)
from tests._agent_auto_restart_scan_helpers import scan_facts

__all__ = [
    "test_collect_failed_candidates_filters_and_dedups",
    "test_collect_failed_candidates_keeps_unknown_time",
    "test_failure_facts_wire_round_trip",
    "test_handle_scan_empty_corpus",
    "test_handle_scan_json_emits_verdict_wires",
    "test_handle_scan_missing_binding",
    "test_handle_scan_rejects_bad_flags",
    "test_parse_local_stamp_variants",
    "test_parse_since_and_limit",
    "test_recovery_verdict_wire_to_dict",
]


def _write_done(
    artifacts_dir: Path, done: dict[str, Any], meta: dict[str, Any] | None = None
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")
    if meta is not None:
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )


def _history_tree(tmp_path: Path) -> tuple[Path, Path, Path, float]:
    now = datetime.datetime.now(datetime.UTC).timestamp()
    projects = tmp_path / "projects"
    recent_dir = projects / "proj" / "artifacts" / "ace-run" / "recent-row"
    _write_done(
        recent_dir,
        {
            "outcome": "failed",
            "finished_at": now - 3600,
            "name": "recent.agent",
            "cl_name": "proj",
            "error": "boom",
            "traceback": "",
        },
        {"name": "recent.agent"},
    )
    old_dir = projects / "proj" / "artifacts" / "ace-run" / "old-row"
    _write_done(
        old_dir,
        {
            "outcome": "failed",
            "finished_at": now - 30 * 86400,
            "name": "old.agent",
            "cl_name": "proj",
            "error": "old boom",
            "traceback": "",
        },
        {"name": "old.agent"},
    )
    done_dir = projects / "proj" / "artifacts" / "ace-run" / "done-row"
    _write_done(done_dir, {"outcome": "completed", "name": "ok.agent"})
    bundles = tmp_path / "dismissed_bundles"
    bundles.mkdir(parents=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    (bundles / f"{stamp}.json").write_text(
        json.dumps(
            {
                "status": "FAILED",
                "agent_name": "wiped.agent",
                "cl_name": "proj",
                "artifacts_dir": "/wiped/20200101000000",
                "error_message": "wiped boom",
                "error_traceback": "",
            }
        ),
        encoding="utf-8",
    )
    (bundles / f"{stamp}dup.json").write_text(
        json.dumps(
            {
                "status": "FAILED",
                "agent_name": "recent.agent",
                "cl_name": "proj",
                "artifacts_dir": str(recent_dir),
                "error_message": "duplicate boom",
                "error_traceback": "",
            }
        ),
        encoding="utf-8",
    )
    (bundles / f"{stamp}mon.json").write_text(
        json.dumps(
            {
                "status": "FAILED",
                "agent_name": "check.agent--mon",
                "agent_session_role": "monitor",
                "error_message": "exited with code 1",
                "error_traceback": "",
            }
        ),
        encoding="utf-8",
    )
    (bundles / f"{stamp}ok.json").write_text(
        json.dumps({"status": "DONE", "agent_name": "ok.agent"}),
        encoding="utf-8",
    )
    return projects, bundles, tmp_path / "workflows", now


def test_collect_failed_candidates_filters_and_dedups(tmp_path: Path) -> None:
    projects, bundles, workflows, _now = _history_tree(tmp_path)
    candidates = collect_failed_candidates(
        projects_root=projects,
        bundles_root=bundles,
        workflows_root=workflows,
        since_seconds=7 * 86400,
    )
    by_name = {candidate.name: candidate for candidate in candidates}
    assert "recent.agent" in by_name
    assert by_name["recent.agent"].source == "done"
    assert "wiped.agent" in by_name
    assert by_name["wiped.agent"].source == "bundle"
    assert "old.agent" not in by_name
    assert "ok.agent" not in by_name
    assert "check.agent--mon" not in by_name


def test_collect_failed_candidates_keeps_unknown_time(tmp_path: Path) -> None:
    projects, bundles, workflows, _now = _history_tree(tmp_path)
    (bundles / "mystery.json").write_text(
        json.dumps(
            {
                "status": "FAILED",
                "agent_name": "mystery.agent",
                "error_message": "mystery boom",
                "error_traceback": "",
            }
        ),
        encoding="utf-8",
    )
    candidates = collect_failed_candidates(
        projects_root=projects,
        bundles_root=bundles,
        workflows_root=workflows,
        since_seconds=7 * 86400,
    )
    assert "mystery.agent" in {candidate.name for candidate in candidates}


def test_parse_local_stamp_variants() -> None:
    assert _parse_local_stamp("20261009112914") is not None
    assert _parse_local_stamp("261009_112914") is not None
    assert _parse_local_stamp(1_700_000_000.0) is None
    assert _parse_local_stamp("") is None
    assert _parse_local_stamp("not-a-stamp") is None
    fourteen = _parse_local_stamp("20261009112914")
    twelve = _parse_local_stamp("261009_112914")
    assert fourteen is not None and twelve is not None
    assert abs(fourteen - twelve) < 1.0


def test_failure_facts_wire_round_trip() -> None:
    from sase.core.agent_auto_restart_wire import (
        agent_failure_facts_from_dict,
        agent_failure_facts_to_dict,
    )

    facts = agent_failure_facts_from_dict(scan_facts())
    assert facts is not None
    assert facts.import_error is not None
    assert facts.import_error.missing_symbol == "auto_launch_prefix"
    assert len(facts.exception_chain) == 1
    assert len(facts.frames) == 1
    assert agent_failure_facts_from_dict(None) is None
    assert agent_failure_facts_from_dict({}) is None
    assert agent_failure_facts_from_dict("nope") is None
    assert agent_failure_facts_to_dict(facts)["skew_suspect"] is True


def test_recovery_verdict_wire_to_dict() -> None:
    from sase.core.agent_auto_restart_wire import (
        RecoveryVerdictWire,
        recovery_verdict_to_dict,
    )

    verdict = RecoveryVerdictWire(
        tier="tier1_torn_python",
        family="cannot_import_name",
        signature="ImportError: cannot import name",
        origin_module="sase.monitor.continuation_delivery",
        missing_symbol="auto_launch_prefix",
        phase_class="pre_provider",
        mode="defer",
        reason="probe_pending",
        reason_text="waiting for the probe",
        witnesses_fired=("W1", "W2"),
        episode_id="sase@9fd8a08",
    )
    payload = recovery_verdict_to_dict(verdict)
    assert payload["mode"] == "defer"
    assert payload["witnesses_fired"] == ["W1", "W2"]
    assert payload["schema_version"] == 1


def _scan_args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "auto_restart_subcommand": "scan",
        "since": "7d",
        "limit": None,
        "json": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_parse_since_and_limit() -> None:
    from sase.agents.cli_auto_restart import _parse_limit, _parse_since_seconds

    assert _parse_since_seconds("7d") == 7 * 86400
    assert _parse_since_seconds("2w") == 2 * 604800
    assert _parse_since_seconds("90") == 90
    assert _parse_since_seconds("45m") == 2700
    with pytest.raises(ValueError):
        _parse_since_seconds("yesterday")
    with pytest.raises(ValueError):
        _parse_since_seconds("0d")
    assert _parse_limit(None) == 50
    assert _parse_limit("10") == 10
    with pytest.raises(ValueError):
        _parse_limit("0")
    with pytest.raises(ValueError):
        _parse_limit("many")


def test_handle_scan_rejects_bad_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.agents.cli_auto_restart import handle_agents_auto_restart

    args = _scan_args(since="yesterday")
    assert handle_agents_auto_restart(args) == 2
    args = _scan_args(limit="0")
    assert handle_agents_auto_restart(args) == 2
    args = argparse.Namespace(auto_restart_subcommand=None)
    assert handle_agents_auto_restart(args) == 2


def test_handle_scan_empty_corpus(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sase.agents.cli_auto_restart as cli
    import sase.core.agent_auto_restart_facade as facade

    monkeypatch.setattr(facade, "auto_restart_wire_schema_version", lambda: 1)
    monkeypatch.setattr(cli, "collect_managed_roots", lambda: ())
    monkeypatch.setattr(cli, "collect_failed_candidates", lambda **_: [])
    assert cli.handle_agents_auto_restart(_scan_args()) == 0
    out = capsys.readouterr().out
    assert "Scanned 0 failures" in out
    assert "ledger was not written" in out


def test_handle_scan_json_emits_verdict_wires(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sase.agents.cli_auto_restart as cli
    import sase.core.agent_auto_restart_facade as facade
    from sase.core.agent_auto_restart_wire import RecoveryVerdictWire

    artifacts_dir = tmp_path / "20261009112914"
    artifacts_dir.mkdir()
    candidate = FailedCandidate(
        source="done",
        name="legacy.agent",
        project="proj",
        died_at=None,
        artifacts_dir=artifacts_dir,
        done={
            "outcome": "failed",
            "name": "legacy.agent",
            "error": "ImportError: cannot import name 'x'",
            "traceback": "",
        },
        meta={},
        bundle=None,
        log_path=None,
    )
    monkeypatch.setattr(facade, "auto_restart_wire_schema_version", lambda: 1)
    monkeypatch.setattr(
        facade,
        "classify_agent_failure",
        lambda context, witnesses, facts=None: RecoveryVerdictWire(
            tier="tier1_torn_python",
            family="cannot_import_name",
            signature="ImportError: cannot import name",
            phase_class="unknown",
            mode="defer",
            reason="probe_pending",
            reason_text="waiting for the probe",
            witnesses_fired=("W2",),
        ),
    )
    monkeypatch.setattr(cli, "collect_managed_roots", lambda: ())
    monkeypatch.setattr(cli, "collect_failed_candidates", lambda **_: [candidate])
    assert cli.handle_agents_auto_restart(_scan_args(json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    result = payload["results"][0]
    assert result["name"] == "legacy.agent"
    assert result["verdict"]["mode"] == "defer"
    assert result["verdict"]["witnesses_fired"] == ["W2"]
    assert result["context"]["error_text"].startswith("ImportError")


def test_handle_scan_missing_binding(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sase.agents.cli_auto_restart as cli
    import sase.core.agent_auto_restart_facade as facade

    def _missing() -> int:
        raise AttributeError("no such binding")

    monkeypatch.setattr(facade, "auto_restart_wire_schema_version", _missing)
    assert cli.handle_agents_auto_restart(_scan_args()) == 1
    assert "unavailable" in capsys.readouterr().err
