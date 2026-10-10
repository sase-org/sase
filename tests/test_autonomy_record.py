"""Autonomy record persistence and readers (``%auto`` E1 ``record`` phase).

Every launch persists ``agent_meta.autonomy`` and no legacy ``%auto``
meta keys. Every reader below goes through the record (or its legacy
translation), so record and legacy-only metas behave identically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.autonomy.record import (
    LEGACY_AUTONOMY_KEYS,
    apply_record_meta_patch,
    auto_applies,
    legacy_projection,
    live_record,
    read_record,
    record_meta_patch,
    resolve_selection,
    retune_meta_record,
)
from tests.autonomy_contract.harness import launch_meta
from tests.autonomy_contract.rows import SPELLING_ROWS

_TALE_PROMPT = "%auto:tale\nDo the work"

# (prompt, profile, selection, legacy keys) per spelling row.
_SPELLING_EXPECTATIONS: dict[str, tuple[str, str, str, dict[str, Any]]] = {
    "no_auto": ("Do the work", "manual", "manual", {}),
    "bare": ("%auto\nDo the work", "standard", "", {"approve": True}),
    "short_a": ("%a\nDo the work", "standard", "", {"approve": True}),
    "plus": ("%auto+\nDo the work", "standard", "", {"approve": True}),
    "true": ("%auto:true\nDo the work", "standard", "", {"approve": True}),
    "tale": (
        "%auto:tale\nDo the work",
        "tale",
        "tale",
        {
            "auto_approve_argument": "tale",
            "auto_approve_plan_action": "tale",
            "plan": True,
        },
    ),
    "plan": (
        "%auto:plan\nDo the work",
        "tale",
        "plan",
        {"approve": True, "auto_approve_argument": "plan"},
    ),
    "epic": (
        "%auto:epic\nDo the work",
        "epic",
        "epic",
        {
            "auto_approve_argument": "epic",
            "auto_approve_plan_action": "epic",
            "plan": True,
        },
    ),
    "manual": ("%auto:manual\nDo the work", "manual", "manual", {}),
    "off": ("%auto:off\nDo the work", "manual", "manual", {}),
}


def _launch(prompt: str, workdir: Path) -> dict[str, Any]:
    _, meta, _ = launch_meta(prompt, workdir)
    return meta


@pytest.mark.parametrize("row", SPELLING_ROWS, ids=[row.id for row in SPELLING_ROWS])
def test_launch_record_shape(row, tmp_path: Path) -> None:
    """Every spelling resolves to its record with no legacy keys."""
    prompt, profile, selection, legacy = _SPELLING_EXPECTATIONS[row.id]
    assert row.prompt == prompt

    meta = _launch(prompt, tmp_path)

    record = meta["autonomy"]
    assert record["profile"] == profile
    assert record["selection"] == selection
    assert record["revision"] == 1
    assert record["schema_version"] == 1

    # Launches write no legacy keys; the projection still reproduces
    # the historical writer keys for readers on the record.
    assert not any(key in meta for key in LEGACY_AUTONOMY_KEYS)
    projected = {
        key: value
        for key, value in legacy_projection(record).items()
        if key in LEGACY_AUTONOMY_KEYS and value not in (None, False)
    }
    assert projected == legacy


def test_tale_launch_acceptance(tmp_path: Path) -> None:
    """Acceptance: a fresh ``%auto:tale`` launch writes the tale record."""
    meta = _launch(_TALE_PROMPT, tmp_path)
    assert meta["autonomy"]["profile"] == "tale"
    assert meta["autonomy"]["selection"] == "tale"
    assert meta["autonomy"]["revision"] == 1
    assert not any(key in meta for key in LEGACY_AUTONOMY_KEYS)


def test_read_record_prefers_stored_record() -> None:
    stored = resolve_selection("epic", source="prompt", surface="launch")
    assert read_record({"approve": True, "autonomy": stored}) == stored


def test_read_record_translates_legacy_only() -> None:
    record = read_record({"approve": True, "auto_approve_argument": "plan"})
    assert record is not None
    assert record["profile"] == "tale"
    assert record["selection"] == "plan"
    assert record["source"] == "legacy"


def test_read_record_none_without_state() -> None:
    assert read_record({}) is None
    assert read_record(None) is None


def test_record_meta_patch_writes_no_legacy() -> None:
    record = resolve_selection("tale", source="prompt", surface="launch")
    patch = record_meta_patch(record)
    assert patch["autonomy"] == record
    assert set(patch) == {"autonomy"}


def test_record_meta_patch_manual_writes_no_legacy() -> None:
    record = resolve_selection(None, source="prompt", surface="launch")
    assert set(record_meta_patch(record)) == {"autonomy"}


def test_apply_record_meta_patch_removes_legacy() -> None:
    meta = {"approve": True, "plan": True}
    record = resolve_selection("", source="prompt", surface="launch")
    apply_record_meta_patch(meta, record)
    assert meta["autonomy"] == record
    assert "approve" not in meta
    assert "auto_approve_argument" not in meta
    assert "auto_approve_plan_action" not in meta
    # The dual-use ``plan`` flow marker is preserved.
    assert meta.get("plan") is True


def test_auto_applies_kinds() -> None:
    standard = resolve_selection("", source="prompt", surface="launch")
    tale = resolve_selection("tale", source="prompt", surface="launch")
    assert auto_applies(standard, "plan") is True
    assert auto_applies(standard, "epic_plan") is True
    assert auto_applies(standard, "question") is True
    assert auto_applies(tale, "plan") is True
    assert auto_applies(tale, "epic_plan") is False
    assert auto_applies(tale, "question") is True
    assert auto_applies(None, "plan") is False
    assert auto_applies(standard, "launch") is False
    assert auto_applies(standard, "no_such_kind") is False


def _write_live_meta(artifacts: Path, meta: dict[str, Any]) -> None:
    (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_plan_approve_readers_record_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production readers resolve a record-only meta identically."""
    from sase.main.plan_approve_handler import (
        get_auto_plan_approval_action,
        get_auto_plan_approval_argument,
        is_auto_approve_active,
    )

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    meta = _launch(_TALE_PROMPT, tmp_path / "work")
    _write_live_meta(artifacts, meta)

    assert get_auto_plan_approval_action() == "tale"
    assert get_auto_plan_approval_argument() == "tale"
    assert is_auto_approve_active() is True


