"""Launch support for the SASE xprompt language server."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NoReturn

SASE_XPROMPT_LSP_CMD_ENV = "SASE_XPROMPT_LSP_CMD"
XPROMPT_LSP_BINARY = "sase-xprompt-lsp"


class _XPromptLspLaunchError(RuntimeError):
    """User-facing xprompt LSP startup error."""


def handle_xprompt_lsp_command(args: argparse.Namespace) -> NoReturn:
    """Exec the Rust xprompt LSP server for clean stdio and signal handling."""
    try:
        argv = _build_xprompt_lsp_argv(args)
        os.execvp(argv[0], argv)
    except _XPromptLspLaunchError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"Error: failed to launch xprompt LSP: {exc}", file=sys.stderr)
        sys.exit(1)

    raise AssertionError("os.execvp unexpectedly returned")


def _build_xprompt_lsp_argv(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    repo_root: Path | None = None,
) -> list[str]:
    """Resolve the LSP command and append wrapper/server arguments."""
    command = _resolve_xprompt_lsp_command(
        environ=os.environ if environ is None else environ,
        which=which,
        repo_root=repo_root,
    )
    server_args = _server_args_from_namespace(args)
    return [*command, *server_args]


def _resolve_xprompt_lsp_command(
    *,
    environ: Mapping[str, str],
    which: Callable[[str], str | None],
    repo_root: Path | None,
) -> tuple[str, ...]:
    override = environ.get(SASE_XPROMPT_LSP_CMD_ENV, "").strip()
    if override:
        try:
            command = tuple(shlex.split(override))
        except ValueError as exc:
            raise _XPromptLspLaunchError(
                f"{SASE_XPROMPT_LSP_CMD_ENV} is not a valid shell-style command: {exc}"
            ) from exc
        if command:
            return command

    path = which(XPROMPT_LSP_BINARY)
    if path:
        return (path,)

    root = repo_root or Path(__file__).resolve().parents[3]
    sibling_core = root.parent / "sase-core"
    for candidate in (
        sibling_core / "target" / "debug" / XPROMPT_LSP_BINARY,
        sibling_core / "target" / "release" / XPROMPT_LSP_BINARY,
    ):
        if candidate.is_file():
            return (str(candidate),)

    cargo = which("cargo")
    manifest = sibling_core / "Cargo.toml"
    if cargo and manifest.is_file():
        return (
            cargo,
            "run",
            "--manifest-path",
            str(manifest),
            "-p",
            "sase_xprompt_lsp",
            "--",
        )

    raise _XPromptLspLaunchError(
        "xprompt LSP binary not found; install `sase-xprompt-lsp` on PATH "
        f"or set {SASE_XPROMPT_LSP_CMD_ENV}"
    )


def _server_args_from_namespace(args: argparse.Namespace) -> list[str]:
    raw_args = list(_strip_remainder_sentinel(getattr(args, "lsp_args", [])))
    if bool(getattr(args, "version", False)):
        raw_args.insert(0, "--version")
    return raw_args


def _strip_remainder_sentinel(raw_args: Sequence[str]) -> Sequence[str]:
    if raw_args and raw_args[0] == "--":
        return raw_args[1:]
    return raw_args
