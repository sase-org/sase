"""Tests for artifact-link outbox persistence and conversion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.sdd import _artifact_link_outbox_io as _outbox_io
from sase.sdd._artifact_link_outbox_io import (
    convert_legacy_artifact_link_outbox_entries,
    read_artifact_link_outbox_entries,
)
from sase.sdd.artifact_link_outbox import (
    ARTIFACT_LINK_OUTBOX_FILENAME,
    append_artifact_link_outbox_entry,
    append_artifact_link_outbox_event,
    drain_artifact_link_outbox,
)
from sase.sdd.artifact_link_event_publisher import observation_or_put_event_from_row
from sase.sdd.artifact_link_release_evidence import (
    record_artifact_link_release_evidence,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.main.artifact_link_outbox_helpers import _init_plans_repo, _outbox_lines
from tests.sdd._artifact_link_store_helpers import _row, allow_machine_sidecar_writes


def test_outbox_rejects_reused_operation_id_with_different_event_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, home)
    project_key = "gh_sase-org__sase"
    operation_id = "a" * 32
    first = observation_or_put_event_from_row(
        _row(source="agent:reader", target="plan:doc.md", origin="read"),
        project_key=project_key,
        operation_id=operation_id,
    )
    second = observation_or_put_event_from_row(
        _row(source="agent:reader", target="plan:other.md", origin="read"),
        project_key=project_key,
        operation_id=operation_id,
    )

    append_artifact_link_outbox_event(
        project_key=project_key,
        agent_name="reader",
        run_id="run-1",
        event=first,
    )
    with pytest.raises(RuntimeError, match="reused for different event bytes"):
        append_artifact_link_outbox_event(
            project_key=project_key,
            agent_name="reader",
            run_id="run-1",
            event=second,
        )

    assert len(_outbox_lines(home, project_key)) == 1


_PER_LINE_SCAN_BINDINGS = frozenset(
    {
        "artifact_link_outbox_classify_line",
        "artifact_link_event_canonicalize",
        "artifact_link_event_canonical_json",
        "artifact_link_event_digest",
        "artifact_link_event_path_for_digest",
        "artifact_link_event_validate_bytes",
    }
)


def _seed_large_outbox(home: Path, project_key: str, *, lines: int = 20_000) -> Path:
    """Write a synthetic large outbox by repeating one valid entry line."""

    append_artifact_link_outbox_entry(
        project_key=project_key,
        agent_name="reader",
        run_id="run-1",
        row=_row(source="agent:reader", target="plan:seed.md", origin="read"),
    )
    path = home / "projects" / project_key / ARTIFACT_LINK_OUTBOX_FILENAME
    [seed_line] = path.read_text(encoding="utf-8").splitlines()
    with path.open("a", encoding="utf-8") as output_file:
        for _ in range(lines):
            output_file.write(seed_line)
            output_file.write("\n")
    assert len(_outbox_lines(home, project_key)) == lines + 1
    return path


def _spy_outbox_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    """Record every Rust binding name resolved through the outbox io module."""

    calls: list[str] = []
    real = _outbox_io.require_rust_binding

    def _spy(name: str) -> Any:
        calls.append(name)
        return real(name)

    monkeypatch.setattr(_outbox_io, "require_rust_binding", _spy)
    return calls


def test_minted_id_append_performs_no_per_line_binding_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A uuid4-minted append must not re-read the outbox at all."""

    home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, home)
    project_key = "gh_sase-org__sase"
    _seed_large_outbox(home, project_key)
    calls = _spy_outbox_bindings(monkeypatch)

    append_artifact_link_outbox_entry(
        project_key=project_key,
        agent_name="reader",
        run_id="run-1",
        row=_row(source="agent:reader", target="plan:doc.md", origin="read"),
    )

    assert calls == []
    assert len(_outbox_lines(home, project_key)) == 20_002


