"""Needs-attention apply outcomes for the Projects-tab init flow."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.init_plan_modal import InitPlanModal
from sase.ace.tui.modals.projects_pane_init_flow import (
    ProjectsInitFlowController,
    _APPLY_SEVERITY,
    _apply_payload_from_output,
)
from tests.ace.tui._projects_pane_init_flow_helpers import (
    _completion,
    _install_submit,
    _open_projects,
    _patch_panes,
)
from tests.ace.tui.modals.projects_pane_init_test_helpers import (
    sidecar_terminal_payload,
)
from tests.ace.tui.modals.test_new_project_init_outcomes import _Host


def test_needs_attention_summary_is_attention_kind_regardless_of_exit() -> None:
    for returncode in (0, 1):
        payload = _apply_payload_from_output(
            "Initialization summary: 1 checked, 1 needs attention",
            returncode,
        )
        assert payload.kind == "attention"
        assert _APPLY_SEVERITY[payload.kind] == "warning"
        assert "1 needs attention" in payload.message
        assert "press t to finish in a terminal" in payload.message


def test_needs_attention_summary_is_not_classified_current() -> None:
    payload = _apply_payload_from_output(
        "Initialization summary: 1 checked, 1 needs attention",
        0,
    )
    assert payload.kind != "current"
    assert payload.kind == "attention"


def test_mixed_failure_batch_stays_partial() -> None:
    payload = _apply_payload_from_output(
        "Initialization summary: 2 checked, 1 initialized, 1 failed",
        1,
    )
    assert payload.kind == "partial"


async def test_sidecar_payload_offers_terminal_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        await _open_projects(page)
        await page.press("i")
        await page.pause()
        _args, kwargs, handle = submitted[0]
        payload = sidecar_terminal_payload("alpha")
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await page.expect_modal("InitPlanModal")
        modal = page.app.screen
        assert isinstance(modal, InitPlanModal)
        await page.wait_for(lambda _s: len(modal.query("#init-plan-terminal")) > 0)
        assert modal._show_terminal is True


def test_needs_attention_apply_reports_not_initialized() -> None:
    host = _Host()
    flow = ProjectsInitFlowController(host)
    payload = _apply_payload_from_output(
        "Initialization summary: 1 checked, 1 needs attention",
        1,
    )
    handle = SimpleNamespace(proc_id="session-0")
    flow._on_init_apply_complete(
        _completion(
            handle.proc_id,
            payload,
            proc_type="init-apply",
            message=payload.message,
        )
    )
    assert host.outcomes == [False]
    assert host.notices == [(payload.message, "warning")]
