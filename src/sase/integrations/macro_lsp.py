"""Launch support for the SASE macro language server."""

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
from sase.legacy_xprompt_names import MACRO_LSP_DIRNAME
from sase.main.plugin_discovery import (
    discover_macro_plugin_modules,
    discover_plugin_resources,
    is_plugin_disabled,
    macro_plugin_definition_dirname,
    macro_plugins_disabled,
)
from sase.macro.loader_skills import get_sase_package_skills_dir

SASE_MACRO_LSP_CMD_ENV = "SASE_MACRO_LSP_CMD"
SASE_XPROMPT_LSP_CMD_ENV = "SASE_XPROMPT_LSP_CMD"
SASE_ACCEPT_LEGACY_XPROMPT_NAMES_ENV = "SASE_ACCEPT_LEGACY_XPROMPT_NAMES"
SASE_XPROMPT_PACKAGE_DIR_ENV = "SASE_XPROMPT_PACKAGE_DIR"
SASE_MACRO_PACKAGE_DIR_ENV = "SASE_MACRO_PACKAGE_DIR"
SASE_XPROMPT_BUILTIN_DIR_ENV = "SASE_XPROMPT_BUILTIN_DIR"
SASE_MACRO_BUILTIN_DIR_ENV = "SASE_MACRO_BUILTIN_DIR"
SASE_SKILL_BUILTIN_DIR_ENV = "SASE_SKILL_BUILTIN_DIR"
SASE_XPROMPT_DEFAULT_DIR_ENV = "SASE_XPROMPT_DEFAULT_DIR"
SASE_MACRO_DEFAULT_DIR_ENV = "SASE_MACRO_DEFAULT_DIR"
SASE_DEFAULT_CONFIG_PATH_ENV = "SASE_DEFAULT_CONFIG_PATH"
SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV = "SASE_XPROMPT_PLUGIN_DIRS_JSON"
SASE_MACRO_PLUGIN_DIRS_JSON_ENV = "SASE_MACRO_PLUGIN_DIRS_JSON"
SASE_SKILL_PLUGIN_DIRS_JSON_ENV = "SASE_SKILL_PLUGIN_DIRS_JSON"
SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV = "SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON"
SASE_MACRO_PLUGIN_CONFIG_PATHS_JSON_ENV = "SASE_MACRO_PLUGIN_CONFIG_PATHS_JSON"
SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV = "SASE_XPROMPT_VCS_PROJECT_CATALOG"
SASE_MACRO_VCS_PROJECT_CATALOG_ENV = "SASE_MACRO_VCS_PROJECT_CATALOG"
SASE_XPROMPT_MODEL_CATALOG_ENV = "SASE_XPROMPT_MODEL_CATALOG"
SASE_MACRO_MODEL_CATALOG_ENV = "SASE_MACRO_MODEL_CATALOG"
SASE_XPROMPT_MACHINE_CATALOG_ENV = "SASE_XPROMPT_MACHINE_CATALOG"
SASE_MACRO_MACHINE_CATALOG_ENV = "SASE_MACRO_MACHINE_CATALOG"
SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV = "SASE_XPROMPT_ARTIFACT_REF_CATALOG"
SASE_MACRO_ARTIFACT_REF_CATALOG_ENV = "SASE_MACRO_ARTIFACT_REF_CATALOG"
SASE_XPROMPT_GLOSSARY_CATALOG_ENV = "SASE_XPROMPT_GLOSSARY_CATALOG"
SASE_MACRO_GLOSSARY_CATALOG_ENV = "SASE_MACRO_GLOSSARY_CATALOG"
SASE_MACRO_PLUGIN_INPUT_TYPES_JSON_ENV = "SASE_MACRO_PLUGIN_INPUT_TYPES_JSON"
SASE_TYPED_LAUNCH_UNITS_ENV = "SASE_TYPED_LAUNCH_UNITS"
SASE_QUEUE_CAPACITY_BUDGET_ENV = "SASE_QUEUE_CAPACITY_BUDGET"
SASE_AGENT_HOLDS_ENV = "SASE_AGENT_HOLDS"
XPROMPT_LSP_BINARY = "sase-xprompt-lsp"
MACRO_LSP_BINARY = "sase-macro-lsp"


