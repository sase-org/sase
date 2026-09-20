"""Tests for the in-session comprehensive-update completion toast."""

from __future__ import annotations

from types import SimpleNamespace

from textual.markup import escape

from sase.ace._update_receipt_models import MAX_PROVIDER_LINES
from sase.ace.comprehensive_update import (
    ComprehensiveSaseUpdateResult,
    ComprehensiveUpdateResult,
    SaseUpdateResultStatus,
)
from sase.ace.tui.actions._update_completion_toast import completion_toast
from sase.ace.update_scope import UpdateLeg
from sase.agent_clis.models import AgentCliUpdateResult, UpdateResultStatus

_PROVIDERS_ONLY = frozenset({UpdateLeg.PROVIDERS})


def _provider(
    name: str,
    display_name: str,
    status: UpdateResultStatus,
    *,
    old: str | None = None,
    new: str | None = None,
    reason: str | None = None,
    suggested_command: tuple[str, ...] | None = None,
) -> AgentCliUpdateResult:
    return AgentCliUpdateResult(
        name=name,
        display_name=display_name,
        status=status,
        old_version=old,
        new_version=new,
        command=None,
        docs_url=None,
        suggested_command=suggested_command,
        reason=reason,
    )


def _result(
    *providers: AgentCliUpdateResult,
    selected: frozenset[UpdateLeg] = _PROVIDERS_ONLY,
    provider_error: str | None = None,
    sase_status: SaseUpdateResultStatus = SaseUpdateResultStatus.SKIPPED,
    sase_message: str = "not selected",
    code_changed: bool = False,
) -> ComprehensiveUpdateResult:
    return ComprehensiveUpdateResult(
        sase=ComprehensiveSaseUpdateResult(
            sase_status,
            sase_message,
            SimpleNamespace(changed=True) if code_changed else None,  # type: ignore[arg-type]
        ),
        provider_results=providers,
        provider_error=provider_error,
        selected_legs=selected,
    )


def test_providers_only_result_names_each_provider_with_transition() -> None:
    toast = completion_toast(
        _result(
            _provider(
                "claude",
                "Claude Code",
                UpdateResultStatus.UPDATED,
                old="2.1.0",
                new="2.2.0",
            ),
            _provider("codex", "Codex CLI", UpdateResultStatus.ALREADY_CURRENT),
        )
    )

    assert toast.title == "✓ Providers updated"
    assert toast.severity == "information"
    assert toast.message == (
        "[bold]Agent CLIs[/]\n"
        "• Claude Code: [dim]2.1.0 →[/] [green]2.2.0[/]\n"
        "• Codex CLI: [dim]already current[/]"
    )
    assert "SASE, core & plugins" not in toast.message


def test_manual_provider_shows_reason_and_command() -> None:
    toast = completion_toast(
        _result(
            _provider(
                "codex",
                "Codex CLI",
                UpdateResultStatus.SKIPPED,
                reason="Homebrew requires a manual upgrade",
                suggested_command=("brew", "upgrade", "codex"),
            ),
        )
    )

    assert "• Codex CLI: [yellow]manual[/] — Homebrew requires a manual upgrade" in (
        toast.message
    )
    assert "  [dim]brew upgrade codex[/]" in toast.message
    assert toast.severity == "information"
    assert toast.title == "✓ Update complete"


def test_provider_failure_with_other_success_is_a_warning() -> None:
    toast = completion_toast(
        _result(
            _provider(
                "claude",
                "Claude Code",
                UpdateResultStatus.UPDATED,
                old="2.1.0",
                new="2.2.0",
            ),
            _provider("codex", "Codex CLI", UpdateResultStatus.FAILED, reason="exit 1"),
        )
    )

    assert toast.severity == "warning"
    assert toast.title == "⚠ Update finished with issues"
    assert "• Codex CLI: [red]failed[/] — exit 1" in toast.message


def test_fully_failed_result_is_an_error() -> None:
    toast = completion_toast(
        _result(
            _provider("codex", "Codex CLI", UpdateResultStatus.FAILED, reason="exit 1"),
        )
    )

    assert toast.severity == "error"
    assert toast.title == "✕ Update failed"


