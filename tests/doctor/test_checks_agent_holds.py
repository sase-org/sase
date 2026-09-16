"""OK / WARN fixtures for the ``agent_holds.*`` doctor checks."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.core.agent_hold_facade import arm_agent_hold
from sase.doctor.checks_agent_holds import (
    _check_agent_holds_stale,
    agent_hold_check_specs,
)
from sase.doctor.runner import DoctorContext
from tests._runner_slot_fixtures import artifact as make_artifact


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        env={},
    )


def test_agent_hold_check_specs_are_registered() -> None:
    specs = agent_hold_check_specs(_context(Path("/tmp")))
    assert [spec.id for spec in specs] == ["agent_holds.stale"]
    assert {spec.group for spec in specs} == {"agent_holds"}


def test_stale_holds_ok_when_store_file_is_absent(tmp_path: Path) -> None:
    check = _check_agent_holds_stale(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["hold_count"] == 0


def test_stale_holds_ok_when_the_only_hold_is_alive(tmp_path: Path) -> None:
    with patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}, clear=False):
        with patch(
            "sase.core.agent_hold_facade._project_for_cwd", return_value="scratch"
        ):
            arm_agent_hold(future=True, scope="host", ttl_seconds=3600.0)

        check = _check_agent_holds_stale(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["hold_count"] == 1


def test_stale_holds_warns_and_prunes_a_dead_armer(tmp_path: Path) -> None:
    dead_pid = 999_999_999
    armer_dir = make_artifact(tmp_path, "20260910130000", dead_pid)
    (armer_dir / "agent_meta.json").write_text(
        json.dumps({"pid": dead_pid, "name": "ghost--code"})
    )

    with patch.dict(
        "os.environ",
        {
            "SASE_HOME": str(tmp_path / ".sase"),
            "SASE_ARTIFACTS_DIR": str(armer_dir),
        },
        clear=False,
    ):
        result = arm_agent_hold(future=True, scope="host", ttl_seconds=3600.0)
        armer_key = result.record["armer"]["key"]

        check = _check_agent_holds_stale(_context(tmp_path))

    assert check.status == "WARN"
    assert check.data["stale_count"] == 1
    assert check.data["stale"][0]["armer_key"] == armer_key
    assert check.data["stale"][0]["reason"] == "dead armer"
    assert any("ghost" in detail for detail in check.details)


def test_stale_holds_reason_is_past_expiry_when_only_ttl_is_stale(
    tmp_path: Path,
) -> None:
    raw_holds = {
        "agent:hold-a": {
            "armer": {"kind": "agent", "key": "agent:hold-a", "display": "hold-a"},
            "expires_at": 1_700_000_000.0,
        }
    }

    check = _check_agent_holds_stale(
        _context(tmp_path),
        raw_holds=raw_holds,
        pruned=[],
        now=1_700_000_500.0,
    )

    assert check.status == "WARN"
    assert check.data["stale"][0]["reason"] == "past expiry"


def test_stale_holds_ignores_a_hold_still_present_after_reconcile(
    tmp_path: Path,
) -> None:
    raw_holds = {
        "agent:hold-a": {
            "armer": {"kind": "agent", "key": "agent:hold-a", "display": "hold-a"},
            "expires_at": 1_700_001_000.0,
        }
    }

    check = _check_agent_holds_stale(
        _context(tmp_path),
        raw_holds=raw_holds,
        pruned=[{"armer": {"key": "agent:hold-a"}}],
        now=1_700_000_500.0,
    )

    assert check.status == "OK"
    assert check.data["hold_count"] == 1


def test_stale_holds_warns_on_malformed_store_file(tmp_path: Path) -> None:
    context = _context(tmp_path)
    context.sase_home.mkdir(parents=True)
    (context.sase_home / "agent_holds.json").write_text("not json")

    check = _check_agent_holds_stale(context)

    assert check.status == "WARN"
    assert check.data == {"raw_readable": False}