def test_plan_approve_readers_manual_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_approve_handler import (
        get_auto_plan_approval_action,
        get_auto_plan_approval_argument,
        is_auto_approve_active,
    )

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    meta = _launch("Do the work", tmp_path / "work")
    _write_live_meta(artifacts, meta)

    assert get_auto_plan_approval_action() is None
    assert get_auto_plan_approval_argument() is None
    assert is_auto_approve_active() is False


def test_live_record_missing_is_none(tmp_path: Path) -> None:
    assert live_record(tmp_path / "nope") is None


def test_retune_after_toggle_off() -> None:
    meta = {
        "approve": True,
        "autonomy": resolve_selection("", source="prompt", surface="launch"),
    }
    del meta["approve"]
    retune_meta_record(meta)
    assert meta["autonomy"]["profile"] == "manual"
    assert not any(key in meta for key in LEGACY_AUTONOMY_KEYS)


def test_retune_after_toggle_on_drops_legacy() -> None:
    meta: dict[str, Any] = {}
    meta["approve"] = True
    retune_meta_record(meta)
    assert meta["autonomy"]["profile"] == "standard"
    assert "approve" not in meta


def test_plan_auto_covers_tier_matches_historical_tables() -> None:
    """The record-backed coverage helper keeps the historical truth table."""
    from sase._plan_gate_metadata import plan_auto_covers_tier

    tale_covered = {None, "", "plan", "tale"}
    epic_covered = {None, "", "epic", "epic_plan"}
    for argument in [None, "", "plan", "tale", "epic", "epic_plan", "foo", "manual"]:
        assert plan_auto_covers_tier("tale", argument) is (argument in tale_covered)
        assert plan_auto_covers_tier("epic", argument) is (argument in epic_covered)


def test_promotion_suffix_record_only() -> None:
    """A record-only ``%auto`` launch still promotes to the plan root."""
    from sase.agent._agent_session_promotion import agent_session_root_role_suffix

    tale = resolve_selection("tale", source="prompt", surface="launch")
    assert agent_session_root_role_suffix({"autonomy": tale}) == "--plan"
    manual = resolve_selection(None, source="prompt", surface="launch")
    assert agent_session_root_role_suffix({"autonomy": manual}) == "--0"


def test_filesystem_enrichment_record_only_matches_legacy(tmp_path: Path) -> None:
    """The TUI filesystem loader renders record-only metas identically."""
    from sase.ace.tui.models._loaders._meta_enrichment import enrich_agent_from_meta
    from tests._enrich_agent_helpers import make_agent

    tale = resolve_selection("tale", source="prompt", surface="launch")
    record_dir = tmp_path / "record"
    record_dir.mkdir()
    (record_dir / "agent_meta.json").write_text(json.dumps({"autonomy": tale}))
    record_agent = make_agent()
    enrich_agent_from_meta(record_agent, str(record_dir))

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "auto_approve_argument": "tale",
                "auto_approve_plan_action": "tale",
                "plan": True,
            }
        )
    )
    legacy_agent = make_agent()
    enrich_agent_from_meta(legacy_agent, str(legacy_dir))

    assert record_agent.auto_approve_plan_action == "tale"
    assert record_agent.approve is True
    assert (
        record_agent.auto_approve_plan_action == legacy_agent.auto_approve_plan_action
    )
    assert record_agent.approve == legacy_agent.approve


def test_wire_conversion_projects_record(tmp_path: Path) -> None:
    """The Python wire mirror derives legacy fields from the record."""
    from sase.core.agent_scan_wire_conversion import _agent_meta_from_dict

    tale = resolve_selection("tale", source="prompt", surface="launch")
    wire = _agent_meta_from_dict({"autonomy": tale, "name": "agent-x"})
    assert wire.auto_approve_plan_action == "tale"
    assert wire.auto_approve_argument == "tale"
    assert wire.approve is False
    assert wire.autonomy == tale

    # An existing valid record is authoritative: stale legacy keys cannot
    # override it, including false/absent projection values.
    wire = _agent_meta_from_dict(
        {"autonomy": tale, "approve": True, "auto_approve_argument": "plan"}
    )
    assert wire.approve is False
    assert wire.auto_approve_argument == "tale"
    assert wire.auto_approve_plan_action == "tale"
