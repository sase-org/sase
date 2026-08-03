"""Tests for the Rust bead prefix migration facade."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from sase.core import bead_prefix_migration as facade
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


def _fake_module(monkeypatch: pytest.MonkeyPatch, **bindings: Any) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    for name, binding in bindings.items():
        setattr(fake, name, binding)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)


def _outcome_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "preimage_digest": "pre",
        "postimage_digest": "post",
        "changed": True,
        "bead_id_map": {"old-1": "new-1"},
        "event_id_map": {"old-event": "new-event"},
        "token_counts": {"old-1": 2},
        "total_token_replacements": 2,
        "stream_count": 1,
        "event_count": 3,
        "issue_count": 1,
        "alias_additions": {"old-1": "new-1"},
        "lock_wait_ms": 7,
    }
    payload.update(overrides)
    return payload


def test_rewrite_tokens_rehydrates_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_rewrite(text: str, replacements: dict[str, str]) -> dict[str, Any]:
        calls.append((text, replacements))
        return {
            "text": "new-1, xold-1",
            "replacement_counts": {"old-1": 1},
            "total_replacements": 1,
        }

    _fake_module(monkeypatch, bead_rewrite_id_tokens=fake_rewrite)

    outcome = facade.rewrite_id_tokens("old-1, xold-1", {"old-1": "new-1"})

    assert calls == [("old-1, xold-1", {"old-1": "new-1"})]
    assert outcome.text == "new-1, xold-1"
    assert outcome.replacement_counts == {"old-1": 1}
    assert outcome.total_replacements == 1


def test_preview_and_apply_convert_request_and_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_preview(beads_dir: str, request: dict[str, Any]) -> dict[str, Any]:
        calls.append(("preview", beads_dir, request))
        return _outcome_payload(lock_wait_ms=0)

    def fake_apply(beads_dir: str, request: dict[str, Any]) -> dict[str, Any]:
        calls.append(("apply", beads_dir, request))
        return _outcome_payload()

    _fake_module(
        monkeypatch,
        bead_prefix_migration_preview=fake_preview,
        bead_prefix_migration_apply=fake_apply,
    )
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    request = facade.BeadPrefixMigrationRequest(
        from_prefix="old",
        to_prefix="new",
        agent_name_map={"old-agent": "new-agent"},
        expected_preimage_digest="pre",
    )

    preview = facade.preview_prefix_migration(beads_dir, request)
    applied = facade.apply_prefix_migration(beads_dir, request)

    expected_wire = {
        "from_prefix": "old",
        "to_prefix": "new",
        "agent_name_map": {"old-agent": "new-agent"},
        "expected_preimage_digest": "pre",
    }
    assert calls == [
        ("preview", str(beads_dir), expected_wire),
        ("apply", str(beads_dir), expected_wire),
    ]
    assert preview.bead_id_map == {"old-1": "new-1"}
    assert preview.lock_wait_ms == 0
    assert applied.event_id_map == {"old-event": "new-event"}
    assert applied.lock_wait_ms == 7


def test_validate_issue_prefix_delegates_to_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_validate(prefix: str) -> None:
        calls.append(prefix)

    _fake_module(monkeypatch, bead_validate_issue_prefix=fake_validate)

    facade.validate_issue_prefix("new-prefix")

    assert calls == ["new-prefix"]
