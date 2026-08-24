"""Real-store regression coverage for leaving the snoozed status.

Every test here drives a genuine bead store on disk, with no project mock,
because mocking the project is exactly what let a store-bricking close ship:
``close_one`` left the snooze record on the closed issue, the derived record
failed validation, and the ``issue_closed`` event had already been persisted,
so every later load replayed the poison event forever.

The assertion that matters is therefore not that the call returns — it is
that a *cold* read of the store still works afterwards.
``sase.core.bead_read_facade.list_issues`` is that read: it goes straight to
the ``bead_list`` binding against ``beads_dir`` with no Python-side cache in
front of it, which is the exact call that used to raise
``Only snoozed issues can carry snooze metadata`` for the rest of the store's
life.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from datetime import datetime, UTC
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Issue, IssueType, SnoozeRecord, Status
from sase.bead.project import BeadProject
from sase.bead._snooze_gate_preview import bead_snooze_close_reason
from sase.bead._snooze_gate_spec import build_bead_snooze_gate_spec
from sase.core import bead_read_facade
from sase.core.time import get_timezone
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.service import create_gate
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution

WAKE_TIME = "2026-08-09T09:00:00-04:00"
SNOOZED_AT = "2026-08-06T09:00:00-04:00"
ACTOR = "owner@example"
FROZEN_LOCAL = datetime(2026, 8, 6, 12, 0)


@pytest.fixture(autouse=True)
def frozen_clocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin both clocks together, as ``test_cli_snooze`` does.

    The Python surfaces resolve "now" through ``sase.core.time`` while the
    Rust store is handed the timestamp ``sase.bead.project._now`` produces;
    pinning only one leaves a wake time that is future by one clock and
    already past by the other.
    """
    frozen_utc = (
        FROZEN_LOCAL.replace(tzinfo=get_timezone())
        .astimezone(UTC)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    monkeypatch.setattr("sase.core.time.local_now", lambda: FROZEN_LOCAL)
    monkeypatch.setattr("sase.bead.project._now", lambda: frozen_utc)


@pytest.fixture
def snooze_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[SimpleNamespace]:
    """A real bead store, kept clear of the gate fixture's tmp_path files."""
    checkout = tmp_path / "checkout"
    with BeadProject.init(checkout):
        pass
    isolate_bead_store_resolution(monkeypatch, checkout)
    monkeypatch.setattr(
        "sase.agent.identity.discover_agent_identity",
        lambda: SimpleNamespace(name=ACTOR),
    )
    with BeadProject(checkout) as project:
        beads_dir = project.beads_dir
    yield SimpleNamespace(checkout=checkout, beads_dir=beads_dir)


def _snoozed_task(store: SimpleNamespace, title: str = "Deferrable") -> Issue:
    """Create a task bead and snooze it for real, through the store."""
    with BeadProject(store.checkout) as project:
        issue = project.create(title, IssueType.TASK, task_type="bug", size="small")
        project.update(issue.id, status=Status.READY.value)
        project.snooze(
            issue.id,
            until=WAKE_TIME,
            actor=ACTOR,
            reason="waiting on the upstream fix",
        )
        snoozed = project.show(issue.id)
    assert snoozed.status is Status.SNOOZED
    assert snoozed.snooze is not None
    return snoozed


def _reload(store: SimpleNamespace) -> Issue:
    """Read the bead back through the binding, bypassing every Python cache.

    This is the assertion the mocked tests could not make: the call raising
    is not the failure mode that mattered, the store dying afterwards was.
    """
    issues = bead_read_facade.list_issues(store.beads_dir)
    assert len(issues) == 1
    return issues[0]


def _gate_spec(bead: Issue, *, request_id: str) -> dict[str, Any]:
    return build_bead_snooze_gate_spec(
        request_id=request_id,
        bead_id=bead.id,
        project="sase",
        title=bead.title,
        snooze=SnoozeRecord(
            until=WAKE_TIME,
            snoozed_at=SNOOZED_AT,
            snoozed_by=ACTOR,
            reason="waiting on the upstream fix",
        ),
        description="Make invalidation deterministic.",
        notes="",
        created_by="claude_coder",
        created_at="2026-01-01T00:00:00Z",
        producer={"agent_name": "snooze-regression"},
    )


def _select(
    bead: Issue,
    store: SimpleNamespace,
    option: str,
    *,
    request_id: str,
    feedback: str | None = None,
    option_inputs: dict[str, dict[str, object]] | None = None,
) -> None:
    """Run one BeadSnooze gate option against the real store."""
    gate = create_gate(_gate_spec(bead, request_id=request_id))
    with patch(
        "sase.bead._snooze_gate_actions._resolve_bead_snooze_project_cwd",
        return_value=store.checkout,
    ):
        execute_gate_selection(
            gate.bundle_path,
            [option],
            feedback=feedback,
            option_inputs=option_inputs,
            source="tui",
        )


def _close_args(bead: Issue, reason: str) -> argparse.Namespace:
    return argparse.Namespace(
        ids=[bead.id],
        reason=reason,
        resolution="canceled",
        force=False,
        note=None,
        no_push=True,
    )


def test_gate_close_closes_a_snoozed_bead_and_leaves_the_store_readable(
    gate_home: Path,
    snooze_store: SimpleNamespace,
) -> None:
    """The gate's primary action — the one that used to brick the store."""
    del gate_home
    bead = _snoozed_task(snooze_store)

    _select(bead, snooze_store, "close", request_id="snooze-close-real")

    reloaded = _reload(snooze_store)
    assert reloaded.status is Status.CLOSED
    assert reloaded.snooze is None
    assert reloaded.close_reason == bead_snooze_close_reason(WAKE_TIME)


def test_gate_ready_wakes_a_snoozed_bead_and_leaves_the_store_readable(
    gate_home: Path,
    snooze_store: SimpleNamespace,
) -> None:
    del gate_home
    bead = _snoozed_task(snooze_store)

    _select(bead, snooze_store, "ready", request_id="snooze-ready-real")

    reloaded = _reload(snooze_store)
    assert reloaded.status is Status.READY
    assert reloaded.snooze is None
    assert "Woken from snooze and returned to triage." in reloaded.notes_text


def test_gate_resnooze_defers_a_woken_bead_and_leaves_the_store_readable(
    gate_home: Path,
    snooze_store: SimpleNamespace,
) -> None:
    del gate_home
    bead = _snoozed_task(snooze_store)

    _select(
        bead,
        snooze_store,
        "snooze",
        request_id="snooze-again-real",
        option_inputs={"snooze": {"duration": "3d +2"}},
    )

    reloaded = _reload(snooze_store)
    assert reloaded.status is Status.SNOOZED
    assert reloaded.snooze is not None
    assert reloaded.snooze.until == "2026-08-09T12:00:00-04:00"
    assert reloaded.snooze.plus_one_target == 2
    assert reloaded.snooze.reason == "waiting on the upstream fix"


def test_cli_close_closes_a_snoozed_bead_and_leaves_the_store_readable(
    snooze_store: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``sase bead close <id>`` — the second caller with no snooze pre-clear."""
    bead = _snoozed_task(snooze_store)

    bead_cli.handle_bead_close(_close_args(bead, "Superseded upstream."))
    capsys.readouterr()

    reloaded = _reload(snooze_store)
    assert reloaded.status is Status.CLOSED
    assert reloaded.snooze is None
    assert reloaded.close_reason == "Superseded upstream."


def test_a_closed_snoozed_bead_survives_replay_from_its_event_stream(
    snooze_store: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The durability half: the events on disk must derive the same record.

    The defect was unrecoverable because ``issue_closed`` landed in the event
    stream while validation rejected the derived state, so every later load
    replayed the poison event against a stale ``issues.jsonl``. Deleting that
    derived snapshot forces the same replay path here.
    """
    bead = _snoozed_task(snooze_store)
    bead_cli.handle_bead_close(_close_args(bead, "Superseded upstream."))
    capsys.readouterr()
    assert _event_kinds(snooze_store.beads_dir) >= {"task_snoozed", "issue_closed"}
    (snooze_store.beads_dir / "issues.jsonl").unlink()

    replayed = _reload(snooze_store)

    assert replayed.status is Status.CLOSED
    assert replayed.snooze is None


def _event_kinds(beads_dir: Path) -> set[str]:
    kinds: set[str] = set()
    for stream in (beads_dir / "events" / "streams").glob("*.jsonl"):
        for line in stream.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line).get("payload")
            if isinstance(payload, dict) and isinstance(payload.get("kind"), str):
                kinds.add(payload["kind"])
    return kinds
