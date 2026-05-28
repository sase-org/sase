"""Launch support for the SASE xprompt language server."""

from __future__ import annotations

import argparse
import importlib.resources
import json
import os
import shlex
import shutil
import sys
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import NoReturn

from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

SASE_XPROMPT_LSP_CMD_ENV = "SASE_XPROMPT_LSP_CMD"
SASE_XPROMPT_PACKAGE_DIR_ENV = "SASE_XPROMPT_PACKAGE_DIR"
SASE_XPROMPT_BUILTIN_DIR_ENV = "SASE_XPROMPT_BUILTIN_DIR"
SASE_XPROMPT_DEFAULT_DIR_ENV = "SASE_XPROMPT_DEFAULT_DIR"
SASE_DEFAULT_CONFIG_PATH_ENV = "SASE_DEFAULT_CONFIG_PATH"
SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV = "SASE_XPROMPT_PLUGIN_DIRS_JSON"
SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV = "SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON"
SASE_CORE_DIR_ENV = "SASE_CORE_DIR"
SASE_SIBLING_REPO_CORE_DIR_ENV = "SASE_SIBLING_REPO_CORE_DIR"
SASE_SIBLING_REPO_SASE_CORE_DIR_ENV = "SASE_SIBLING_REPO_SASE_CORE_DIR"
XPROMPT_LSP_BINARY = "sase-xprompt-lsp"


class _XPromptLspLaunchError(RuntimeError):
    """User-facing xprompt LSP startup error."""


def handle_xprompt_lsp_command(args: argparse.Namespace) -> NoReturn:
    """Exec the Rust xprompt LSP server for clean stdio and signal handling."""
    try:
        argv = _build_xprompt_lsp_argv(args)
        _prepare_xprompt_lsp_environment(os.environ)
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

    cargo = which("cargo")
    for sibling_core in _sase_core_dir_candidates(environ, repo_root):
        manifest = sibling_core / "Cargo.toml"
        if manifest.is_file():
            if cargo:
                return (
                    cargo,
                    "run",
                    "--manifest-path",
                    str(manifest),
                    "-p",
                    "sase_xprompt_lsp",
                    "--",
                )
            for candidate in (
                sibling_core / "target" / "debug" / XPROMPT_LSP_BINARY,
                sibling_core / "target" / "release" / XPROMPT_LSP_BINARY,
            ):
                if candidate.is_file():
                    return (str(candidate),)

    path = which(XPROMPT_LSP_BINARY)
    if path:
        return (path,)

    raise _XPromptLspLaunchError(
        "xprompt LSP binary not found; install `sase-xprompt-lsp` on PATH "
        f"or set {SASE_XPROMPT_LSP_CMD_ENV}"
    )


def _sase_core_dir_candidates(
    environ: Mapping[str, str],
    repo_root: Path | None,
) -> list[Path]:
    root = repo_root or Path(__file__).resolve().parents[3]
    candidates = [
        environ.get(SASE_CORE_DIR_ENV, ""),
        environ.get(SASE_SIBLING_REPO_CORE_DIR_ENV, ""),
        environ.get(SASE_SIBLING_REPO_SASE_CORE_DIR_ENV, ""),
        str(root.parent / "sase-core"),
    ]
    paths: list[Path] = []
    seen: set[str] = set()
    for raw in candidates:
        if not raw.strip():
            continue
        path = Path(raw).expanduser()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def _server_args_from_namespace(args: argparse.Namespace) -> list[str]:
    raw_args = list(_strip_remainder_sentinel(getattr(args, "lsp_args", [])))
    if bool(getattr(args, "version", False)):
        raw_args.insert(0, "--version")
    return raw_args


def _strip_remainder_sentinel(raw_args: Sequence[str]) -> Sequence[str]:
    if raw_args and raw_args[0] == "--":
        return raw_args[1:]
    return raw_args


def _prepare_xprompt_lsp_environment(
    environ: MutableMapping[str, str], package_dir: Path | None = None
) -> None:
    """Expose package xprompt locations to the Rust LSP catalog loader."""
    root = package_dir or Path(__file__).resolve().parents[1]
    defaults = {
        SASE_XPROMPT_PACKAGE_DIR_ENV: str(root),
        SASE_XPROMPT_BUILTIN_DIR_ENV: str(root / "xprompts"),
        SASE_XPROMPT_DEFAULT_DIR_ENV: str(root / "default_xprompts"),
        SASE_DEFAULT_CONFIG_PATH_ENV: str(root / "default_config.yml"),
    }
    for key, value in defaults.items():
        environ.setdefault(key, value)
    if SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV not in environ:
        environ[SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV] = json.dumps(
            _discover_plugin_xprompt_dirs()
        )
    if SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV not in environ:
        environ[SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV] = json.dumps(
            _discover_plugin_config_paths()
        )


def _discover_plugin_xprompt_dirs() -> list[dict[str, str]]:
    """Return concrete plugin xprompt directories for the Rust LSP loader."""
    if is_plugin_disabled("XPROMPTS"):
        return []

    entries: list[dict[str, str]] = []
    for module in discover_plugin_resources("sase_xprompts"):
        try:
            ref = importlib.resources.files(module).joinpath("xprompts")
        except (TypeError, AttributeError):
            continue
        path = Path(str(ref))
        if path.is_dir():
            entries.append(
                {"module": getattr(module, "__name__", str(module)), "path": str(path)}
            )
    return entries


def _discover_plugin_config_paths() -> list[dict[str, str]]:
    """Return concrete plugin default config files for the Rust LSP loader."""
    if is_plugin_disabled("CONFIG"):
        return []

    entries: list[dict[str, str]] = []
    for module in discover_plugin_resources("sase_config"):
        try:
            ref = importlib.resources.files(module).joinpath("default_config.yml")
        except (TypeError, AttributeError):
            continue
        path = Path(str(ref))
        if path.is_file():
            entries.append(
                {"module": getattr(module, "__name__", str(module)), "path": str(path)}
            )
    return entries
