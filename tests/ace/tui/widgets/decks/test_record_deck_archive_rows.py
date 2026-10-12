"""Light-row Record for unreadable Archive entries and container rows."""

from __future__ import annotations

from types import SimpleNamespace

from rich.console import Group

from sase.ace.tui.models.agent_archive_reader import (
    archive_identity_header_from_light_row,
)
from sase.ace.tui.widgets.decks.record.document import build_record_document
from sase.ace.tui.widgets.decks.record.facts import (
    FactsExtras,
    lifecycle_card,
    load_facts_extras,
    provenance_card,
)
from sase.ace.tui.widgets.decks.record.model import (
    record_archive_facts_from_light_row,
    record_subject_from_light_row,
)
from sase.ace.tui.widgets.decks.record.relations import RelationsExtras, relations_card
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from sase.project_display_names import ProjectDisplaySnapshot
from tests.ace.tui._agent_archive_column_helpers import light_row


def _card_text(card: object) -> str:
    return renderable_to_text(Group(*card.renderables)) or ""


def test_light_row_subject_is_archive_kind_with_row_facts() -> None:
    row = light_row(
        "run-1",
        name="gone.agent",
        status="FAILED",
        outcome="failed",
        time_basis="dismissed",
        restorable=False,
    )
    subject = record_subject_from_light_row(row)
    assert subject.kind == "light_row"
    assert subject.location == "archive"
    assert subject.agent_name == "gone.agent"
    assert subject.status == "FAILED"
    assert subject.restartable is False
    assert subject.durably_revivable is False
    assert subject.archive is not None
    assert subject.archive.outcome == "failed"
    assert subject.archive.time_basis == "dismissed"
    assert subject.archive.last_activity == "2026-10-10T12:00:00Z"
    assert subject.archive.start_time == "2026-10-10T12:00:00Z"
    assert subject.archive.restorable is False
    assert subject.archive.archive_key == "u.m@run-1"
    assert subject.source_run_id == "run-1"
    assert subject.project_label == "sase"
    assert subject.identity == ("archive-light", "u", "m", "run-1")
    assert subject.raw_suffix is None
    hash(subject.identity)


def test_container_subject_carries_member_count_outcome_and_refs() -> None:
    members = (
        light_row("m1", name="swarm.one", outcome="done"),
        light_row("m2", name="swarm.two", outcome="failed", hour=11),
    )
    row = light_row(
        "clan",
        name="swarm",
        container_key="clan:swarm:1",
        container=True,
        member_count=3,
        outcome="failed",
        time_basis="ended",
        last_activity_at="2026-10-10T12:00:00Z",
    )
    subject = record_subject_from_light_row(row, members=members)
    assert subject.kind == "container"
    assert subject.location == "archive"
    assert subject.member_names == ("swarm.one", "swarm.two")
    assert subject.archive is not None
    assert subject.archive.member_count == 3
    assert subject.archive.outcome == "failed"
    assert subject.archive.last_activity == "2026-10-10T12:00:00Z"
    assert subject.identity == ("archive-container", "clan:swarm:1")

    extras = FactsExtras()
    life = _card_text(lifecycle_card(subject, extras))
    assert "Archive" in life
    assert "✗ failed" in life
    assert "Members: 3" in life
    assert "Last activity:" in life
    assert "Time basis: ended" in life

    relations = _card_text(relations_card(subject, RelationsExtras()))
    assert "@agent:swarm.one" in relations
    assert "@agent:swarm.two" in relations