class MacroLspLaunchError(RuntimeError):
    """User-facing macro LSP startup error."""


_MacroLspLaunchError = MacroLspLaunchError


def handle_macro_lsp_command(args: argparse.Namespace) -> NoReturn:
    """Exec the Rust macro LSP server for clean stdio and signal handling."""
    try:
        argv = _build_macro_lsp_argv(args)
        _prepare_macro_lsp_environment(os.environ)
        os.execvp(argv[0], argv)
    except MacroLspLaunchError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"Error: failed to launch macro LSP: {exc}", file=sys.stderr)
        sys.exit(1)

    raise AssertionError("os.execvp unexpectedly returned")


def _build_macro_lsp_argv(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    repo_root: Path | None = None,
) -> list[str]:
    """Resolve the LSP command and append wrapper/server arguments."""
    command = _resolve_macro_lsp_command(
        environ=os.environ if environ is None else environ,
        which=which,
        repo_root=repo_root,
    )
    server_args = _server_args_from_namespace(args)
    return [*command, *server_args]


def resolve_macro_lsp_command(
    *,
    environ: Mapping[str, str],
    which: Callable[[str], str | None] = shutil.which,
    repo_root: Path | None = None,
) -> tuple[str, ...]:
    """Resolve the macro LSP server command without launching it."""
    return _resolve_macro_lsp_command(
        environ=environ,
        which=which,
        repo_root=repo_root,
    )


def _macro_lsp_accept_legacy(environ: Mapping[str, str]) -> bool:
    """Return whether retired LSP spellings are accepted for this launch."""
    from sase.legacy_xprompt_syntax import legacy_xprompt_syntax_enabled

    return legacy_xprompt_syntax_enabled()


def _resolve_macro_lsp_command(
    *,
    environ: Mapping[str, str],
    which: Callable[[str], str | None],
    repo_root: Path | None,
) -> tuple[str, ...]:
    accept_legacy = _macro_lsp_accept_legacy(environ)
    override = environ.get(SASE_MACRO_LSP_CMD_ENV, "").strip()
    legacy_override = environ.get(SASE_XPROMPT_LSP_CMD_ENV, "").strip()
    if override:
        return _parse_lsp_override(SASE_MACRO_LSP_CMD_ENV, override, which=which)
    if legacy_override:
        if not accept_legacy:
            raise MacroLspLaunchError(
                f"{SASE_XPROMPT_LSP_CMD_ENV} is retired; use {SASE_MACRO_LSP_CMD_ENV}"
            )
        return _parse_lsp_override(
            SASE_XPROMPT_LSP_CMD_ENV, legacy_override, which=which
        )

    venv_binary = _first_existing_macro_lsp_binary(
        Path(sys.executable).parent, accept_legacy=accept_legacy
    )
    if venv_binary is not None:
        return (str(venv_binary),)

    path = which(MACRO_LSP_BINARY)
    if path is None and accept_legacy:
        path = which(XPROMPT_LSP_BINARY)
    if path:
        return (path,)

    root = repo_root or Path(__file__).resolve().parents[3]
    sibling_core = root.parent / "sase-core"
    target_binary = _newest_existing_macro_lsp_binary(
        (
            sibling_core / "target" / "debug",
            sibling_core / "target" / "release",
        ),
        accept_legacy=accept_legacy,
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
            _lsp_cargo_package(sibling_core),
            "--",
        )

    detail = (
        "install `sase-macro-lsp` into the current venv, install it on PATH, "
        f"or set {SASE_MACRO_LSP_CMD_ENV}"
    )
    if accept_legacy:
        detail = (
            "install `sase-macro-lsp` (or legacy `sase-xprompt-lsp`) into the "
            f"current venv, install it on PATH, or set {SASE_MACRO_LSP_CMD_ENV}"
        )
    raise MacroLspLaunchError(f"macro LSP binary not found; {detail}")


def _parse_lsp_override(
    env_name: str,
    override: str,
    *,
    which: Callable[[str], str | None],
) -> tuple[str, ...]:
    """Split one explicit LSP command override, recovering spaced paths."""
    try:
        command = tuple(shlex.split(override))
    except ValueError as exc:
        raise MacroLspLaunchError(
            f"{env_name} is not a valid shell-style command: {exc}"
        ) from exc
    if command:
        recovered = _recover_unquoted_command_path_with_spaces(
            override,
            command,
            which=which,
        )
        return recovered or command
    raise MacroLspLaunchError(f"{env_name} is empty")


