"""Rust-projected owner candidates for failure triage (sase-1tc.5.1.2).

The ``bead_triage_owner_candidates`` binding replaced the gatherer's full
Python task hydration. These tests pin its values to the retired Python
policy, prove no full issue crosses into Python, and keep the gatherer's
fail-open and locator contracts.
"""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sase.bead.model import IssueType, Status
from sase.core import bead_read_facade
from sase.core.tool_run import (
    tool_run_begin,
    tool_run_finish,
    tool_run_observe,
    tool_run_triage_settle,
    tool_run_triage_show,
)
from sase.tool.triage_inputs import LOOKBACK_SECONDS, gather_owner_candidates
from tests.tool._triage_inputs_helpers import home

_CORE = importlib.import_module("sase_core_rs")

pytestmark = pytest.mark.skipif(
    not hasattr(_CORE, "bead_triage_owner_candidates"),
    reason="bead_triage_owner_candidates binding is not in this wheel",
)

NOW = 1_773_100_800  # 2026-03-10T00:00:00Z
DAY = 86_400
_CANDIDATE_KEYS = {"node_id", "location", "title", "status", "closed_ts"}


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(bead_id: str, created_at: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": bead_id,
        "title": f"Title {bead_id}",
        "status": "open",
        "issue_type": "task",
        "created_at": created_at,
        "updated_at": created_at,
    }
    row.update(extra)
    return row


def _representative_rows(history: int = 0) -> list[dict[str, Any]]:
    heavy = "x" * 16_384
    rows = [
        _row(
            "o.ci",
            "2026-01-01T00:00:01Z",
            task_type="ci",
            task_type_fields={
                "node_id": "tests/test_a.py::test_one",
                "location": "tests/test_a.py",
            },
        ),
        _row(
            "o.ready",
            "2026-01-01T00:00:02Z",
            status="ready",
            task_type="flake",
            task_type_fields={"location": "src/pkg/mod.py"},
        ),
        _row("o.claimed", "2026-01-01T00:00:03Z", status="claimed", task_type="bug"),
        _row(
            "o.prog",
            "2026-01-01T00:00:04Z",
            status="in_progress",
            task_type="ci",
            title="Fix tests/test_b.py failure",
        ),
        _row(
            "o.snooze",
            "2026-01-01T00:00:05Z",
            status="snoozed",
            task_type="flake",
            snooze={
                "until": "2026-04-01T00:00:00+00:00",
                "snoozed_at": "2026-03-01T00:00:00+00:00",
                "snoozed_by": "fixture",
            },
        ),
        _row(
            "c.recent",
            "2026-01-01T00:00:06Z",
            status="closed",
            task_type="bug",
            closed_at=_iso(NOW - DAY),
            task_type_fields={"node_id": "tests/test_c.py::test_two"},
        ),
        _row(
            "c.edge",
            "2026-01-01T00:00:07Z",
            status="closed",
            task_type="ci",
            closed_at=_iso(NOW - LOOKBACK_SECONDS),
        ),
        _row(
            "c.expired",
            "2026-01-01T00:00:08Z",
            status="closed",
            task_type="ci",
            closed_at=_iso(NOW - LOOKBACK_SECONDS - 1),
        ),
        _row("c.unknown", "2026-01-01T00:00:09Z", status="closed", task_type="flake"),
        _row(
            "c.naive",
            "2026-01-01T00:00:11Z",
            status="closed",
            task_type="ci",
            closed_at="2026-03-09 12:00:00",
        ),
        _row(
            "x.feature",
            "2026-01-01T00:00:12Z",
            task_type="feature",
            task_type_fields={"proposal": "tests/test_a.py"},
        ),
        _row("x.untyped", "2026-01-01T00:00:13Z"),
        _row("x.plan", "2026-01-01T00:00:14Z", issue_type="plan", tier="plan"),
    ]
    for index in range(history):
        rows.append(
            _row(
                f"h.{index}",
                "2025-06-01T00:00:00Z",
                status="closed",
                task_type="ci" if index % 2 == 0 else "memory",
                closed_at="2025-06-02T00:00:00Z",
                description=heavy,
                design=heavy,
                notes=[
                    {
                        "id": f"n{index}",
                        "timestamp": "2025-06-01T00:00:00Z",
                        "author": "fixture",
                        "text": heavy,
                    }
                ],
            )
        )
    return rows


