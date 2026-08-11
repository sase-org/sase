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

from sase.core.paths import sase_subdir
from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled
from sase.xprompt.loader_skills import get_sase_package_skills_dir

SASE_XPROMPT_LSP_CMD_ENV = "SASE_XPROMPT_LSP_CMD"
SASE_XPROMPT_PACKAGE_DIR_ENV = "SASE_XPROMPT_PACKAGE_DIR"
SASE_XPROMPT_BUILTIN_DIR_ENV = "SASE_XPROMPT_BUILTIN_DIR"
SASE_SKILL_BUILTIN_DIR_ENV = "SASE_SKILL_BUILTIN_DIR"
SASE_XPROMPT_DEFAULT_DIR_ENV = "SASE_XPROMPT_DEFAULT_DIR"
SASE_DEFAULT_CONFIG_PATH_ENV = "SASE_DEFAULT_CONFIG_PATH"
SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV = "SASE_XPROMPT_PLUGIN_DIRS_JSON"
SASE_SKILL_PLUGIN_DIRS_JSON_ENV = "SASE_SKILL_PLUGIN_DIRS_JSON"
SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV = "SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON"
SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV = "SASE_XPROMPT_VCS_PROJECT_CATALOG"
SASE_XPROMPT_MODEL_CATALOG_ENV = "SASE_XPROMPT_MODEL_CATALOG"
SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV = "SASE_XPROMPT_ARTIFACT_REF_CATALOG"
SASE_XPROMPT_GLOSSARY_CATALOG_ENV = "SASE_XPROMPT_GLOSSARY_CATALOG"
XPROMPT_LSP_BINARY = "sase-xprompt-lsp"


class XPromptLspLaunchError(RuntimeError):
    """User-facing xprompt LSP startup error."""


_XPromptLspLaunchError = XPromptLspLaunchError


def handle_xprompt_lsp_command(args: argparse.Namespace) -> NoReturn:
    """Exec the Rust xprompt LSP server for clean stdio and signal handling."""
    try:
        argv = _build_xprompt_lsp_argv(args)
        _prepare_xprompt_lsp_environment(os.environ)
        os.execvp(argv[0], argv)
    except XPromptLspLaunchError as exc:
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


def resolve_xprompt_lsp_command(
    *,
    environ: Mapping[str, str],
    which: Callable[[str], str | None] = shutil.which,
    repo_root: Path | None = None,
) -> tuple[str, ...]:
    """Resolve the xprompt LSP server command without launching it."""
    return _resolve_xprompt_lsp_command(
        environ=environ,
        which=which,
        repo_root=repo_root,
    )


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
            raise XPromptLspLaunchError(
                f"{SASE_XPROMPT_LSP_CMD_ENV} is not a valid shell-style command: {exc}"
            ) from exc
        if command:
            recovered = _recover_unquoted_command_path_with_spaces(
                override,
                command,
                which=which,
            )
            return recovered or command

    venv_binary = _first_existing_xprompt_lsp_binary(Path(sys.executable).parent)
    if venv_binary is not None:
        return (str(venv_binary),)

    path = which(XPROMPT_LSP_BINARY)
    if path:
        return (path,)

    root = repo_root or Path(__file__).resolve().parents[3]
    sibling_core = root.parent / "sase-core"
    target_binary = _newest_existing_xprompt_lsp_binary(
        (
            sibling_core / "target" / "debug",
            sibling_core / "target" / "release",
        )
    )
    if target_binary is not None:
        return (str(target_binary),)

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

    raise XPromptLspLaunchError(
        "xprompt LSP binary not found; install `sase-xprompt-lsp` into the "
        f"current venv, install it on PATH, or set {SASE_XPROMPT_LSP_CMD_ENV}"
    )


def _first_existing_xprompt_lsp_binary(directory: Path) -> Path | None:
    for candidate in _xprompt_lsp_binary_candidates(directory):
        if candidate.is_file():
            return candidate
    return None


def _newest_existing_xprompt_lsp_binary(
    directories: Sequence[Path],
) -> Path | None:
    candidates = [
        candidate
        for directory in directories
        for candidate in _xprompt_lsp_binary_candidates(directory)
        if candidate.is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=_mtime_ns)


def _xprompt_lsp_binary_candidates(directory: Path) -> tuple[Path, ...]:
    return tuple(directory / name for name in _xprompt_lsp_binary_names())


def _xprompt_lsp_binary_names() -> tuple[str, ...]:
    if os.name == "nt":
        return (f"{XPROMPT_LSP_BINARY}.exe", XPROMPT_LSP_BINARY)
    return (XPROMPT_LSP_BINARY,)


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


def _recover_unquoted_command_path_with_spaces(
    override: str,
    command: tuple[str, ...],
    *,
    which: Callable[[str], str | None],
) -> tuple[str, ...] | None:
    """Recover ``/path/with spaces/bin args`` from an unquoted env override."""
    if _command_head_exists(command[0], which=which):
        return command

    parts = override.split()
    for end in range(len(parts), 0, -1):
        candidate = " ".join(parts[:end])
        if _command_head_exists(candidate, which=which):
            return (candidate, *parts[end:])
    return None


