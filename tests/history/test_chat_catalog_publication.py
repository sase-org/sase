"""Tests for publication state exposed through the chat catalog."""

from __future__ import annotations

from pathlib import Path

import pytest
from sase.agents_sync.models import TargetSelection
from sase.history.chat_catalog_provenance import load_chat_catalog
from sase.history.chat_catalog_provenance import sidecars

from tests.history._chat_catalog_provenance_helpers import (
    _artifact,
    _chat,
    _commit_sidecar,
    _git_sidecar,
    _publication_row,
    _selection,
    _setup_home,
    _write_outbox,
)


def test_schema_v1_publication_backlog_is_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = _chat(home, "pending-260724_160000")
    _artifact(home, "20260724160000", chat)
    row = _publication_row(attempts=28, last_error="network down")
    row.pop("quarantined")
    row.pop("quarantined_at")
    outbox = _write_outbox(
        home,
        [row],
        schema_version=1,
    )

    entry = load_chat_catalog(force=True).entries[0]

    assert entry.publication_pending is True
    assert entry.publication_quarantined is False
    assert entry.publication_disposition == "queued"
    assert entry.publication_attempts == 28
    assert entry.publication_last_error == "network down"
    assert not outbox.with_suffix(".json.lock").exists()


def test_schema_v2_quarantined_publication_is_not_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = _chat(home, "quarantined-260724_160100")
    _artifact(home, "20260724160100", chat)
    outbox = _write_outbox(
        home,
        [
            _publication_row(
                attempts=3,
                last_error="remote rejected update",
                quarantined=True,
            )
        ],
    )

    entry = load_chat_catalog(force=True).entries[0]

    assert entry.publication_pending is False
    assert entry.publication_quarantined is True
    assert entry.publication_disposition == "quarantined"
    assert entry.publication_attempts == 3
    assert entry.publication_last_error == "remote rejected update"
    assert not outbox.with_suffix(".json.lock").exists()


def test_malformed_publication_state_becomes_catalog_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = _chat(home, "malformed-260724_160200")
    _artifact(home, "20260724160200", chat)
    row = _publication_row()
    row["quarantined"] = 1
    _write_outbox(home, [row])

    snapshot = load_chat_catalog(force=True)

    assert snapshot.entries[0].provenance == "local"
    assert snapshot.entries[0].publication_disposition is None
    assert any("quarantined must be a boolean" in item for item in snapshot.diagnostics)


def test_multiple_publication_revisions_aggregate_deterministically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = _chat(home, "aggregate-260724_160300")
    _artifact(home, "20260724160300", chat)

    cases = (
        (
            [
                _publication_row(
                    revision="a" * 40,
                    attempts=7,
                    last_error="older active",
                    updated_at=10.0,
                ),
                _publication_row(
                    revision="b" * 40,
                    attempts=2,
                    last_error="newer active",
                    updated_at=20.0,
                ),
            ],
            ("queued", True, False, 7, "newer active"),
        ),
        (
            [
                _publication_row(
                    revision="a" * 40,
                    attempts=3,
                    last_error="older quarantine",
                    quarantined=True,
                    updated_at=10.0,
                ),
                _publication_row(
                    revision="b" * 40,
                    attempts=5,
                    last_error="newer quarantine",
                    quarantined=True,
                    updated_at=20.0,
                ),
            ],
            ("quarantined", False, True, 5, "newer quarantine"),
        ),
        (
            [
                _publication_row(
                    revision="a" * 40,
                    attempts=8,
                    last_error="active max attempts",
                    updated_at=10.0,
                ),
                _publication_row(
                    revision="b" * 40,
                    attempts=4,
                    last_error="newest quarantined",
                    quarantined=True,
                    updated_at=20.0,
                ),
            ],
            ("mixed", True, False, 8, "newest quarantined"),
        ),
    )
    for rows, expected in cases:
        _write_outbox(home, rows)
        entry = load_chat_catalog().entries[0]
        assert (
            entry.publication_disposition,
            entry.publication_pending,
            entry.publication_quarantined,
            entry.publication_attempts,
            entry.publication_last_error,
        ) == expected


def test_remote_provenance_suppresses_colliding_local_publication_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sidecars,
        "resolve_sync_targets",
        lambda: TargetSelection(),
    )
    chat = _chat(home, "remote-collision-260724_160400")
    _artifact(
        home,
        "20260724160400",
        chat,
        name="alpha",
        meta_extra={
            "canonical_global_name": "bryan.athena.alpha",
            "imported_source_owner": {
                "username": "alice",
                "machine_name": "zeus",
            },
        },
    )
    _write_outbox(
        home,
        [
            _publication_row(
                attempts=2,
                last_error="local collision",
            )
        ],
    )

    entry = load_chat_catalog(force=True).entries[0]

    assert entry.provenance == "remote"
    assert entry.publication_pending is False
    assert entry.publication_quarantined is False
    assert entry.publication_attempts is None
    assert entry.publication_last_error is None
    assert entry.publication_disposition is None


def test_publication_transition_preserves_provenance_and_catalog_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _setup_home(monkeypatch, tmp_path)
    sidecar_path = _git_sidecar(tmp_path / "sidecar")
    monkeypatch.setattr(
        sidecars, "resolve_sync_targets", lambda: _selection(sidecar_path)
    )
    chat = _chat(home, "transition-260724_160500")
    _artifact(home, "20260724160500", chat)
    active = _publication_row(
        revision="a" * 40,
        attempts=1,
        last_error="push pending",
        updated_at=10.0,
    )
    quarantined = _publication_row(
        revision="a" * 40,
        attempts=3,
        last_error="prepare failed",
        quarantined=True,
        updated_at=20.0,
    )

    _write_outbox(home, [active])
    entry = load_chat_catalog(force=True).entries[0]
    assert (entry.provenance, entry.publication_disposition) == (
        "local",
        "queued",
    )

    _write_outbox(home, [quarantined])
    entry = load_chat_catalog().entries[0]
    assert (entry.provenance, entry.publication_disposition) == (
        "local",
        "quarantined",
    )

    published = sidecar_path / "agents" / "bryan.athena.alpha" / "chat.md"
    published.parent.mkdir(parents=True)
    published.write_text("prepared", encoding="utf-8")
    assert load_chat_catalog(force=True).entries[0].provenance == "local"

    _write_outbox(home, [active])
    _commit_sidecar(sidecar_path)
    entry = load_chat_catalog().entries[0]
    assert (entry.provenance, entry.publication_disposition) == (
        "shared",
        "queued",
    )

    _write_outbox(home, [quarantined])
    entry = load_chat_catalog().entries[0]
    assert (entry.provenance, entry.publication_disposition) == (
        "shared",
        "quarantined",
    )

    later_quarantined = _publication_row(
        revision="b" * 40,
        attempts=4,
        last_error="later revision failed",
        quarantined=True,
        updated_at=30.0,
    )
    _write_outbox(home, [active, later_quarantined])
    entry = load_chat_catalog().entries[0]
    assert (entry.provenance, entry.publication_disposition) == (
        "shared",
        "mixed",
    )

    _write_outbox(home, [])
    entry = load_chat_catalog().entries[0]
    assert entry.provenance == "shared"
    assert entry.publication_disposition is None