def _lsp_cargo_package(sibling_core: Path) -> str:
    """Return the LSP crate name the linked core checkout provides."""
    if (sibling_core / "crates" / "sase_macro_lsp" / "Cargo.toml").is_file():
        return "sase_macro_lsp"
    return "sase_xprompt_lsp"


def _first_existing_macro_lsp_binary(
    directory: Path, *, accept_legacy: bool = True
) -> Path | None:
    for candidate in _macro_lsp_binary_candidates(
        directory, accept_legacy=accept_legacy
    ):
        if candidate.is_file():
            return candidate
    return None


def _newest_existing_macro_lsp_binary(
    directories: Sequence[Path],
    *,
    accept_legacy: bool = True,
) -> Path | None:
    """Return the newest built binary, preferring usable canonical binaries.

    A usable canonical ``sase-macro-lsp`` binary always wins over a newer
    legacy ``sase-xprompt-lsp`` binary; legacy candidates are considered
    only while the sunset flag allows them.
    """
    canonical = [
        candidate
        for directory in directories
        for candidate in _macro_lsp_binary_candidates(directory, accept_legacy=False)
        if candidate.is_file()
    ]
    if canonical:
        return max(canonical, key=_mtime_ns)
    if not accept_legacy:
        return None
    legacy = [
        candidate
        for directory in directories
        for candidate in _macro_lsp_binary_candidates(directory, accept_legacy=True)
        if candidate.name not in _canonical_binary_names() and candidate.is_file()
    ]
    if not legacy:
        return None
    return max(legacy, key=_mtime_ns)


def _canonical_binary_names() -> tuple[str, ...]:
    if os.name == "nt":
        return (f"{MACRO_LSP_BINARY}.exe", MACRO_LSP_BINARY)
    return (MACRO_LSP_BINARY,)


def _macro_lsp_binary_candidates(
    directory: Path, *, accept_legacy: bool = True
) -> tuple[Path, ...]:
    return tuple(
        directory / name
        for name in _macro_lsp_binary_names(accept_legacy=accept_legacy)
    )


def _macro_lsp_binary_names(*, accept_legacy: bool = True) -> tuple[str, ...]:
    if os.name == "nt":
        names = [f"{MACRO_LSP_BINARY}.exe", MACRO_LSP_BINARY]
        if accept_legacy:
            names += [f"{XPROMPT_LSP_BINARY}.exe", XPROMPT_LSP_BINARY]
        return tuple(names)
    if accept_legacy:
        return (MACRO_LSP_BINARY, XPROMPT_LSP_BINARY)
    return (MACRO_LSP_BINARY,)


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


def _set_catalog_env(
    environ: MutableMapping[str, str],
    macro_key: str,
    default: str,
) -> None:
    """Export one catalog location under the canonical macro name."""
    environ.setdefault(macro_key, default)