def test_caller_supplied_id_append_scans_only_matching_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied id checks only lines carrying that id token."""

    home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, home)
    project_key = "gh_sase-org__sase"
    _seed_large_outbox(home, project_key)
    calls = _spy_outbox_bindings(monkeypatch)
    operation_id = "b" * 32
    row = _row(source="agent:reader", target="plan:doc.md", origin="read")

    append_artifact_link_outbox_entry(
        project_key=project_key,
        agent_name="reader",
        run_id="run-1",
        row=row,
        entry_id=operation_id,
    )
    assert [name for name in calls if name in _PER_LINE_SCAN_BINDINGS] == []

    append_artifact_link_outbox_entry(
        project_key=project_key,
        agent_name="reader",
        run_id="run-1",
        row=row,
        entry_id=operation_id,
    )
    scan_calls = [name for name in calls if name in _PER_LINE_SCAN_BINDINGS]
    assert scan_calls.count("artifact_link_outbox_classify_line") == 1

    with pytest.raises(RuntimeError, match="reused for different event bytes"):
        append_artifact_link_outbox_entry(
            project_key=project_key,
            agent_name="reader",
            run_id="run-1",
            row=_row(source="agent:reader", target="plan:other.md", origin="read"),
            entry_id=operation_id,
        )


def test_event_path_identical_payload_reappend_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, home)
    project_key = "gh_sase-org__sase"
    event = observation_or_put_event_from_row(
        _row(source="agent:reader", target="plan:doc.md", origin="read"),
        project_key=project_key,
        operation_id="d" * 32,
    )

    append_artifact_link_outbox_event(
        project_key=project_key,
        agent_name="reader",
        run_id="run-1",
        event=event,
    )
    append_artifact_link_outbox_event(
        project_key=project_key,
        agent_name="reader",
        run_id="run-1",
        event=event,
    )

    assert len(_outbox_lines(home, project_key)) == 2


def test_ineligible_drain_never_silently_drops_an_unconverted_legacy_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-op drain must not lose an unconverted schema-v1 outbox row.

    Reproduces the audited defect where seeding a valid legacy v1 row
    alongside an ineligible v2 entry, then draining with nothing eligible
    to publish, silently rewrote the queue from schema ``[1, 2]`` to
    ``[2]`` while reporting ``drained=0, dropped=0``.
    """

    home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, home)
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": repo},
    )
    path = home / "projects" / store.project_key / ARTIFACT_LINK_OUTBOX_FILENAME
    path.parent.mkdir(parents=True)
    legacy_row = _row(
        source="agent:legacy-reader",
        relation="read",
        target="plan:legacy.md",
        origin="read",
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "legacy-unconverted",
                "created_at": 1.0,
                "project_key": store.project_key,
                "agent_name": "legacy-reader",
                "run_id": "",
                "row": legacy_row,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    append_artifact_link_outbox_entry(
        project_key=store.project_key,
        agent_name="reader",
        run_id="run-1",
        row=_row(source="agent:reader", target="plan:doc.md", origin="read"),
    )
    before = [
        json.loads(line)["schema_version"]
        for line in path.read_text(encoding="utf-8").splitlines()
    ]

    report = drain_artifact_link_outbox(
        store=store,
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    after = [
        json.loads(line)["schema_version"]
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert report.drained == 0
    assert report.dropped == 0
    assert before == [1, 2]
    assert after == [1, 2]
    [remaining] = read_artifact_link_outbox_entries(store.project_key)
    assert remaining.agent_name == "reader"


def test_new_outbox_entries_persist_canonical_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, home)

    entry = append_artifact_link_outbox_entry(
        project_key="gh_sase-org__sase",
        agent_name="reader",
        run_id="run-1",
        row=_row(
            source="agent:reader",
            relation="read",
            target="plan:doc.md",
            origin="read",
            created_by="reader",
            created_at="2026-09-09T12:00:00Z",
        ),
        now=100.0,
    )

    assert len(entry.id) == 32
    assert entry.event is not None
    assert entry.event["operation_id"] == entry.id
    assert entry.row is not None
    assert entry.row["uses"] == 1
    [stored] = _outbox_lines(home, "gh_sase-org__sase")
    assert "event" in stored
    assert "row" not in stored
    assert stored["id"] == entry.id
    assert stored["event"] == entry.event


def test_legacy_row_only_outbox_entries_convert_before_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, home)
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": repo},
    )
    row = _row(
        source="agent:reader",
        relation="read",
        target="plan:doc.md",
        origin="read",
    )
    path = home / "projects" / "gh_sase-org__sase" / ARTIFACT_LINK_OUTBOX_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "legacy-row",
                "created_at": 100.0,
                "project_key": "gh_sase-org__sase",
                "agent_name": "reader",
                "run_id": "run-1",
                "row": row,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    converted = convert_legacy_artifact_link_outbox_entries("gh_sase-org__sase")

    assert converted.converted == 1
    assert converted.covered == 0
    assert converted.invalid == ()
    [converted_entry] = read_artifact_link_outbox_entries("gh_sase-org__sase")
    assert converted_entry.event is not None
    assert converted_entry.created_at == 100.0
    assert converted_entry.agent_name == "reader"
    assert converted_entry.run_id == "run-1"
    record_artifact_link_release_evidence(
        project_key="gh_sase-org__sase",
        run_id="run-1",
        agent_id="reader",
        qualifying_repo_ids=(str(repo),),
    )

    report = drain_artifact_link_outbox(
        store=store,
        agent_name="reader",
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    assert report.drained == 1
    assert report.committed is True
    assert len(report.event_paths) == 1
    assert not list((repo / "links").rglob("*"))
    [indexed] = store.load_aggregate()["rows"]
    assert indexed["uses"] == 1
    assert read_artifact_link_outbox_entries("gh_sase-org__sase") == ()