def _command_head_exists(head: str, *, which: Callable[[str], str | None]) -> bool:
    return Path(head).is_file() or which(head) is not None


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
        SASE_SKILL_BUILTIN_DIR_ENV: str(get_sase_package_skills_dir(root)),
        SASE_XPROMPT_DEFAULT_DIR_ENV: str(root / "default_xprompts"),
        SASE_DEFAULT_CONFIG_PATH_ENV: str(root / "default_config.yml"),
    }
    for key, value in defaults.items():
        environ.setdefault(key, value)
    if SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV not in environ:
        environ[SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV] = json.dumps(
            _discover_plugin_xprompt_dirs()
        )
    if SASE_SKILL_PLUGIN_DIRS_JSON_ENV not in environ:
        environ[SASE_SKILL_PLUGIN_DIRS_JSON_ENV] = json.dumps(
            _discover_plugin_resource_dirs("skills")
        )
    if SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV not in environ:
        environ[SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV] = json.dumps(
            _discover_plugin_config_paths()
        )
    _materialize_vcs_project_catalog(environ)
    _materialize_model_catalog(environ)
    _materialize_artifact_ref_catalog(environ)
    _materialize_glossary_catalog(environ)


def _default_vcs_project_catalog_path() -> Path:
    """Return the default on-disk location for the LSP project catalog."""
    return sase_subdir("xprompt_lsp") / "vcs_project_catalog.json"


def _materialize_vcs_project_catalog(environ: MutableMapping[str, str]) -> None:
    """Write the enabled project/PR completion catalog and expose its path.

    The Rust xprompt LSP re-reads this JSON file on every ``+`` completion
    request, so project changes are reflected after the file is rewritten.
    Writing is best-effort: an empty or missing catalog only means the ``+``
    menu shows nothing, and must never prevent the LSP from starting. The path
    is exported regardless so a later rewrite is still picked up.
    """
    existing = environ.get(SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV)
    path = Path(existing) if existing else _default_vcs_project_catalog_path()
    environ[SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV] = str(path)
    try:
        from sase.xprompt.vcs_project_completion import (
            vcs_project_catalog_payload,
        )

        payload = vcs_project_catalog_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never block LSP startup on catalog errors.
        print(
            f"Warning: failed to materialize VCS project catalog: {exc}",
            file=sys.stderr,
        )


def _default_model_catalog_path() -> Path:
    """Return the default on-disk location for the LSP model catalog."""
    return sase_subdir("xprompt_lsp") / "model_catalog.json"


def _materialize_model_catalog(environ: MutableMapping[str, str]) -> None:
    """Write the ``%model`` completion catalog and expose its path.

    The Rust xprompt LSP re-reads this JSON file on every ``%model`` argument
    completion request. Writing is best-effort so LSP startup is never blocked
    by provider/config metadata issues.
    """
    existing = environ.get(SASE_XPROMPT_MODEL_CATALOG_ENV)
    path = Path(existing) if existing else _default_model_catalog_path()
    environ[SASE_XPROMPT_MODEL_CATALOG_ENV] = str(path)
    try:
        from sase.xprompt.model_completion import model_completion_catalog_payload

        payload = model_completion_catalog_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never block LSP startup on catalog errors.
        print(
            f"Warning: failed to materialize model completion catalog: {exc}",
            file=sys.stderr,
        )


def _default_artifact_ref_catalog_path() -> Path:
    """Return the default on-disk location for the artifact-reference catalog."""
    return sase_subdir("xprompt_lsp") / "artifact_ref_catalog.json"


def _materialize_artifact_ref_catalog(
    environ: MutableMapping[str, str],
) -> None:
    """Write the local artifact-reference catalog and expose its path.

    The Rust server re-reads this file for every request. Materialization is
    best-effort, and the path remains exported after failures so a later
    refresh or external rewrite can recover without restarting the editor.
    """

    existing = environ.get(SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV)
    path = Path(existing) if existing else _default_artifact_ref_catalog_path()
    environ[SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV] = str(path)
    try:
        from sase.artifact_refs import artifact_ref_lsp_catalog_payload

        payload = artifact_ref_lsp_catalog_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never block LSP startup on catalog errors.
        print(
            f"Warning: failed to materialize artifact-reference catalog: {exc}",
            file=sys.stderr,
        )


def _default_glossary_catalog_path() -> Path:
    """Return the default on-disk location for the glossary catalog."""
    return sase_subdir("xprompt_lsp") / "glossary_catalog.json"


def _materialize_glossary_catalog(
    environ: MutableMapping[str, str],
) -> None:
    """Write the project glossary catalog and expose its path to the LSP."""

    existing = environ.get(SASE_XPROMPT_GLOSSARY_CATALOG_ENV)
    path = Path(existing) if existing else _default_glossary_catalog_path()
    environ[SASE_XPROMPT_GLOSSARY_CATALOG_ENV] = str(path)
    try:
        from sase.xprompt.glossary_catalog import editor_glossary_lsp_catalog_payload

        payload = editor_glossary_lsp_catalog_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never block LSP startup on catalog errors.
        print(
            f"Warning: failed to materialize glossary catalog: {exc}",
            file=sys.stderr,
        )


def _discover_plugin_xprompt_dirs() -> list[dict[str, str]]:
    """Return concrete plugin xprompt directories for the Rust LSP loader."""
    return _discover_plugin_resource_dirs("xprompts")


def _discover_plugin_resource_dirs(resource_dir: str) -> list[dict[str, str]]:
    """Return concrete plugin xprompt, skill, or ref resource directories."""
    if is_plugin_disabled("XPROMPTS"):
        return []

    entries: list[dict[str, str]] = []
    for module in discover_plugin_resources("sase_xprompts"):
        try:
            ref = importlib.resources.files(module).joinpath(resource_dir)
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
