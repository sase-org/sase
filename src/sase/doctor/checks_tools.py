"""Tool checks for ``sase doctor``."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.core.clipboard import clipboard_available, clipboard_commands
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
        "prompt and generated skill Markdown formatting; missing Prettier can "
        "inflate skill-drift reports",
    ),
    _ToolRequirement(
        "dict",
        ("dict",),
        "prompt word definitions (K on a plain word)",
    ),
    _ToolRequirement(
        "aspell",
        ("aspell",),
        "prompt spell checking and fix suggestions (K on a plain word)",
    ),
)

_ASPELL_DICTIONARY_TIMEOUT_SECONDS = 2.0


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
            id="tools.tmux",
            group="tools",
            title="tmux command",
            runner=_check_tmux,
        ),
        CheckSpec(
            id="tools.clipboard",
            group="tools",
            title="System clipboard",
            runner=lambda: _check_clipboard(context),
        ),
        CheckSpec(
            id="tools.fzf",
            group="tools",
            title="fzf command",
            runner=_check_fzf,
        ),
        CheckSpec(
            id="tools.optional",
            group="tools",
            title="Optional feature tools",
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


def _check_tmux() -> DiagnosticCheck:
    """Check whether the tmux command is available for ACE tmux workflows."""
    resolved_path = shutil.which("tmux")
    if resolved_path:
        return DiagnosticCheck(
            id="tools.tmux",
            group="tools",
            status="OK",
            title="tmux command",
            summary="tmux is available for ACE tmux workflows",
            details=(f"Command: {resolved_path}",),
            data={
                "command": "tmux",
                "resolved_path": resolved_path,
                "required_for_agents": False,
            },
        )

    return DiagnosticCheck(
        id="tools.tmux",
        group="tools",
        status="WARN",
        title="tmux command",
        summary="tmux is not installed or not on PATH",
        details=(
            "`sase ace --tmux` exits with code 2 when tmux is missing.",
            "Agents can run without tmux, but workspace windows, inline artifact panes, and artifact zoom are degraded.",
        ),
        next_steps=("Install `tmux` or run ACE without `--tmux`.",),
        data={
            "command": "tmux",
            "resolved_path": None,
            "required_for_agents": False,
        },
    )


def _check_clipboard(
    context: DoctorContext,
    *,
    platform: str | None = None,
) -> DiagnosticCheck:
    """Check whether a system clipboard helper is available."""
    current_platform = sys.platform if platform is None else platform
    candidates = clipboard_commands(env=context.env, platform=current_platform)
    command_heads = tuple(dict.fromkeys(command[0] for command in candidates))
    available = clipboard_available(env=context.env, platform=current_platform)
    status: CheckStatus = "OK" if available else "WARN"

    return DiagnosticCheck(
        id="tools.clipboard",
        group="tools",
        status=status,
        title="System clipboard",
        summary=(
            "system clipboard helper is available"
            if available
            else _clipboard_missing_summary(current_platform)
        ),
        details=_clipboard_details(available=available, command_heads=command_heads),
        next_steps=_clipboard_next_steps(
            available=available,
            env=context.env,
            platform=current_platform,
        ),
        data={
            "available": available,
            "platform": current_platform,
            "wayland_session": bool(context.env.get("WAYLAND_DISPLAY")),
            "x11_session": bool(context.env.get("DISPLAY")),
            "commands": candidates,
            "command_heads": list(command_heads),
        },
    )


def _clipboard_missing_summary(platform: str) -> str:
    if platform == "darwin":
        return "pbcopy is not available for clipboard workflows"
    if platform.startswith("linux"):
        return "no Linux clipboard helper is available"
    return "no supported system clipboard helper is available"


def _clipboard_details(
    *,
    available: bool,
    command_heads: tuple[str, ...],
) -> tuple[str, ...]:
    if available:
        return ()
    if command_heads:
        return (
            f"Checked clipboard helper command(s): {', '.join(command_heads)}.",
            "Copy and yank workflows need one of these helpers on PATH.",
        )
    return ("No clipboard helper commands are registered for this platform.",)


def _clipboard_next_steps(
    *,
    available: bool,
    env: dict[str, str],
    platform: str,
) -> tuple[str, ...]:
    if available:
        return ()
    if platform == "darwin":
        return ("Ensure `pbcopy` is available on PATH.",)
    if platform.startswith("linux"):
        if env.get("WAYLAND_DISPLAY"):
            return ("Install `wl-clipboard` for the `wl-copy` command.",)
        if env.get("DISPLAY"):
            return ("Install `xclip` or `xsel` for X11 clipboard support.",)
        return (
            "Install `wl-clipboard`, `xclip`, or `xsel`, and ensure WAYLAND_DISPLAY or DISPLAY is set for graphical clipboard sessions.",
        )
    return (
        "Install a supported clipboard helper such as `wl-clipboard`, `xclip`, `xsel`, or `pbcopy` for your platform.",
    )


def _check_fzf() -> DiagnosticCheck:
    """Check whether fzf is available for prompt picker workflows."""
    resolved_path = shutil.which("fzf")
    if resolved_path:
        return DiagnosticCheck(
            id="tools.fzf",
            group="tools",
            status="OK",
            title="fzf command",
            summary="fzf is available for prompt pickers and prompt history",
            details=(f"Command: {resolved_path}",),
            data={
                "command": "fzf",
                "resolved_path": resolved_path,
                "required_for_agents": False,
            },
        )

    return DiagnosticCheck(
        id="tools.fzf",
        group="tools",
        status="WARN",
        title="fzf command",
        summary="fzf is not installed or not on PATH",
        details=(
            "Prompt pickers and editor prompt history require `fzf`.",
            "`sase prompt doctor` also reports prompt-history fzf availability.",
        ),
        next_steps=(
            "Install `fzf` to enable prompt pickers and prompt-history editing.",
        ),
        data={
            "command": "fzf",
            "resolved_path": None,
            "required_for_agents": False,
        },
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
    details = tuple(_optional_tool_missing_detail(row) for row in missing)

    return DiagnosticCheck(
        id="tools.optional",
        group="tools",
        status=status,
        title="Optional feature tools",
        summary=summary,
        details=details,
        data={"tools": rows},
    )


def _tool_row(requirement: _ToolRequirement) -> dict[str, Any]:
    resolved = {command: shutil.which(command) for command in requirement.commands}
    available = any(path is not None for path in resolved.values())
    row: dict[str, Any] = {
        "id": requirement.id,
        "commands": list(requirement.commands),
        "feature": requirement.feature,
        "any_of": requirement.any_of,
        "available": available,
        "resolved": resolved,
    }
    if requirement.id == "aspell" and available:
        aspell_path = resolved["aspell"]
        assert aspell_path is not None
        english_available, dictionaries, probe_detail = (
            _probe_aspell_english_dictionary(aspell_path)
        )
        row.update(
            {
                "available": english_available,
                "english_dictionary_available": english_available,
                "dictionaries": list(dictionaries),
                "probe_detail": probe_detail,
            }
        )
        if not english_available:
            row["missing_hint"] = _aspell_missing_dictionary_hint(probe_detail)
    return row


def _optional_tool_missing_detail(row: dict[str, Any]) -> str:
    missing_hint = row.get("missing_hint")
    if isinstance(missing_hint, str):
        return f"{row['feature']}: {missing_hint}"
    if row["any_of"]:
        return f"{row['feature']}: install one of {', '.join(row['commands'])}"
    return f"{row['feature']}: install {row['commands'][0]}"


def _aspell_missing_dictionary_hint(probe_detail: str) -> str:
    if probe_detail == "no English dictionary reported":
        return "aspell found but no English dictionary — install aspell-en"
    return (
        "aspell found but its English dictionary could not be verified "
        f"({probe_detail}) — install aspell-en"
    )


def _probe_aspell_english_dictionary(
    executable: str,
) -> tuple[bool, tuple[str, ...], str]:
    try:
        completed = subprocess.run(
            [executable, "dump", "dicts"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_ASPELL_DICTIONARY_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, (), "dictionary probe timed out after 2 seconds"
    except OSError as exc:
        return False, (), f"{type(exc).__name__}: {exc}"

    dictionaries = tuple(
        line.strip() for line in completed.stdout.splitlines() if line.strip()
    )
    if completed.returncode != 0:
        detail = next(
            (line.strip() for line in completed.stderr.splitlines() if line.strip()),
            f"dictionary probe exited {completed.returncode}",
        )
        return False, dictionaries, detail

    available = any(
        dictionary == "en"
        or dictionary.startswith("en_")
        or dictionary.startswith("en-")
        for dictionary in dictionaries
    )
    return (
        available,
        dictionaries,
        (
            "English dictionary available"
            if available
            else "no English dictionary reported"
        ),
    )


__all__ = [
    "tools_check_specs",
]
