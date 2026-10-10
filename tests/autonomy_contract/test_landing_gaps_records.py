"""Landing-gap contracts for autonomy record authority and refresh."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.autonomy.record import (
    apply_record_meta_patch,
    mutate_record,
    read_record,
    resolve_selection,
    with_legacy_projection,
)
from sase.feature_flags import override_flags
from tests.autonomy_contract import harness
from tests.autonomy_contract._landing_gaps_helpers import inputs


@pytest.mark.parametrize("flag_on", [True, False])
def test_record_authoritative_over_stale_legacy(tmp_path: Path, flag_on: bool) -> None:
    """A manual record with stale auto keys still reads manual everywhere."""
    from sase.core.agent_scan_wire_conversion import _agent_meta_from_dict

    with override_flags(autonomy_record_only=flag_on):
        manual = resolve_selection(None, source="prompt", surface="launch")
        mixed = {
            "autonomy": manual,
            "approve": True,
            "auto_approve_plan_action": "tale",
            "auto_approve_argument": "tale",
        }
        projected = with_legacy_projection(mixed)
        assert "approve" not in projected
        assert "auto_approve_plan_action" not in projected
        assert "auto_approve_argument" not in projected
        wire = _agent_meta_from_dict(dict(mixed))
        assert wire.approve is False


@pytest.mark.parametrize("flag_on", [True, False])
def test_apply_removes_stale_flag_off(tmp_path: Path, flag_on: bool) -> None:
    """Flag-off rewrites drop stale auto keys centrally, keeping ``plan``."""
    with override_flags(autonomy_record_only=flag_on):
        manual = resolve_selection(None, source="prompt", surface="launch")
        meta: dict[str, Any] = {
            "approve": True,
            "auto_approve_argument": "tale",
            "plan": True,
        }
        apply_record_meta_patch(meta, manual)
        assert meta["autonomy"] == manual
        if flag_on:
            assert "approve" not in meta
            assert "auto_approve_argument" not in meta
        else:
            assert "approve" not in meta
            assert "auto_approve_argument" not in meta
        assert meta.get("plan") is True


def test_human_mutation_source_truthful(tmp_path: Path) -> None:
    """A human TUI toggle records ``tui`` provenance, not ``prompt``."""
    base = resolve_selection("tale", source="prompt", surface="launch")
    outcome = mutate_record(base, "manual", actor_kind="human", surface="tui")
    assert outcome["record"]["source"] == "tui"
    outcome_cli = mutate_record(base, "manual", actor_kind="human", surface="cli")
    assert outcome_cli["record"]["source"] == "cli"


@pytest.mark.parametrize("flag_on", [True, False])
def test_refresh_preserves_live_record(
    tmp_path: Path, monkeypatch, flag_on: bool
) -> None:
    """A-off, refreshed metadata build, and A-on retain the tale restore state."""
    from sase.axe.run_agent_directive_metadata import preserved_agent_metadata
    from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV
    from sase.axe.run_agent_runner_refresh import reconcile_prompt_with_live_auto_state
    from sase.macro.directives import extract_prompt_directives

    with override_flags(autonomy_record_only=flag_on):
        _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
        harness.adapt_a_off(parent_dir)
        live = harness.read_meta(parent_dir)
        live_record = read_record(live)
        assert live_record is not None
        assert live_record["profile"] == "manual"
        assert live_record["revision"] == 2
        assert live_record["last"] == {"profile": "tale", "selection": "tale"}

        monkeypatch.setenv(RUNNER_CODE_REFRESHED_ENV, "1")
        preserved = preserved_agent_metadata(str(parent_dir))
        assert preserved.get("autonomy") == live_record
        submitted_prompt = "%auto:tale\nDo the work"
        refreshed_prompt = reconcile_prompt_with_live_auto_state(
            submitted_prompt, str(parent_dir)
        )
        assert refreshed_prompt == "Do the work"
        _, directives = extract_prompt_directives(refreshed_prompt)
        from sase.axe.run_agent_directive_metadata import build_agent_meta

        rebuilt = build_agent_meta(
            inputs(tmp_path, preserved),
            directives=directives,
            agent_name="contract-agent",
            agent_tribe=None,
            agent_session_attach_plan=None,
            clan_membership_plan=None,
        )
        harness.write_meta(parent_dir, rebuilt)
        rebuilt_record = read_record(rebuilt)
        assert rebuilt_record == live_record
        assert rebuilt_record["revision"] == 2
        assert rebuilt_record["last"] == {"profile": "tale", "selection": "tale"}

        monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
        fresh_preserved = preserved_agent_metadata(str(parent_dir))
        assert "autonomy" not in fresh_preserved

        restored = harness.adapt_a_on_bare(parent_dir)
        restored_record = read_record(restored)
        assert restored_record is not None
        assert restored_record["profile"] == "tale"
        assert restored_record["selection"] == "tale"
        assert restored_record["revision"] == 3
