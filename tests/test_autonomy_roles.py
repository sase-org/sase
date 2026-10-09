"""Unit tests for epic worker role assignments (``autonomy.roles``)."""

from __future__ import annotations

import logging

import pytest

from sase.autonomy.roles import (
    DEFAULT_ROLE_PROFILE,
    EPIC_LAND_ROLE,
    EPIC_PHASE_ROLE,
    role_assignments,
    role_auto_directive,
    role_profile,
)


def _patch_config(monkeypatch: pytest.MonkeyPatch, merged: object) -> None:
    monkeypatch.setattr("sase.config.load_merged_config", lambda: merged, raising=False)


def test_directive_mapping_defaults_to_bare_auto() -> None:
    assert DEFAULT_ROLE_PROFILE == "standard"
    assert role_auto_directive(EPIC_PHASE_ROLE) == "%auto"
    assert role_auto_directive(EPIC_LAND_ROLE) == "%auto"


def test_each_builtin_maps_to_expected_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for profile, directive in [
        ("standard", "%auto"),
        ("tale", "%auto:tale"),
        ("epic", "%auto:epic"),
        ("manual", "%auto:manual"),
    ]:
        _patch_config(monkeypatch, {"autonomy": {"roles": {EPIC_PHASE_ROLE: profile}}})
        assert role_auto_directive(EPIC_PHASE_ROLE) == directive


def test_directive_round_trips_through_resolve_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.autonomy.record import resolve_selection

    for profile in ["standard", "tale", "epic", "manual"]:
        _patch_config(monkeypatch, {"autonomy": {"roles": {EPIC_PHASE_ROLE: profile}}})
        directive = role_auto_directive(EPIC_PHASE_ROLE)
        selection = directive.removeprefix("%auto").removeprefix(":")
        record = resolve_selection(selection, source="prompt", surface="launch")
        assert record.get("profile") == profile


def test_source_values_config_default_invalid(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_config(monkeypatch, {"autonomy": {"roles": {EPIC_PHASE_ROLE: "tale"}}})
    assert role_profile(EPIC_PHASE_ROLE) == {
        "role": EPIC_PHASE_ROLE,
        "profile": "tale",
        "source": "config",
    }

    _patch_config(monkeypatch, {})
    assert role_profile(EPIC_PHASE_ROLE)["source"] == "default"
    assert role_profile(EPIC_PHASE_ROLE)["profile"] == "standard"

    _patch_config(monkeypatch, {"autonomy": {"roles": {EPIC_PHASE_ROLE: "bogus"}}})
    with caplog.at_level(logging.WARNING):
        assignment = role_profile(EPIC_PHASE_ROLE)
    assert assignment["source"] == "invalid"
    assert assignment["profile"] == "standard"
    assert "bogus" in caplog.text


def test_whitespace_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(monkeypatch, {"autonomy": {"roles": {EPIC_PHASE_ROLE: "  tale  "}}})
    assignment = role_profile(EPIC_PHASE_ROLE)
    assert assignment["profile"] == "tale"
    assert assignment["source"] == "config"


def test_non_dict_sections_fall_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for bad in [
        {"autonomy": "nope"},
        {"autonomy": {"roles": "nope"}},
        {"autonomy": {"roles": {EPIC_PHASE_ROLE: 123}}},
        {"autonomy": {"roles": {EPIC_PHASE_ROLE: None}}},
        "nope",
        None,
    ]:
        _patch_config(monkeypatch, bad)
        assignment = role_profile(EPIC_PHASE_ROLE)
        assert assignment["profile"] == "standard"
        assert assignment["source"] == "default"


def test_role_assignments_fixed_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(
        monkeypatch,
        {"autonomy": {"roles": {EPIC_PHASE_ROLE: "tale", EPIC_LAND_ROLE: "manual"}}},
    )
    assignments = role_assignments()
    assert [item["role"] for item in assignments] == [EPIC_PHASE_ROLE, EPIC_LAND_ROLE]
    assert assignments[0]["profile"] == "tale"
    assert assignments[1]["profile"] == "manual"


def test_render_uses_role_directives(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from sase.bead import db as _db
    from sase.bead.work_plan import _build_epic_work_plan
    from sase.bead.work_prompt import render_multi_prompt
    from sase.macro.workflow_models import Workflow
    from tests.test_bead.work_test_helpers import epic as _epic
    from tests.test_bead.work_test_helpers import phase as _phase
    from tests.test_bead.work_test_helpers import seed as _seed

    conn = _db.init_db(tmp_path / "roles-test.db")
    try:
        _seed(conn, [_epic("e1"), _phase("p1")])
        plan = _build_epic_work_plan(conn, "e1")

        def _render() -> str:
            return render_multi_prompt(
                plan,
                work_phase_macro=Workflow(name="bd/work_phase_bead"),
                land_epic_macro=Workflow(name="bd/land_epic"),
            )

        _patch_config(monkeypatch, {})
        rendered = _render()
        segments = rendered.split("\n---\n")
        assert all("%auto" in segment.splitlines() for segment in segments)
        assert all("%auto:tale" not in segment.splitlines() for segment in segments)

        _patch_config(
            monkeypatch,
            {
                "autonomy": {
                    "roles": {EPIC_PHASE_ROLE: "tale", EPIC_LAND_ROLE: "manual"}
                }
            },
        )
        rendered = _render()
        segments = rendered.split("\n---\n")
        assert "%auto:tale" in segments[0].splitlines()
        assert "%auto:manual" in segments[-1].splitlines()

        _patch_config(monkeypatch, {"autonomy": {"roles": {EPIC_PHASE_ROLE: "bogus"}}})
        rendered = _render()
        segments = rendered.split("\n---\n")
        assert "%auto" in segments[0].splitlines()
    finally:
        conn.close()