def _prepare_macro_lsp_environment(
    environ: MutableMapping[str, str], package_dir: Path | None = None
) -> None:
    """Expose package macro locations to the Rust LSP catalog loader.

    The ``sase lsp`` wrapper execs the server without owning the client's
    initialize message, so the sunset policy travels on the server's
    existing ``SASE_ACCEPT_LEGACY_XPROMPT_NAMES`` transport alongside the
    initialization option.
    """
    from sase.legacy_xprompt_syntax import legacy_xprompt_syntax_enabled

    if SASE_ACCEPT_LEGACY_XPROMPT_NAMES_ENV not in environ:
        environ[SASE_ACCEPT_LEGACY_XPROMPT_NAMES_ENV] = (
            "1" if legacy_xprompt_syntax_enabled() else "0"
        )
    root = package_dir or Path(__file__).resolve().parents[1]
    defaults = {
        SASE_SKILL_BUILTIN_DIR_ENV: str(get_sase_package_skills_dir(root)),
        SASE_DEFAULT_CONFIG_PATH_ENV: str(root / "default_config.yml"),
    }
    for key, value in defaults.items():
        environ.setdefault(key, value)
    _set_catalog_env(
        environ,
        SASE_MACRO_PACKAGE_DIR_ENV,
        str(root),
    )
    _set_catalog_env(
        environ,
        SASE_MACRO_BUILTIN_DIR_ENV,
        str(root / "macros"),
    )
    _set_catalog_env(
        environ,
        SASE_MACRO_DEFAULT_DIR_ENV,
        str(root / "default_macros"),
    )
    if SASE_MACRO_PLUGIN_DIRS_JSON_ENV not in environ:
        environ[SASE_MACRO_PLUGIN_DIRS_JSON_ENV] = json.dumps(
            _discover_plugin_macro_dirs()
        )
    if SASE_SKILL_PLUGIN_DIRS_JSON_ENV not in environ:
        environ[SASE_SKILL_PLUGIN_DIRS_JSON_ENV] = json.dumps(
            _discover_plugin_resource_dirs("skills")
        )
    if SASE_MACRO_PLUGIN_CONFIG_PATHS_JSON_ENV not in environ:
        environ[SASE_MACRO_PLUGIN_CONFIG_PATHS_JSON_ENV] = json.dumps(
            _discover_plugin_config_paths()
        )
    if SASE_MACRO_PLUGIN_INPUT_TYPES_JSON_ENV not in environ:
        environ[SASE_MACRO_PLUGIN_INPUT_TYPES_JSON_ENV] = json.dumps(
            _discover_plugin_input_type_files()
        )
    _materialize_vcs_project_catalog(environ)
    _materialize_model_catalog(environ)
    _materialize_machine_catalog(environ)
    _materialize_artifact_ref_catalog(environ)
    _materialize_glossary_catalog(environ)
    _apply_typed_launch_units_flag(environ)
    _apply_queue_capacity_budget_flag(environ)
    _apply_agent_holds_flag(environ)


def _default_vcs_project_catalog_path() -> Path:
    """Return the default on-disk location for the LSP project catalog."""
    return sase_subdir(MACRO_LSP_DIRNAME) / "vcs_project_catalog.json"


