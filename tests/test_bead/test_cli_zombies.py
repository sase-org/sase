"""CLI and collector coverage for ``sase bead zombies``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead import zombie as zombie_module
from sase.bead.cli_zombies import handle_bead_zombies
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    DoneMarkerWire,
)
from sase.core.zombie_facade import ZombieEvaluationReport, ZombieVerdict
from sase.bead.zombie import ZombieReport
from sase.main import bead_fast_path
from sase.main.bead_fast_path import try_handle_bead_fast_path
from sase.main.parser import create_parser


def _zombie_row(plan_id: str = "sase-1", **fields: object) -> ZombieVerdict:
    values: dict[str, object] = {
        "plan_id": plan_id,
        "title": "Epic",
        "tier": "epic",
        "assignee": f"{plan_id}.land",
        "state": "zombie",
        "zombie": True,
        "recovery_eligible": True,
        "tree_complete": True,
        "descendant_count": 1,
        "all_descendants_closed": True,
        "latest_descendant_closed_at": "2026-09-13T10:21:02Z",
        "latest_descendant_id": f"{plan_id}.1",
        "latest_descendant_close_event_id": "close-1",
        "close_token": f"{plan_id}.1:close-1",
        "ownership_reason": "child_landed",
    }
    values.update(fields)
    return ZombieVerdict(**values)  # type: ignore[arg-type]


def _loaded_report(
    *rows: ZombieVerdict,
    project: str = "demo",
    collection_failed: bool = False,
    failure_reason: str | None = None,
) -> ZombieReport:
    return ZombieReport(
        report=ZombieEvaluationReport(rows=rows),
        project=project,
        titles={row.plan_id: row.title for row in rows},
        generated_at=1_700_000_000.0,
        collection_failed=collection_failed,
        failure_reason=failure_reason,
    )


def _run_handler(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    reports: dict[str, ZombieReport],
) -> str:
    monkeypatch.setattr(
        "sase.bead.cli_zombies._project_targets",
        lambda all_projects: [("demo", "Demo")],
    )

    def fake_load(project: str, *, now: float | None = None) -> ZombieReport:
        return reports[project]

    monkeypatch.setattr("sase.bead.cli_zombies.load_zombie_report", fake_load)
    args = create_parser().parse_args(["bead", *argv])
    bead_cli.handle_bead_zombies(args)
    return capsys.readouterr().out


def test_zombies_parser_accepts_scope_and_format() -> None:
    parser = create_parser()

    bare = parser.parse_args(["bead", "zombies"])
    scoped = parser.parse_args(["bead", "zombies", "-a", "--format", "json"])

    assert bare.bead_subcommand == "zombies"
    assert bare.all_projects is False
    assert bare.format == "compact"
    assert scoped.all_projects is True
    assert scoped.format == "json"


def test_fast_path_defers_zombies_to_argparse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_context(argv: list[str]) -> None:
        raise AssertionError(f"context should not resolve for zombies: {argv}")

    monkeypatch.setattr(bead_fast_path, "_resolve_fast_path_context", fail_context)

    assert try_handle_bead_fast_path(["zombies"]) is None
    assert try_handle_bead_fast_path(["zombies", "-a"]) is None


def test_zombies_compact_lists_zombie_unknown_and_counts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run_handler(
        monkeypatch,
        capsys,
        ["zombies"],
        {
            "demo": _loaded_report(
                _zombie_row(),
                _zombie_row(
                    plan_id="sase-2",
                    state="unknown",
                    zombie=False,
                    recovery_eligible=False,
                    unknown_reason="ownership_records_unavailable",
                ),
                _zombie_row(
                    plan_id="sase-3",
                    state="owned",
                    zombie=False,
                    recovery_eligible=False,
                    owner="sase-3.land",
                    ownership_reason="running",
                ),
                _zombie_row(
                    plan_id="sase-4",
                    state="not_zombie",
                    zombie=False,
                    recovery_eligible=False,
                    reason="open_descendant",
                ),
            )
        },
    )
    assert "project Demo (demo)" in out
    assert "⚐ sase-1 · Epic" in out
    assert "all 1 descendants closed" in out
    assert "sase bead work sase-1" in out
    assert "? sase-2" in out
    assert "ownership_records_unavailable" in out
    assert "not a zombie" in out
    assert "owned by sase-3.land" in out
    assert "Summary: 1 zombie(s), 1 unknown, 1 owned, 1 not-zombie" in out


def test_zombies_compact_is_explicit_when_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run_handler(monkeypatch, capsys, ["zombies"], {"demo": _loaded_report()})
    assert "no in-progress plans" in out
    assert "Summary: 0 zombie(s), 0 unknown, 0 owned, 0 not-zombie" in out


def test_zombies_compact_reports_failed_collection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run_handler(
        monkeypatch,
        capsys,
        ["zombies"],
        {"demo": _loaded_report(collection_failed=True, failure_reason="boom")},
    )
    assert "report failed: boom" in out


def test_zombies_json_reports_every_row(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run_handler(
        monkeypatch,
        capsys,
        ["zombies", "--format", "json"],
        {"demo": _loaded_report(_zombie_row())},
    )
    payload = json.loads(out)
    assert payload["projects"][0]["project_key"] == "demo"
    assert payload["projects"][0]["project_label"] == "Demo"
    (row,) = payload["projects"][0]["rows"]
    assert row["plan_id"] == "sase-1"
    assert row["state"] == "zombie"
    assert row["close_token"] == "sase-1.1:close-1"
    assert row["recovery_eligible"] is True


def _tree_state(root: Path) -> dict[str, bytes | None]:
    state: dict[str, bytes | None] = {}
    for path in sorted(root.rglob("*")):
        key = path.relative_to(root).as_posix()
        if path.is_dir():
            state[f"{key}/"] = b"dir"
        elif path.is_symlink():
            state[key] = f"symlink:{path.readlink()}".encode()
        else:
            state[key] = path.read_bytes()
    return state


def test_zombies_handler_never_mutates_or_launches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    with BeadProject.init(store) as project:
        epic = project.create("Epic", IssueType.PLAN, tier=BeadTier.EPIC)
    before = _tree_state(store)
    out = _run_handler(monkeypatch, capsys, ["zombies"], {"demo": _loaded_report()})
    assert "Summary:" in out
    assert _tree_state(store) == before
    with BeadProject(store) as project:
        assert project.show(epic.id).status is Status.OPEN


def _seed_zombie_store(tmp_path: Path) -> tuple[Path, Issue, Issue]:
    store = tmp_path / "store"
    with BeadProject.init(store) as project:
        epic = project.create(
            "Epic", IssueType.PLAN, tier=BeadTier.EPIC, assignee="demo.land"
        )
        epic = project.update(epic.id, status="in_progress")
        phase = project.create("Phase", IssueType.PHASE, parent_id=epic.id)
        closed = project.close([phase.id], reason="done")
    return store, epic, closed[0]


def _canonical_for(store: Path):  # type: ignore[no-untyped-def]
    beads_dir = store / "sdd" / "beads"
    assert beads_dir.is_dir()
    return lambda _project: beads_dir


def test_zombie_collector_confirms_completed_descendant_epic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, epic, _phase = _seed_zombie_store(tmp_path)
    artifact = tmp_path / "artifacts" / "demo.land"
    artifact.mkdir(parents=True)
    record = AgentArtifactRecordWire(
        project_name="demo",
        project_dir=str(tmp_path),
        project_file=str(tmp_path / "demo.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(artifact),
        timestamp="20260912120000",
        agent_meta=AgentMetaWire(name="demo.land", agent_session="demo.land"),
        done=DoneMarkerWire(
            outcome="completed", finished_at=1_700_000_000.0, name="demo.land"
        ),
        has_done_marker=True,
    )
    monkeypatch.setattr(
        zombie_module, "canonical_beads_dir_for_project", _canonical_for(store)
    )
    monkeypatch.setattr(
        zombie_module,
        "session_record_cache",
        lambda _project, assignees: {key: ([record], True) for key in assignees},
    )
    payload = zombie_module._collect_zombie_report_input("demo")
    assert payload["snapshot"]["complete"] is True
    assert len(payload["owners"]) == 1
    report = zombie_module.load_zombie_report("demo")
    assert not report.collection_failed
    (row,) = report.report.rows
    assert row.plan_id == epic.id
    assert row.state == "zombie"
    assert row.zombie is True
    assert row.descendant_count == 1
    assert row.all_descendants_closed is True
    assert row.latest_descendant_closed_at is not None
    assert (row.close_token is not None) == row.recovery_eligible


def test_zombie_collector_marks_ownerless_evidence_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, epic, _phase = _seed_zombie_store(tmp_path)
    monkeypatch.setattr(
        zombie_module, "canonical_beads_dir_for_project", _canonical_for(store)
    )
    monkeypatch.setattr(
        zombie_module, "session_record_cache", lambda _project, _assignees: {}
    )
    report = zombie_module.load_zombie_report("demo")
    assert not report.collection_failed
    (row,) = [item for item in report.report.rows if item.plan_id == epic.id]
    assert row.state == "unknown"


def test_zombie_loader_marks_missing_store_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        zombie_module, "canonical_beads_dir_for_project", lambda _p: None
    )
    report = zombie_module.load_zombie_report("nope")
    assert report.collection_failed
    assert report.failure_reason is not None
