"""Direct coverage for the typed sudo request modal."""

from __future__ import annotations

from pathlib import Path

from textual.app import App
from textual.widgets import Button, SelectionList

from sase.ace.tui.modals import (
    SudoCommandReviewData,
    SudoRequestModal,
    SudoRequestModalData,
    SudoRequestModalResult,
)
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea

_ROOT = Path(__file__).resolve().parents[3]


class _ModalHost(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"


def _data() -> SudoRequestModalData:
    return SudoRequestModalData(
        request_id="sudo-123",
        title="Sudo request: true",
        sender="sudo",
        reason="Refresh root-owned cache",
        commands=(
            SudoCommandReviewData(
                id="refresh",
                argv=("/usr/bin/true", "--refresh"),
                executable_sha256="sha256-refresh",
            ),
            SudoCommandReviewData(
                id="verify",
                argv=("/usr/bin/true", "--verify"),
                executable_sha256="sha256-verify",
            ),
        ),
        run_as="root",
        cwd="/tmp",
        env=(("LC_ALL", "C"),),
        timeout_seconds=30,
        stop_policy="terminate",
        output_policy="bounded",
        machine="athena",
        manifest_sha256="manifest-sha",
        risk_badges=("root", "writes"),
        requester="coder",
        project="sase",
        expires_at="2026-09-14T00:30:00+00:00",
        created_at="2026-09-14T00:00:00+00:00",
    )


async def test_sudo_modal_defaults_to_all_commands_and_runs_subset() -> None:
    modal = SudoRequestModal(_data())
    results: list[SudoRequestModalResult | None] = []
    async with _ModalHost().run_test() as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()

        selection = modal.query_one("#sudo-command-list", SelectionList)
        assert modal._selected_command_ids() == ("refresh", "verify")
        selection.deselect("verify")
        await pilot.pause()
        assert modal._selected_command_ids() == ("refresh",)

        modal.action_run()
        await pilot.pause()

    assert results == [
        SudoRequestModalResult(action="run", command_ids=("refresh",), feedback=None)
    ]


async def test_sudo_modal_refuses_empty_run_selection() -> None:
    modal = SudoRequestModal(_data())
    notices: list[tuple[str, str]] = []
    modal.notify = lambda message, **kwargs: notices.append(  # type: ignore[method-assign]
        (message, str(kwargs.get("severity", "information")))
    )
    results: list[SudoRequestModalResult | None] = []
    async with _ModalHost().run_test() as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()

        selection = modal.query_one("#sudo-command-list", SelectionList)
        selection.deselect_all()
        await pilot.pause()
        modal.action_run()
        await pilot.pause()

        assert modal.query_one("#sudo-run", Button).disabled is True

    assert results == []
    assert notices == [("Select at least one sudo command to run", "warning")]


async def test_sudo_modal_details_and_deny_feedback() -> None:
    modal = SudoRequestModal(_data())
    results: list[SudoRequestModalResult | None] = []
    async with _ModalHost().run_test() as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()

        modal.action_toggle_details()
        detail = modal._detail_markdown()
        assert "manifest_sha256" in detail
        assert "sha256-refresh" in detail

        modal.query_one(
            "#sudo-deny-feedback", SingleLineVimTextArea
        ).text = "Prefer a safer dry run"
        modal.action_deny()
        await pilot.pause()

    assert results == [
        SudoRequestModalResult(
            action="deny",
            command_ids=(),
            feedback="Prefer a safer dry run",
        )
    ]
