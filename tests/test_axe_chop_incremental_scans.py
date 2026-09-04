"""Incremental wait_checks / bead_claim_checks scan short-circuits and parity."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_claim_checks as claim_checks
import sase.scripts.sase_chop_wait_checks as wait_checks_module
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    rebuild_agent_artifact_index,
)
from sase.scripts._chop_bead_claim_scan import BEAD_CLAIM_RECONCILED_MARKER
from sase.scripts._chop_incremental_index import chop_scan_full_walk
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_bead_claim_checks_helpers import make_runtime
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks

FULL_WALK_ENV = "SASE_CHOP_SCAN_FULL_WALK"


def _count_wait_meta_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> list[int]:
    original = wait_checks_module._read_json_dict
    reads = [0]

    def counting_read_json_dict(path: Path) -> dict[str, Any] | None:
        if path.name == "agent_meta.json":
            reads[0] += 1
        return original(path)

    monkeypatch.setattr(
        wait_checks_module,
        "_read_json_dict",
        counting_read_json_dict,
    )
    return reads


def _rebuild_test_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    index_path = default_agent_artifact_index_path()
    rebuild_agent_artifact_index(index_path, tmp_path / ".sase" / "projects")
    return index_path


def _write_claim_artifact(
    tmp_path: Path,
    *,
    timestamp: str,
    name: str,
    bead_id: str,
    promoted: bool,
    tombstoned: bool = False,
) -> Path:
    artifact_dir = (
        tmp_path / ".sase" / "projects" / "sase" / "artifacts" / "ace-run" / timestamp
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": name,
                "bead_id": bead_id,
                "bead_claim_promoted": promoted,
                "pid": 123,
            }
        ),
        encoding="utf-8",
    )
    if tombstoned:
        (artifact_dir / BEAD_CLAIM_RECONCILED_MARKER).write_text(
            "{}\n", encoding="utf-8"
        )
    return artifact_dir


def test_chop_scan_full_walk_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FULL_WALK_ENV, raising=False)
    assert chop_scan_full_walk() is False
    monkeypatch.setenv(FULL_WALK_ENV, "1")
    assert chop_scan_full_walk() is True
    monkeypatch.setenv(FULL_WALK_ENV, "false")
    assert chop_scan_full_walk() is False


def test_wait_checks_skip_path_does_not_read_agent_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "idle-agent",
        done=True,
        outcome="completed",
    )
    reads = _count_wait_meta_reads(monkeypatch)

    run_wait_checks(tmp_path, monkeypatch)

    assert reads[0] == 0


def test_wait_checks_already_ready_does_not_read_agent_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter = make_waiting_agent(tmp_path, "foo")
    (waiter / "ready.json").write_text("{}\n", encoding="utf-8")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    reads = _count_wait_meta_reads(monkeypatch)

    run_wait_checks(tmp_path, monkeypatch)

    assert reads[0] == 0
    assert (waiter / "ready.json").exists()


def test_wait_checks_incremental_matches_full_walk_on_populated_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    waiter = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)
    incremental_out = capsys.readouterr().out
    incremental_ready = (waiter / "ready.json").read_text(encoding="utf-8")
    (waiter / "ready.json").unlink()

    monkeypatch.setenv(FULL_WALK_ENV, "1")
    run_wait_checks(tmp_path, monkeypatch)
    full_walk_out = capsys.readouterr().out
    full_walk_ready = (waiter / "ready.json").read_text(encoding="utf-8")

    assert (
        json.loads(incremental_ready)
        == json.loads(full_walk_ready)
        == {"resolved_deps": ["foo"]}
    )
    assert "ready_written=1" in incremental_out
    assert "ready_written=1" in full_walk_out


def test_wait_checks_index_resolution_skips_filesystem_meta_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    _rebuild_test_index(tmp_path, monkeypatch)
    reads = _count_wait_meta_reads(monkeypatch)

    run_wait_checks(tmp_path, monkeypatch)

    assert json.loads((waiter / "ready.json").read_text(encoding="utf-8")) == {
        "resolved_deps": ["foo"]
    }
    assert reads[0] == 0


def test_wait_checks_full_walk_still_reads_idle_agent_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(8):
        make_agent(
            tmp_path,
            "proj",
            f"2026050601{index:04d}",
            f"idle-{index}",
            done=True,
            outcome="completed",
        )
    monkeypatch.setenv(FULL_WALK_ENV, "1")
    reads = _count_wait_meta_reads(monkeypatch)

    run_wait_checks(tmp_path, monkeypatch)

    assert reads[0] == 8


def test_bead_claim_index_prepass_skips_full_scan_when_idle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _write_claim_artifact(
        tmp_path,
        timestamp="20260724120000",
        name="sase-1.1",
        bead_id="sase-1.1",
        promoted=True,
    )
    _rebuild_test_index(tmp_path, monkeypatch)

    monkeypatch.setattr(
        claim_checks,
        "scan_agent_artifacts",
        lambda *_args, **_kwargs: pytest.fail(
            "idle index prepass must not scan_agent_artifacts"
        ),
    )
    monkeypatch.setattr(
        claim_checks,
        "_process_project_claims",
        lambda *_args, **_kwargs: pytest.fail("idle index prepass opened a bead store"),
    )

    result = claim_checks._run(make_runtime(tmp_path))

    assert result.reason == "no_claim_reconciliation_candidates"


def test_bead_claim_tombstoned_owner_is_skipped_by_index_prepass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _write_claim_artifact(
        tmp_path,
        timestamp="20260724120000",
        name="sase-1.1",
        bead_id="sase-1.1",
        promoted=False,
        tombstoned=True,
    )
    _rebuild_test_index(tmp_path, monkeypatch)
    monkeypatch.setattr(
        claim_checks,
        "scan_agent_artifacts",
        lambda *_args, **_kwargs: pytest.fail(
            "tombstoned index prepass must not scan_agent_artifacts"
        ),
    )

    result = claim_checks._run(make_runtime(tmp_path))

    assert result.reason == "no_claim_reconciliation_candidates"


def test_bead_claim_full_walk_still_scans_when_index_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _write_claim_artifact(
        tmp_path,
        timestamp="20260724120000",
        name="sase-1.1",
        bead_id="sase-1.1",
        promoted=True,
    )
    _rebuild_test_index(tmp_path, monkeypatch)
    monkeypatch.setenv(FULL_WALK_ENV, "1")
    scanned: list[Path] = []

    def tracking_scan(root: Path, _options: object) -> SimpleNamespace:
        scanned.append(root)
        return SimpleNamespace(records=[])

    monkeypatch.setattr(claim_checks, "scan_agent_artifacts", tracking_scan)

    result = claim_checks._run(make_runtime(tmp_path))

    assert scanned
    assert result.reason == "no_claim_reconciliation_candidates"
