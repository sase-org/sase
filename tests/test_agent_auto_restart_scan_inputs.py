"""Bundle and done-row input-assembly tests for the scan phase.

Split from ``tests.test_agent_auto_restart_scan``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from sase.agent.auto_restart.inputs import (
    assemble_bundle_input,
    assemble_done_row_input,
    find_runner_log,
    read_log_tail,
)
from tests._agent_auto_restart_scan_helpers import scan_facts

__all__ = [
    "test_assemble_bundle_input",
    "test_assemble_done_row_legacy_without_facts",
    "test_assemble_done_row_pending_markers",
    "test_assemble_done_row_with_structured_facts",
    "test_find_runner_log_by_timestamp_suffix",
    "test_find_runner_log_prefers_output_path",
    "test_read_log_tail_last_200_lines",
]


def _done_dict(**overrides: Any) -> dict[str, Any]:
    done: dict[str, Any] = {
        "outcome": "failed",
        "finished_at": datetime.datetime(
            2026, 10, 9, 12, 5, tzinfo=datetime.UTC
        ).timestamp(),
        "name": "research.46.image",
        "cl_name": "gh_sase-org__sase",
        "workspace_dir": "/tmp/ws",
        "error": "ImportError: cannot import name 'x'",
        "traceback": "Traceback (most recent call last): ...",
        "output_path": None,
    }
    done.update(overrides)
    return done


def _meta_dict(**overrides: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "name": "research.46.image",
        "lifecycle_phase": "waiting",
        "booted_at": "2026-10-09T11:29:14-04:00",
        "code_identity": {
            "schema_version": 1,
            "roots": [{"name": "sase", "commit": "9c5000f2db"}],
        },
    }
    meta.update(overrides)
    return meta


def test_assemble_done_row_with_structured_facts(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "20261009112914"
    artifacts_dir.mkdir()
    assembled = assemble_done_row_input(
        artifacts_dir=artifacts_dir,
        done=_done_dict(failure_facts=scan_facts()),
        meta=_meta_dict(),
        managed_roots=(),
        project="gh_sase-org__sase",
        died_at=1.0,
        log_tail="Refreshing sase runner code after dependency wait: a -> b\n",
        journal_path=tmp_path / "absent.jsonl",
        enable_file_proof=False,
    )
    assert assembled.name == "research.46.image"
    assert assembled.facts is not None
    assert assembled.facts.lifecycle_phase == "waiting"
    assert assembled.facts.import_error is not None
    assert assembled.facts.import_error.missing_symbol == "auto_launch_prefix"
    assert assembled.context.lifecycle_phase == "waiting"
    assert assembled.context.workspace_dir == "/tmp/ws"
    assert assembled.context.error_text.startswith("ImportError")
    assert assembled.witnesses.boot_identity == "sase@9c5000f"
    assert assembled.lifecycle_phase == "waiting"


def test_assemble_done_row_legacy_without_facts(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "20261009112914"
    artifacts_dir.mkdir()
    assembled = assemble_done_row_input(
        artifacts_dir=artifacts_dir,
        done=_done_dict(),
        meta={"name": "old.row"},
        managed_roots=(),
        project="gh_sase-org__sase",
        died_at=1.0,
        log_tail="",
        journal_path=tmp_path / "absent.jsonl",
        enable_file_proof=False,
    )
    assert assembled.facts is None
    assert assembled.context.error_text.startswith("ImportError")
    assert assembled.context.traceback_text.startswith("Traceback")
    assert assembled.witnesses.boot_identity is None
    assert assembled.lifecycle_phase is None


def test_assemble_done_row_pending_markers(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "20261009112914"
    artifacts_dir.mkdir()
    (artifacts_dir / "pending_question.json").write_text("{}", encoding="utf-8")
    (artifacts_dir / ".sase_gate_pending").write_text("", encoding="utf-8")
    assembled = assemble_done_row_input(
        artifacts_dir=artifacts_dir,
        done=_done_dict(),
        meta={},
        managed_roots=(),
        project="p",
        died_at=None,
        log_tail="",
        journal_path=tmp_path / "absent.jsonl",
        enable_file_proof=False,
    )
    assert assembled.context.has_pending_question is True
    assert assembled.context.has_pending_handoff is True


def test_assemble_bundle_input(tmp_path: Path) -> None:
    bundle = {
        "agent_name": "0yz",
        "cl_name": "gh_bobs-org__bob-cli",
        "workspace_dir": "/tmp/bob",
        "artifacts_dir": "/nowhere/20261009115056",
        "error_message": "ImportError: cannot import name 'x'",
        "error_traceback": "Traceback ...",
        "output_path": None,
    }
    assembled = assemble_bundle_input(
        bundle=bundle,
        managed_roots=(),
        project="gh_bobs-org__bob-cli",
        died_at=1.0,
        log_tail="tail",
        journal_path=tmp_path / "absent.jsonl",
        enable_file_proof=False,
    )
    assert assembled.name == "0yz"
    assert assembled.facts is None
    assert assembled.context.workspace_dir == "/tmp/bob"
    assert assembled.witnesses.boot_identity is None


def test_read_log_tail_last_200_lines(tmp_path: Path) -> None:
    log = tmp_path / "run.txt"
    log.write_text("\n".join(f"line {n}" for n in range(500)), encoding="utf-8")
    tail = read_log_tail(log)
    lines = tail.splitlines()
    assert len(lines) == 200
    assert lines[0] == "line 300"
    assert lines[-1] == "line 499"
    assert read_log_tail(tmp_path / "absent.txt") == ""
    assert read_log_tail(None) == ""


def test_find_runner_log_prefers_output_path(tmp_path: Path) -> None:
    log = tmp_path / "custom.txt"
    log.write_text("hello", encoding="utf-8")
    assert find_runner_log(None, str(log), tmp_path) == log
    assert find_runner_log(None, str(tmp_path / "absent.txt"), tmp_path) is None


def test_find_runner_log_by_timestamp_suffix(tmp_path: Path) -> None:
    shard = tmp_path / "202610"
    shard.mkdir()
    log = shard / "gh_x__y_ace-run-261009_112914.txt"
    log.write_text("hello", encoding="utf-8")
    assert find_runner_log("20261009112914", None, tmp_path) == log
    assert find_runner_log("19990101000000", None, tmp_path) is None
