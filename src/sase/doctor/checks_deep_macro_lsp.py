"""Deep macro LSP resolution checks for ``sase doctor``."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sase.diagnostics import DiagnosticCheck
from sase.integrations import macro_lsp

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


def check_macro_lsp(context: DoctorContext) -> DiagnosticCheck:
    """Mirror the ``sase lsp`` server-command resolver without launching it."""
    try:
        command = macro_lsp.resolve_macro_lsp_command(
            environ=context.env,
            which=shutil.which,
            repo_root=None,
        )
    except macro_lsp.MacroLspLaunchError as exc:
        return DiagnosticCheck(
            id="tools.macro_lsp",
            group="tools",
            status="WARN",
            title="macro LSP command",
            summary="macro LSP server command does not resolve",
            details=(
                str(exc),
                "Editor macro completions and diagnostics require this server.",
            ),
            next_steps=(
                "Install `sase-macro-lsp` into the current venv or PATH, build the sibling `sase-core` LSP binary, or set $SASE_MACRO_LSP_CMD.",
            ),
            data={
                "resolved": False,
                "command": [],
                "source": None,
                "env_var": macro_lsp.SASE_MACRO_LSP_CMD_ENV,
                "env_override_set": bool(
                    context.env.get(macro_lsp.SASE_MACRO_LSP_CMD_ENV, "").strip()
                ),
                "cargo_fallback": False,
                "error": str(exc),
            },
        )

    source = _macro_lsp_command_source(command, context.env)
    cargo_fallback = _is_macro_lsp_cargo_run(command)
    if cargo_fallback:
        return DiagnosticCheck(
            id="tools.macro_lsp",
            group="tools",
            status="WARN",
            title="macro LSP command",
            summary="macro LSP resolves through the slow cargo fallback",
            details=(
                f"Command: {_format_command(command)}",
                "Editor startup can be slow because Cargo must check or build the Rust LSP package before serving requests.",
            ),
            next_steps=(
                "Install `sase-macro-lsp` into the current venv or PATH, or build the sibling `sase-core` LSP binary once.",
            ),
            data={
                "resolved": True,
                "command": list(command),
                "source": source,
                "env_var": macro_lsp.SASE_MACRO_LSP_CMD_ENV,
                "env_override_set": bool(
                    context.env.get(macro_lsp.SASE_MACRO_LSP_CMD_ENV, "").strip()
                ),
                "cargo_fallback": True,
            },
        )

    return DiagnosticCheck(
        id="tools.macro_lsp",
        group="tools",
        status="OK",
        title="macro LSP command",
        summary=f"macro LSP server resolves via {source}",
        details=(f"Command: {_format_command(command)}",),
        data={
            "resolved": True,
            "command": list(command),
            "source": source,
            "env_var": macro_lsp.SASE_MACRO_LSP_CMD_ENV,
            "env_override_set": bool(
                context.env.get(macro_lsp.SASE_MACRO_LSP_CMD_ENV, "").strip()
            ),
            "cargo_fallback": False,
        },
    )


def _macro_lsp_command_source(
    command: tuple[str, ...],
    env: dict[str, str],
) -> str:
    if env.get(macro_lsp.SASE_MACRO_LSP_CMD_ENV, "").strip():
        return "SASE_MACRO_LSP_CMD"
    if env.get(macro_lsp.SASE_XPROMPT_LSP_CMD_ENV, "").strip():
        return "SASE_XPROMPT_LSP_CMD"
    if _is_macro_lsp_cargo_run(command):
        return "cargo fallback"
    if len(command) != 1:
        return "command"

    path = Path(command[0])
    if path.name not in _macro_lsp_binary_names():
        return "command"

    python_bin_dir = Path(sys.executable).parent
    if _is_relative_to(path, python_bin_dir):
        return "current venv"

    repo_root = Path(__file__).resolve().parents[3]
    sibling_core = repo_root.parent / "sase-core"
    if _is_relative_to(path, sibling_core / "target"):
        return "sibling sase-core build"

    return "PATH"


def _is_macro_lsp_cargo_run(command: tuple[str, ...]) -> bool:
    return (
        len(command) >= 2
        and Path(command[0]).name == "cargo"
        and command[1] == "run"
        and ("sase_xprompt_lsp" in command or "sase_macro_lsp" in command)
    )


def _macro_lsp_binary_names() -> tuple[str, ...]:
    if os.name == "nt":
        return (
            f"{macro_lsp.MACRO_LSP_BINARY}.exe",
            macro_lsp.MACRO_LSP_BINARY,
            f"{macro_lsp.XPROMPT_LSP_BINARY}.exe",
            macro_lsp.XPROMPT_LSP_BINARY,
        )
    return (macro_lsp.MACRO_LSP_BINARY, macro_lsp.XPROMPT_LSP_BINARY)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def _format_command(command: tuple[str, ...]) -> str:
    return " ".join(command)