def test_unreadable_lifecycle_comes_from_the_light_row() -> None:
    row = light_row(
        "t00",
        name="missing.bundle",
        status="RUNNING",
        outcome="interrupted",
        time_basis="started",
        stop_time="2026-10-10T13:00:00Z",
        dismissed_at="2026-10-10T14:00:00Z",
        bundle_path="/tmp/archive/missing.bundle.json",
        raw_suffix="must-not-copy",
    )
    subject = record_subject_from_light_row(row)
    assert subject.raw_suffix is None
    assert subject.stop_time == "2026-10-10T13:00:00Z"
    assert subject.dismissed_at == "2026-10-10T14:00:00Z"
    assert subject.bundle_path == "/tmp/archive/missing.bundle.json"
    extras = load_facts_extras(subject)
    assert extras.dismissed_at == "2026-10-10T14:00:00Z"
    assert extras.bundle_path == "/tmp/archive/missing.bundle.json"
    life = _card_text(lifecycle_card(subject, extras))
    assert "missing.bundle" in life
    assert "Archive" in life
    assert "RUNNING" in life
    assert "○ WAS RUNNING" in life
    assert "Time basis: started" in life
    assert "Ended:" in life
    assert "Dismissed:" in life
    assert "end not recorded" not in life
    prov = _card_text(provenance_card(subject, extras))
    assert "Bundle: /tmp/archive/missing.bundle.json" in prov
    document = build_record_document(subject, extras, RelationsExtras())
    assert [card.title for card in document.cards] == [
        "Lifecycle",
        "Provenance",
        "Relations",
        "Links",
    ]


def test_light_row_project_label_uses_display_snapshot_name() -> None:
    row = light_row("job-run", project="gh_bbugyi200__job")
    snapshot = ProjectDisplaySnapshot({"gh_bbugyi200__job": "job"})
    subject = record_subject_from_light_row(row, display_snapshot=snapshot)
    assert subject.project_label == "job"
    prov = _card_text(provenance_card(subject, FactsExtras()))
    assert "Project: job" in prov
    assert "gh_bbugyi200__job" not in prov
    unlabeled = record_subject_from_light_row(row)
    assert unlabeled.project_label == "gh_bbugyi200__job"


def test_identity_header_labels_time_by_actual_basis() -> None:
    ended = archive_identity_header_from_light_row(light_row("a", time_basis="ended"))
    assert "Ended:" in ended.expanded.plain
    started = archive_identity_header_from_light_row(
        light_row("b", time_basis="started", outcome="interrupted", status="RUNNING")
    )
    assert "Started:" in started.expanded.plain
    assert "Ended:" not in started.expanded.plain
    dismissed = archive_identity_header_from_light_row(
        light_row("c", time_basis="dismissed")
    )
    assert "Dismissed:" in dismissed.expanded.plain
    assert "Started:" not in dismissed.expanded.plain


def test_archive_facts_from_light_row_are_pump_safe() -> None:
    facts = record_archive_facts_from_light_row(None)
    assert facts.outcome is None
    facts = record_archive_facts_from_light_row(light_row("x", runtime_seconds=12.5))
    assert facts.runtime_seconds == 12.5
    assert facts.member_count == 1


def test_show_subject_loads_the_light_row_document() -> None:
    from sase.ace.tui.widgets.decks.record.loader import (
        clear_record_cache,
        load_record_deck,
    )
    from sase.ace.tui.widgets.decks.record.view import RecordDeckView

    clear_record_cache()
    row = light_row("t00", name="gone")
    subject = record_subject_from_light_row(row)
    result = load_record_deck(subject, generation=4)
    assert result.subject_identity == subject.identity
    assert result.document.card("lifecycle") is not None
    life = _card_text(result.document.card("lifecycle"))
    assert "gone" in life
    assert "Archive" in life

    view = RecordDeckView.__new__(RecordDeckView)
    view._current_subject_identity = None
    view._current_generation = 0
    view._current_preferred = None
    view._current_worker = None
    view._current_worker_subject = None
    view._current_worker_generation = 0
    view._painted_signature = None
    view._has_displayed_content = False
    painted: list[object] = []
    view._paint_record_result = lambda loaded, preferred: painted.append(
        (loaded, preferred)
    )
    view._show_loading = lambda: None
    view.run_worker = lambda _fn, thread=True: SimpleNamespace(is_running=False)

    view.show_subject(subject, generation=4, preferred_card="lifecycle")
    assert view._current_subject_identity == subject.identity
    assert view._current_generation == 4
    assert painted and painted[0][1] == "lifecycle"