def test_provider_error_appears_as_failed_agent_cli_entry() -> None:
    toast = completion_toast(_result(provider_error="planning exploded"))

    assert toast.severity == "error"
    assert toast.title == "✕ Update failed"
    assert toast.message == (
        "[bold]Agent CLIs[/]\n• Agent CLIs: [red]failed[/] — planning exploded"
    )


def test_provider_error_is_appended_after_provider_results() -> None:
    toast = completion_toast(
        _result(
            _provider(
                "claude",
                "Claude Code",
                UpdateResultStatus.UPDATED,
                old="2.1.0",
                new="2.2.0",
            ),
            provider_error="late failure",
        )
    )

    lines = toast.message.split("\n")
    assert lines[-1] == "• Agent CLIs: [red]failed[/] — late failure"
    assert lines[1].startswith("• Claude Code:")
    assert toast.severity == "warning"


def test_sase_leg_line_is_included_when_selected() -> None:
    toast = completion_toast(
        _result(
            _provider(
                "claude",
                "Claude Code",
                UpdateResultStatus.UPDATED,
                old="2.1.0",
                new="2.2.0",
            ),
            selected=frozenset({UpdateLeg.SASE, UpdateLeg.PROVIDERS}),
            sase_status=SaseUpdateResultStatus.ALREADY_CURRENT,
            sase_message="already current",
        )
    )

    sections = toast.message.split("\n\n")
    assert sections[0] == "[bold]SASE, core & plugins[/]\nalready current"
    assert sections[1].startswith("[bold]Agent CLIs[/]")
    assert toast.title == "✓ Update complete"


def test_sase_only_result_omits_provider_block() -> None:
    toast = completion_toast(
        _result(
            selected=frozenset({UpdateLeg.SASE}),
            sase_status=SaseUpdateResultStatus.ALREADY_CURRENT,
            sase_message="already current",
        )
    )

    assert toast.message == "[bold]SASE, core & plugins[/]\nalready current"
    assert "Agent CLIs" not in toast.message


def test_empty_provider_results_render_no_captured_work() -> None:
    toast = completion_toast(_result())

    assert toast.message == "[bold]Agent CLIs[/]: [dim]no captured work[/]"
    assert toast.title == "✓ Update complete"
    assert toast.severity == "information"


def test_provider_lines_are_capped_with_overflow_count() -> None:
    providers = tuple(
        _provider(
            f"p{index}",
            f"Provider {index}",
            UpdateResultStatus.UPDATED,
            old="1.0.0",
            new="1.1.0",
        )
        for index in range(MAX_PROVIDER_LINES + 2)
    )
    toast = completion_toast(_result(*providers))

    lines = toast.message.split("\n")
    assert len(lines) == 1 + MAX_PROVIDER_LINES + 1
    assert lines[-1] == "…and 2 more provider results"
    assert f"Provider {MAX_PROVIDER_LINES - 1}:" in lines[-2]
    assert f"Provider {MAX_PROVIDER_LINES}:" not in toast.message


def test_markup_significant_characters_are_escaped() -> None:
    toast = completion_toast(
        _result(
            _provider(
                "odd",
                "Odd [red]CLI",
                UpdateResultStatus.UPDATED,
                old="1.0[0",
                new="2.0[/]",
            ),
            _provider(
                "bad",
                "Bad [b]CLI",
                UpdateResultStatus.FAILED,
                reason="oops [/bold]",
            ),
            selected=frozenset({UpdateLeg.SASE, UpdateLeg.PROVIDERS}),
            sase_message="sase [bold]updated",
            sase_status=SaseUpdateResultStatus.UPDATED,
        )
    )

    for raw in ("Odd [red]CLI", "1.0[0", "2.0[/]", "Bad [b]CLI", "oops [/bold]"):
        assert escape(raw) in toast.message
    assert escape("sase [bold]updated") in toast.message
    assert "Odd [red]CLI" not in toast.message
    assert "sase [bold]updated" not in toast.message