def _legacy_store(root: Path, rows: list[dict[str, Any]]) -> Path:
    beads_dir = root / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    return beads_dir


def _parse(value: object) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def _retired_python_candidates(beads_dir: Path, now_ts: int) -> list[dict[str, Any]]:
    """The retired Python gatherer's policy, with its clock made explicit."""

    cutoff = now_ts - LOOKBACK_SECONDS
    candidates: list[dict[str, Any]] = []
    for issue in bead_read_facade.list_issues(beads_dir, issue_types=[IssueType.TASK]):
        if issue.task_type not in {"ci", "flake", "bug"}:
            continue
        closed_ts = _parse(issue.closed_at)
        if issue.status is Status.CLOSED and (closed_ts is None or closed_ts < cutoff):
            continue
        fields = issue.task_type_fields
        location_text = fields.get("node_id") or fields.get("location")
        candidates.append(
            {
                "node_id": issue.id,
                "location": location_text or None,
                "title": issue.title or None,
                "status": "closed" if issue.status is Status.CLOSED else "open",
                "closed_ts": closed_ts,
            }
        )
    return candidates


@pytest.mark.parametrize("now_ts", [NOW - 1, NOW, NOW + 1, NOW + 30 * DAY])
def test_projection_matches_retired_python_policy(tmp_path: Path, now_ts: int) -> None:
    beads_dir = _legacy_store(tmp_path, _representative_rows(history=6))

    candidates, diagnostics = bead_read_facade.triage_owner_candidates(
        beads_dir, now_ts=now_ts
    )

    assert diagnostics == []
    assert candidates == _retired_python_candidates(beads_dir, now_ts)
    assert all(set(row) == _CANDIDATE_KEYS for row in candidates)


def test_projection_reports_every_supported_status_and_field_rule(
    tmp_path: Path,
) -> None:
    beads_dir = _legacy_store(tmp_path, _representative_rows())

    candidates, _ = bead_read_facade.triage_owner_candidates(beads_dir, now_ts=NOW)

    by_id = {row["node_id"]: row for row in candidates}
    assert list(by_id) == [
        "o.ci",
        "o.ready",
        "o.claimed",
        "o.prog",
        "o.snooze",
        "c.recent",
        "c.edge",
        "c.naive",
    ]
    assert {by_id[key]["status"] for key in list(by_id)[:5]} == {"open"}
    assert by_id["o.ci"]["location"] == "tests/test_a.py::test_one"
    assert by_id["o.ready"]["location"] == "src/pkg/mod.py"
    assert by_id["o.prog"]["location"] is None
    assert by_id["o.prog"]["title"] == "Fix tests/test_b.py failure"
    assert by_id["c.recent"] == {
        "node_id": "c.recent",
        "location": "tests/test_c.py::test_two",
        "title": "Title c.recent",
        "status": "closed",
        "closed_ts": NOW - DAY,
    }
    assert by_id["c.edge"]["closed_ts"] == NOW - LOOKBACK_SECONDS
    assert by_id["c.naive"]["closed_ts"] == NOW - DAY // 2


