"""Markup rendering for the automatic ACE update toast."""

from __future__ import annotations

from collections.abc import Sequence

from textual.markup import escape

from sase.updates import CommitSummary, ProviderUpdateCandidate, UpdateStatus

from ..modals.config_center_modal import center_tab_accent
from ._update_toast_sections import ToastRepoSection, header_only_sections

_UPDATE_GLYPH = "↑"
_AGENT_CLI_ACCENT = "#00D7FF"
_COMMIT_SUBJECT_WIDTH = 58


def format_update_toast_message(
    status: UpdateStatus,
    sections: Sequence[ToastRepoSection] | None = None,
) -> str:
    """Build the Rich/Textual markup body for the update toast."""
    accent = center_tab_accent("updates") or "#AF87FF"
    count = status.count
    noun = "update" if count == 1 else "updates"
    repo_sections = (
        tuple(sections)
        if sections is not None
        else header_only_sections(status.components)
    )
    domain_counts: list[str] = []
    if status.component_count:
        component_noun = "update" if status.component_count == 1 else "updates"
        domain_counts.append(
            f"{status.component_count} SASE/core/plugin {component_noun}"
        )
    if status.agent_cli_count:
        provider_noun = "update" if status.agent_cli_count == 1 else "updates"
        domain_counts.append(f"{status.agent_cli_count} agent CLI {provider_noun}")
    summary = " · ".join(domain_counts)
    lines = [f"[bold {accent}]{count} {noun}[/] available · {summary}"]
    if repo_sections or status.provider_candidates:
        lines.append("")
    for index, section in enumerate(repo_sections):
        if index:
            lines.append("")
        lines.extend(_repo_section_lines(section, accent))
    if repo_sections and status.provider_candidates:
        lines.append("")
    for candidate in status.provider_candidates:
        lines.append(_provider_candidate_line(candidate))
    if repo_sections or status.provider_candidates:
        lines.append("")
    lines.append(_shortcut_line(accent))
    return "\n".join(lines)


def _repo_section_lines(section: ToastRepoSection, accent: str) -> list[str]:
    lines = [
        (
            f"[bold {accent}]{_UPDATE_GLYPH} {escape(section.label)}[/]  "
            f"[dim]{escape(section.installed_version)} → "
            f"{escape(section.latest_version)}[/]"
        )
    ]
    for commit in section.commits:
        lines.append(_commit_line(commit))
    extra = max(0, section.total - len(section.commits))
    if extra > 0:
        lines.append(f"  [dim]+{extra} more…[/]")
    return lines


def _commit_line(commit: CommitSummary) -> str:
    subject = _ellipsize(commit.subject.strip(), _COMMIT_SUBJECT_WIDTH)
    sha = escape(commit.short_sha.strip())
    if not subject:
        return f"  [dim]{sha}[/]"
    return f"  [dim]{sha}[/]  {escape(subject)}"


def _provider_candidate_line(candidate: ProviderUpdateCandidate) -> str:
    manual = "  [yellow]manual[/]" if candidate.manual_only else ""
    return (
        f"[bold {_AGENT_CLI_ACCENT}]{_UPDATE_GLYPH} CLI "
        f"{escape(candidate.display_name)}[/]  "
        f"[dim]{escape(candidate.installed_version)} → "
        f"{escape(candidate.latest_version)}[/]{manual}"
    )


def _shortcut_line(accent: str) -> str:
    return (
        f"Press [bold {accent}],U[/] to update the eligible set across "
        "SASE/core/plugins & agent CLIs"
    )


def _ellipsize(value: str, width: int) -> str:
    if width <= 0 or len(value) <= width:
        return value
    if width == 1:
        return "…"
    return f"{value[: width - 1]}…"