def _materialize_vcs_project_catalog(environ: MutableMapping[str, str]) -> None:
    """Write the enabled project/PR completion catalog and expose its path.

    The Rust macro LSP re-reads this JSON file on every ``+`` completion
    request, so project changes are reflected after the file is rewritten.
    Writing is best-effort: an empty or missing catalog only means the ``+``
    menu shows nothing, and must never prevent the LSP from starting. The path
    is exported regardless so a later rewrite is still picked up.
    """
    existing = environ.get(SASE_MACRO_VCS_PROJECT_CATALOG_ENV)
    path = Path(existing) if existing else _default_vcs_project_catalog_path()
    environ[SASE_MACRO_VCS_PROJECT_CATALOG_ENV] = str(path)
    try:
        from sase.macro.vcs_project_completion import (
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
    return sase_subdir(MACRO_LSP_DIRNAME) / "model_catalog.json"


def _default_machine_catalog_path() -> Path:
    """Return the default on-disk location for the LSP machine catalog."""
    return sase_subdir(MACRO_LSP_DIRNAME) / "machine_catalog.json"


def _materialize_model_catalog(environ: MutableMapping[str, str]) -> None:
    """Write the ``%model`` completion catalog and expose its path.

    The Rust macro LSP re-reads this JSON file on every ``%model`` argument
    completion request. Writing is best-effort so LSP startup is never blocked
    by provider/config metadata issues.
    """
    existing = environ.get(SASE_MACRO_MODEL_CATALOG_ENV)
    path = Path(existing) if existing else _default_model_catalog_path()
    environ[SASE_MACRO_MODEL_CATALOG_ENV] = str(path)
    try:
        from sase.macro.model_completion import model_completion_catalog_payload

        payload = model_completion_catalog_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never block LSP startup on catalog errors.
        print(
            f"Warning: failed to materialize model completion catalog: {exc}",
            file=sys.stderr,
        )


def _materialize_machine_catalog(environ: MutableMapping[str, str]) -> None:
    """Write the `%dispatch` machine catalog and expose its path."""
    existing = environ.get(SASE_MACRO_MACHINE_CATALOG_ENV)
    path = Path(existing) if existing else _default_machine_catalog_path()
    environ[SASE_MACRO_MACHINE_CATALOG_ENV] = str(path)
    try:
        from sase.dispatch.machine_catalog import machine_completion_catalog_payload

        payload = machine_completion_catalog_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never block LSP startup on catalog errors.
        print(
            f"Warning: failed to materialize machine completion catalog: {exc}",
            file=sys.stderr,
        )


def _default_artifact_ref_catalog_path() -> Path:
    """Return the default on-disk location for the artifact-reference catalog."""
    return sase_subdir(MACRO_LSP_DIRNAME) / "artifact_ref_catalog.json"


def _materialize_artifact_ref_catalog(
    environ: MutableMapping[str, str],
) -> None:
    """Write the local artifact-reference catalog and expose its path.

    The Rust server re-reads this file for every request. Materialization is
    best-effort, and the path remains exported after failures so a later
    refresh or external rewrite can recover without restarting the editor.
    """

    existing = environ.get(SASE_MACRO_ARTIFACT_REF_CATALOG_ENV)
    path = Path(existing) if existing else _default_artifact_ref_catalog_path()
    environ[SASE_MACRO_ARTIFACT_REF_CATALOG_ENV] = str(path)
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
    return sase_subdir(MACRO_LSP_DIRNAME) / "glossary_catalog.json"


def _materialize_glossary_catalog(
    environ: MutableMapping[str, str],
) -> None:
    """Write the project glossary catalog and expose its path to the LSP."""

    existing = environ.get(SASE_MACRO_GLOSSARY_CATALOG_ENV)
    path = Path(existing) if existing else _default_glossary_catalog_path()
    environ[SASE_MACRO_GLOSSARY_CATALOG_ENV] = str(path)
    try:
        from sase.macro.glossary_catalog import editor_glossary_lsp_catalog_payload

        payload = editor_glossary_lsp_catalog_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never block LSP startup on catalog errors.
        print(
            f"Warning: failed to materialize glossary catalog: {exc}",
            file=sys.stderr,
        )


def _apply_typed_launch_units_flag(environ: MutableMapping[str, str]) -> None:
    """Pin the LSP to process-local directive feature-flag decisions."""
    from sase.macro.code_value import typed_launch_units_enabled

    environ[SASE_TYPED_LAUNCH_UNITS_ENV] = "1" if typed_launch_units_enabled() else "0"


def _apply_queue_capacity_budget_flag(environ: MutableMapping[str, str]) -> None:
    """Pin the LSP to the process-local queue_capacity_budget sunset flag."""
    from sase.macro.queue_directive import launch_feature_flag_keys

    enabled = "queue_capacity_budget" in launch_feature_flag_keys()
    environ[SASE_QUEUE_CAPACITY_BUDGET_ENV] = "1" if enabled else "0"


def _apply_agent_holds_flag(environ: MutableMapping[str, str]) -> None:
    """Pin the LSP to the retired-on agent_holds capability."""
    environ[SASE_AGENT_HOLDS_ENV] = "1"


def _discover_plugin_macro_dirs() -> list[dict[str, str]]:
    """Return concrete plugin macro directories for the Rust LSP loader.

    Probes each plugin's ``macros/`` directory first and the retired
    ``xprompts/`` directory only while the sunset flag allows it.
    """
    if macro_plugins_disabled():
        return []

    entries: list[dict[str, str]] = []
    for module in discover_macro_plugin_modules():
        resource_dir = macro_plugin_definition_dirname(module)
        if resource_dir is None:
            continue
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


def _discover_plugin_resource_dirs(resource_dir: str) -> list[dict[str, str]]:
    """Return concrete plugin macro, skill, or ref resource directories."""
    if macro_plugins_disabled():
        return []

    entries: list[dict[str, str]] = []
    for module in discover_macro_plugin_modules():
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


def _discover_plugin_input_type_files() -> list[dict[str, str]]:
    """Return concrete plugin ``input_types.yml`` manifests for the Rust LSP.

    Discovery records are exported directly; choices are never materialized
    into another on-disk JSON catalog. Explicit caller environment values win;
    this canonical variable has no legacy alias.
    """
    from sase.main.plugin_discovery import (
        discover_macro_plugin_input_type_files,
    )

    try:
        return discover_macro_plugin_input_type_files()
    except Exception:
        return []


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
