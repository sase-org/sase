"""Wait-notice coverage for the comprehensive update flow."""

from __future__ import annotations

from sase.ace.tui.actions.update_run import UpdateRunActionsMixin
from sase.ace.tui.modals.plugins_browser_comprehensive_update_models import (
    ComprehensiveUpdatePreview,
    ComprehensiveUpdateRequest,
)
from sase.ace.tui.modals.plugins_browser_comprehensive_update_preview import (
    _sase_preview_section,
    build_comprehensive_update_preview,
)
from sase.ace.tui.modals.plugins_browser_dev_update import DevUpdatePreview
from sase.ace.update_scope import UpdateScope
from sase.dev_update.code_swap_lock import code_swap_reader_lock
from tests.ace.tui._plugins_browser_pane_update_helpers import _dev_plan
from tests.ace.tui._session_reporter import session_reporter

_PREVIEW_MOD = "sase.ace.tui.modals.plugins_browser_comprehensive_update_preview"


def _inputs(**overrides: object):
    from sase.ace.tui.update_preview_inputs import UpdatePreviewInputs

    values: dict[str, object] = {
        "uv_tool": None,
        "agent_cli_statuses": (),
        "agent_cli_error": None,
        "offline": False,
        "cached_status": None,
    }
    values.update(overrides)
    return UpdatePreviewInputs(**values)  # type: ignore[arg-type]


def test_comprehensive_preview_sets_wait_notice_while_reader_active(
    monkeypatch,
) -> None:
    plan = _dev_plan()
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.make_sase_dev_update_preview",
        lambda _receipt, **_kwargs: DevUpdatePreview(plan=plan, subject="sase"),
    )
    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ):
        preview = build_comprehensive_update_preview(
            ComprehensiveUpdateRequest((), UpdateScope.SASE),
            _inputs(),
        )
    assert preview.sase_blocker is None
    assert preview.sase_runnable is True
    assert preview.sase_wait_notice is not None
    assert "sase bead work" in preview.sase_wait_notice
    assert "plan.md" in preview.sase_wait_notice
    section = _sase_preview_section(preview)
    assert preview.sase_wait_notice in section.details


def test_comprehensive_preview_has_no_wait_notice_without_reader(
    monkeypatch,
) -> None:
    plan = _dev_plan()
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.make_sase_dev_update_preview",
        lambda _receipt, **_kwargs: DevUpdatePreview(plan=plan, subject="sase"),
    )
    preview = build_comprehensive_update_preview(
        ComprehensiveUpdateRequest((), UpdateScope.SASE),
        _inputs(),
    )
    assert preview.sase_wait_notice is None
    section = _sase_preview_section(preview)
    assert section.details == ()


class _UpdateRunHarness(UpdateRunActionsMixin):
    def __init__(self) -> None:
        self.notifies: list[tuple[str, str]] = []
        self.submitted: object = object()

    def _notify(self, message: str, **kwargs) -> None:  # type: ignore[override]
        self.notifies.append((message, kwargs.get("severity", "information")))


def _preview_with_notice(notice: str | None):
    plan = _dev_plan()
    return ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest((), UpdateScope.SASE),
        sase_preview=DevUpdatePreview(plan=plan, subject="sase"),
        sase_wait_notice=notice,
    )


def test_submit_scoped_update_task_emits_queue_toast_only_with_notice() -> None:
    harness = _UpdateRunHarness()

    def _submit(*_args, **_kwargs):
        return harness.submitted

    harness._submit_session_worker = _submit  # type: ignore[attr-defined]

    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ):
        from sase.ace.tui.modals.plugins_browser_dev_update import (
            dev_update_wait_notice,
        )

        notice = dev_update_wait_notice(_dev_plan())
        assert notice is not None

    assert harness._submit_scoped_update_task(_preview_with_notice(notice)) is True
    assert len(harness.notifies) == 1
    message, severity = harness.notifies[0]
    assert severity == "information"
    assert message.startswith("SASE update queued")
    assert "plan.md" in message

    harness.notifies.clear()
    assert harness._submit_scoped_update_task(_preview_with_notice(None)) is True
    assert harness.notifies == []


def test_reporter_code_swap_wait_sets_phase_and_cancel() -> None:
    reporter = session_reporter(proc_type="comprehensive-update")
    wait = reporter.code_swap_wait()
    assert wait.timeout_seconds == 30 * 60
    wait.on_wait("sase bead work (pid 1)")
    assert reporter.proc.phase == "Waiting for sase bead work (pid 1) to finish"
    assert wait.cancel_check is not None
    assert wait.cancel_check() == reporter.cancel_event.is_set()
    reporter.cancel_event.set()
    assert wait.cancel_check() is True
