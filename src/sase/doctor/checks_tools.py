"""Optional tool checks for ``sase doctor`` deep mode."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck

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
    """Return deep optional-tool check specs."""
    del context
    return (
        CheckSpec(
            id="tools.optional",
            group="tools",
            title="Optional tools",
            runner=_check_optional_tools,
            deep=True,
        ),
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
