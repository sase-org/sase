"""Optional tool checks for ``sase doctor`` deep mode."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.editor_resolver import EditorResolution, resolve_editor

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


@dataclass(frozen=True)
class _ToolRequirement:
    """One optional tool or any-of tool group."""

    id: str
    commands: tuple[str, ...]
    feature: str
    any_of: bool = False


_OPTIONAL_TOOLS: tuple[_ToolRequirement, ...] = (
    _ToolRequirement("tmux", ("tmux",), "ACE tmux windows and artifact panes"),
    _ToolRequirement("bat", ("bat",), "syntax-highlighted file previews"),
    _ToolRequirement("kitten", ("kitten",), "terminal image artifact display"),
    _ToolRequirement("mpv", ("mpv",), "terminal video artifact playback"),
    _ToolRequirement("pdftoppm", ("pdftoppm",), "PDF and Markdown artifact paging"),
    _ToolRequirement("pandoc", ("pandoc",), "Markdown-to-PDF artifact rendering"),
    _ToolRequirement(
        "pdf_engine",
        ("wkhtmltopdf", "xelatex", "pdflatex"),
        "PDF rendering from Markdown and xprompt catalogs",
        any_of=True,
    ),
    _ToolRequirement(
        "prettier",
        ("prettier",),
        "prompt and generated Markdown formatting",
    ),
)


def tools_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return tool check specs."""
    return (
        CheckSpec(
            id="tools.editor",
            group="tools",
            title="Editor command",
            runner=lambda: _check_editor(context),
        ),
        CheckSpec(
            id="tools.optional",
            group="tools",
            title="Optional tools",
            runner=_check_optional_tools,
            deep=True,
        ),
    )


def _check_editor(context: DoctorContext) -> DiagnosticCheck:
    """Check that SASE can resolve the configured editor command."""
    resolution = resolve_editor(env=context.env, which=shutil.which)
    status: CheckStatus = "OK" if resolution.status == "resolved" else "WARN"

    return DiagnosticCheck(
        id="tools.editor",
        group="tools",
        status=status,
        title="Editor command",
        summary=_editor_summary(resolution),
        details=_editor_details(resolution),
        next_steps=_editor_next_steps(resolution),
        data={
            "source": resolution.source,
            "configured": resolution.configured,
            "command": list(resolution.argv),
            "command_head": resolution.head,
            "resolved_path": resolution.resolved_path,
            "resolution_status": resolution.status,
        },
    )


def _editor_summary(resolution: EditorResolution) -> str:
    source_label = (
        f"${resolution.source}" if resolution.configured else "fallback editor"
    )
    if resolution.status == "resolved":
        return f"{source_label} resolves to {resolution.head}"
    if resolution.status == "missing":
        return f"{source_label} command head was not found: {resolution.head}"
    return f"{source_label} is a shell-style command that doctor cannot verify"


def _editor_details(resolution: EditorResolution) -> tuple[str, ...]:
    if resolution.status == "resolved":
        return (f"Command: {resolution.command_string}",)
    if resolution.status == "missing":
        checked = (
            "Checked $VISUAL, $EDITOR, nvim, and vim."
            if not resolution.configured
            else f"Configured value: {resolution.raw_value}"
        )
        return (checked,)
    return (
        f"Configured value: {resolution.raw_value}",
        "SASE launches editors as argv, not through an interactive shell.",
    )


def _editor_next_steps(resolution: EditorResolution) -> tuple[str, ...]:
    if resolution.status == "resolved":
        return ()
    if resolution.status == "missing":
        if resolution.configured:
            return (
                f"Install `{resolution.head}` or update ${resolution.source} to an executable editor command.",
            )
        return ("Install `nvim` or `vim`, or set $VISUAL/$EDITOR.",)
    return (
        "Set $VISUAL or $EDITOR to an executable command such as `nvim`, `vim`, or `code --wait`.",
    )


def _check_optional_tools() -> DiagnosticCheck:
    """Check optional executable availability with feature-specific warnings."""
    rows: list[dict[str, Any]] = [
        _tool_row(requirement) for requirement in _OPTIONAL_TOOLS
    ]
    missing = [row for row in rows if not row["available"]]
    status: CheckStatus = "WARN" if missing else "OK"
    summary = (
        f"{len(rows)} optional tool group(s) available"
        if not missing
        else f"{len(missing)} optional feature(s) are missing tools"
    )
    details = tuple(
        f"{row['feature']}: install one of {', '.join(row['commands'])}"
        if row["any_of"]
        else f"{row['feature']}: install {row['commands'][0]}"
        for row in missing
    )

    return DiagnosticCheck(
        id="tools.optional",
        group="tools",
        status=status,
        title="Optional tools",
        summary=summary,
        details=details,
        data={"tools": rows},
    )


def _tool_row(requirement: _ToolRequirement) -> dict[str, Any]:
    resolved = {command: shutil.which(command) for command in requirement.commands}
    available = any(path is not None for path in resolved.values())
    return {
        "id": requirement.id,
        "commands": list(requirement.commands),
        "feature": requirement.feature,
        "any_of": requirement.any_of,
        "available": available,
        "resolved": resolved,
    }


__all__ = [
    "tools_check_specs",
]