def test_gatherer_never_hydrates_python_issues(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home(monkeypatch, tmp_path)
    root = tmp_path / "project"
    _legacy_store(root, _representative_rows(history=64))

    def _forbidden(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("owner candidates must not hydrate full issues")

    monkeypatch.setattr(bead_read_facade, "list_issues", _forbidden)
    monkeypatch.setattr(bead_read_facade, "issues_from_list", _forbidden)
    monkeypatch.setattr(bead_read_facade, "issue_from_dict", _forbidden)

    candidates, diagnostics = gather_owner_candidates(root, now_ts=NOW)

    assert diagnostics == []
    assert [row["node_id"] for row in candidates][:2] == ["o.ci", "o.ready"]
    assert len(candidates) == 8
    serialized = json.dumps(candidates)
    assert "xxxxxxxx" not in serialized
    assert all(set(row) == _CANDIDATE_KEYS for row in candidates)


def test_gatherer_reports_missing_store_without_raising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home(monkeypatch, tmp_path)
    root = tmp_path / "project"
    root.mkdir()

    assert gather_owner_candidates(root, now_ts=NOW) == (
        [],
        ["bead store unavailable for owner candidates"],
    )


def test_gatherer_fails_open_when_the_binding_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home(monkeypatch, tmp_path)
    root = tmp_path / "project"
    _legacy_store(root, _representative_rows())

    def _boom(*_args: object, **_kwargs: object) -> Any:
        raise RuntimeError("store busy")

    monkeypatch.setattr("sase.tool.triage_inputs.triage_owner_candidates", _boom)

    assert gather_owner_candidates(root, now_ts=NOW) == (
        [],
        ["owner candidate read failed: store busy"],
    )


def test_gatherer_transports_binding_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home(monkeypatch, tmp_path)
    root = tmp_path / "project"
    rows = _representative_rows()
    rows.append(
        _row(
            "c.garbled",
            "2026-01-01T00:00:15Z",
            status="closed",
            task_type="bug",
            closed_at="not a date",
        )
    )
    _legacy_store(root, rows)

    candidates, diagnostics = gather_owner_candidates(root, now_ts=NOW)

    assert "c.garbled" not in {row["node_id"] for row in candidates}
    assert diagnostics == [
        "owner candidates skipped 1 closed task(s) with an unparseable "
        "closed_at: c.garbled"
    ]


def _failed_run(now_ts: int) -> str:
    begun = tool_run_begin(
        {
            "schema_version": 1,
            "tool_name": "check",
            "definition": {
                "schema_version": 1,
                "name": "check",
                "argv": ["true"],
                "description": "fixture",
                "stages": "run_silent",
                "inputs": [],
                "env": [],
                "args": "deny",
                "fingerprint": {"repos": [], "toolchain": {}},
            },
            "display_argv": ["true"],
            "project": "fixture",
            "workspace": "fixture-workspace",
            "now_ts": now_ts,
            "commit_running": True,
        }
    )["run"]
    run_id = str(begun["run_id"])
    tool_run_observe(
        {
            "schema_version": 1,
            "run_id": run_id,
            "fingerprint_before": {
                "schema_version": 1,
                "project_identity": "fixture",
                "repos": [{"identity": "fixture", "head": "head", "dirty_paths": []}],
                "completeness": {"complete": True},
            },
        }
    )
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": run_id,
            "state": "failed",
            "exit_code": 1,
            "duration_ms": 1,
            "now_ts": now_ts + 1,
        }
    )
    return run_id


def test_bare_stage_label_locator_never_attaches_an_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stage label is not a file locator, and bead-ID tokens are not owners."""

    home(monkeypatch, tmp_path)
    now = NOW
    run_id = _failed_run(now)
    candidates = [
        {
            "node_id": "sase-probe",
            "location": "lint (symvision)",
            "title": "lint (symvision) keeps failing",
            "status": "open",
            "closed_ts": None,
        },
        {
            "node_id": "sase-symvision",
            "location": None,
            "title": "symvision unused symbol lint",
            "status": "open",
            "closed_ts": None,
        },
    ]

    settled = tool_run_triage_settle(
        {
            "run_id": run_id,
            "stages": [
                {
                    "stage_key": "lint (symvision)",
                    "stage_id": "stage-1",
                    "output": "symvision: 2 unused symbols (see sase-probe)\n",
                    "truncated": False,
                    "output_path": "logs/stage.log",
                }
            ],
            "project_root": str(tmp_path),
            "workspace_roots": [str(tmp_path)],
            "ancestry": ["head"],
            "flake_baseline": [],
            "selection_records": [],
            "owner_candidates": candidates,
            "knobs": {"min_witnesses": 1, "touched_requires_clean_witness": False},
            "continuation_mode": "never",
            "recipe_finished_ts": now + 2,
            "now_ts": now + 2,
        }
    )

    assert settled["triaged"] is True
    shown = tool_run_triage_show({"run_id": run_id})
    items = [i for i in shown["items"] if i["stage_key"] == "lint (symvision)"]
    assert items, shown
    for item in items:
        assert item["label"].get("possible_owners") in (None, []), item
