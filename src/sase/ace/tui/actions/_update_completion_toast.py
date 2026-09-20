"""Rich in-session completion toast for a finished comprehensive update."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual.markup import escape

from sase.ace._update_receipt_models import MAX_PROVIDER_LINES
from sase.ace.comprehensive_update import ComprehensiveUpdateResult
from sase.ace.update_receipt import ProviderUpdateReceiptResult, provider_receipt_result
from sase.ace.update_scope import UpdateLeg

from ._update_provider_toast_lines import provider_result_lines

COMPLETION_TOAST_TIMEOUT_SECONDS = 10.0

_SUCCESS_GLYPH = "✓"
_WARNING_GLYPH = "⚠"
_FAILURE_GLYPH = "✕"


@dataclass(frozen=True)
class _CompletionToast:
    """Title, Textual markup body, and severity for one completion toast."""

    title: str
    message: str
    severity: Literal["information", "warning", "error"]


def completion_toast(result: ComprehensiveUpdateResult) -> _CompletionToast:
    """Render *result* with the same per-provider fidelity as the restart toast."""
    sections: list[str] = []
    if UpdateLeg.SASE in result.selected_legs:
        sections.append(f"[bold]SASE, core & plugins[/]\n{escape(result.sase.message)}")
    if UpdateLeg.PROVIDERS in result.selected_legs:
        sections.append(_provider_section(result))
    return _CompletionToast(
        title=_title(result),
        message="\n\n".join(sections),
        severity=_severity(result),
    )


def _provider_section(result: ComprehensiveUpdateResult) -> str:
    provider_results = [
        provider_receipt_result(provider) for provider in result.provider_results
    ]
    if result.provider_error:
        provider_results.append(
            ProviderUpdateReceiptResult(
                name="agent-clis",
                display_name="Agent CLIs",
                status="failed",
                reason=result.provider_error,
            )
        )
    if not provider_results:
        return "[bold]Agent CLIs[/]: [dim]no captured work[/]"
    capped = provider_results[:MAX_PROVIDER_LINES]
    return provider_result_lines(
        capped, overflow=max(0, len(provider_results) - len(capped))
    )


def _title(result: ComprehensiveUpdateResult) -> str:
    if result.fully_failed:
        return f"{_FAILURE_GLYPH} Update failed"
    if result.has_failures:
        return f"{_WARNING_GLYPH} Update finished with issues"
    if (
        UpdateLeg.SASE not in result.selected_legs
        and result.has_successful_provider_change
    ):
        return f"{_SUCCESS_GLYPH} Providers updated"
    return f"{_SUCCESS_GLYPH} Update complete"


def _severity(
    result: ComprehensiveUpdateResult,
) -> Literal["information", "warning", "error"]:
    if result.fully_failed:
        return "error"
    if result.has_failures:
        return "warning"
    return "information"


__all__ = ["COMPLETION_TOAST_TIMEOUT_SECONDS", "completion_toast"]
