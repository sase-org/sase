from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.repro import load_bundle, replay_agents_tab_bundle


FIXTURE = Path(__file__).parent / "fixtures" / "agents_tab_disappear_reappear_v1.json"


@pytest.mark.asyncio
async def test_legacy_control_reproduces_disappearing_rows() -> None:
    bundle = load_bundle(FIXTURE)

    result = await replay_agents_tab_bundle(bundle, merge_mode="legacy_replace")

    assert "post_complete_incomplete_shrink" in result.failed_invariant_codes
    assert "expected_visible_mismatch" in result.failed_invariant_codes
    assert "legacy control reproduced" in result.verdict


@pytest.mark.asyncio
async def test_current_code_preserves_rows_for_captured_bug_class() -> None:
    bundle = load_bundle(FIXTURE)

    result = await replay_agents_tab_bundle(bundle)

    assert result.ok, result.verdict
    assert result.verdict == "current code fixed for the captured Agents-tab bug class"
    final_step = result.steps[-1]
    assert (
        "workflow",
        "history_work",
        "20260510103000",
    ) in final_step.visible_identities
    assert (
        "workflow",
        "history_work",
        "20260510103000.01",
    ) in final_step.visible_identities
    assert final_step.agents_seen_complete_history is True
    assert isinstance(final_step.screen_text, str)
    assert "<svg" in final_step.svg
