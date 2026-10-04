"""Path and Python-identifier checks for the macro terminology contract."""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

import pytest

from tests._macro_terminology_common import (
    LEGACY_FIXTURE_MARK,
    MACRO_PATH_ALLOWLIST,
    ROOT,
    SELF_TESTS,
    TUI_SCOPES,
    iter_scope_files,
)

pytestmark = pytest.mark.contract

# The one agent-package line that registers the shim's finder.
_SHIM_MARK = "# TEMP(xprompt->macro shim)"

# Sunset-transport spellings this phase classifies instead of blanket-allowing:
# each (file, identifier) row below names one pre-flip transport constant
# owned by sase-1eq.10, or the narrowed-parser compat `dest` owned by the
# cli-doctor phase. A newly introduced NAME still fails unless it lands
# here with a reason.
_MACRO_TRANSPORT_SINGLETONS = frozenset(
    {
        ("src/sase/agent/multi_prompt_macros.py", "LOCAL_XPROMPTS_ENV"),
        ("src/sase/doctor/checks_deep_macro_lsp.py", "SASE_XPROMPT_LSP_CMD_ENV"),
        ("src/sase/doctor/checks_deep_macro_lsp.py", "XPROMPT_LSP_BINARY"),
        ("src/sase/integrations/macro_lsp.py", "SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV"),
        ("src/sase/integrations/macro_lsp.py", "SASE_XPROMPT_BUILTIN_DIR_ENV"),
        ("src/sase/integrations/macro_lsp.py", "SASE_XPROMPT_DEFAULT_DIR_ENV"),
        ("src/sase/integrations/macro_lsp.py", "SASE_XPROMPT_GLOSSARY_CATALOG_ENV"),
        ("src/sase/integrations/macro_lsp.py", "SASE_XPROMPT_LSP_CMD_ENV"),
        ("src/sase/integrations/macro_lsp.py", "SASE_XPROMPT_MACHINE_CATALOG_ENV"),
        ("src/sase/integrations/macro_lsp.py", "SASE_XPROMPT_MODEL_CATALOG_ENV"),
        ("src/sase/integrations/macro_lsp.py", "SASE_XPROMPT_PACKAGE_DIR_ENV"),
        (
            "src/sase/integrations/macro_lsp.py",
            "SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV",
        ),
        ("src/sase/integrations/macro_lsp.py", "SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV"),
        ("src/sase/integrations/macro_lsp.py", "SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV"),
        ("src/sase/integrations/macro_lsp.py", "XPROMPT_LSP_BINARY"),
        ("src/sase/macro/used_macros.py", "SASE_LAUNCH_SWARM_XPROMPTS"),
        ("src/sase/main/parser_macro.py", "xprompt_subcommand"),
        ("tests/doctor/test_checks_deep.py", "SASE_XPROMPT_LSP_CMD_ENV"),
        ("tests/main/test_lsp_handler.py", "SASE_XPROMPT_LSP_CMD_ENV"),
        (
            "tests/main/test_lsp_handler_environment.py",
            "SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV",
        ),
        ("tests/main/test_lsp_handler_environment.py", "SASE_XPROMPT_BUILTIN_DIR_ENV"),
        ("tests/main/test_lsp_handler_environment.py", "SASE_XPROMPT_DEFAULT_DIR_ENV"),
        (
            "tests/main/test_lsp_handler_environment.py",
            "SASE_XPROMPT_GLOSSARY_CATALOG_ENV",
        ),
        (
            "tests/main/test_lsp_handler_environment.py",
            "SASE_XPROMPT_MODEL_CATALOG_ENV",
        ),
        ("tests/main/test_lsp_handler_environment.py", "SASE_XPROMPT_PACKAGE_DIR_ENV"),
        (
            "tests/main/test_lsp_handler_environment.py",
            "SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV",
        ),
        (
            "tests/main/test_lsp_handler_environment.py",
            "SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV",
        ),
        (
            "tests/main/test_lsp_handler_environment.py",
            "SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV",
        ),
        ("tests/test_axe_chop_agents_identity_scrub.py", "SASE_LAUNCH_SWARM_XPROMPTS"),
        ("tests/test_legacy_macro_names.py", "SASE_LAUNCH_SWARM_XPROMPTS"),
        (
            "tests/test_multi_prompt_launcher_launch_env.py",
            "SASE_LAUNCH_SWARM_XPROMPTS",
        ),
        (
            "tests/test_multi_prompt_launcher_macro_groups.py",
            "SASE_LAUNCH_SWARM_XPROMPTS",
        ),
        ("tests/test_run_agent_runner_refresh.py", "LOCAL_XPROMPTS_ENV"),
        ("tests/test_run_agent_runner_setup.py", "SASE_LAUNCH_SWARM_XPROMPTS"),
    }
)


def _is_legacy_identifier(name: str) -> bool:
    # The codemod skipped every LEGACY_*/legacy_* identifier on purpose and
    # callers were retargeted to the legacy-names constants instead. The
    # substring arm covers fixture helpers such as
    # `_write_legacy_xprompt_agent_dir`.
    return name.startswith("LEGACY_") or "legacy_xprompt" in name.lower()


def _tui_module_basenames() -> frozenset[str]:
    # TUI-local definitions keep their spellings, so a non-TUI reference
    # that names a TUI xprompt module is a follow, not a straggler.
    names: set[str] = set()
    for scope in TUI_SCOPES:
        for path in sorted((ROOT / scope).rglob("*.py")):
            if "xprompt" in path.stem.lower():
                names.add(path.stem)
    return frozenset(names)


_TUI_MODULE_BASENAMES = _tui_module_basenames()

# Intentional survivors as (file, identifier) pairs. Each row is one of: a
# content-layout locator the pinned core still emits, a pre-contract
# wire/durable key read for compatibility, a plugin-directory spelling
# plugins still ship, or a TUI-local definition a non-TUI test follows.
# Never add a whole file here to hide a missed rename.
_MACRO_NAME_ALLOWLIST = {
    # Pinned-core locator fields; the core flip owns the canonical key.
    ("src/sase/core/content_layout_wire.py", "xprompts"),
    ("src/sase/core/content_layout_wire.py", "xprompt_sources"),
    ("src/sase/prompt/cli_export.py", "xprompts"),
    # Plugins still ship an `xprompts/` resource directory.
    ("src/sase/macro/loader_skills.py", "_PLUGIN_XPROMPT_DESTINATION"),
    # Pre-contract wire/durable readers, never writers.
    ("src/sase/core/agent_alias_history_wire.py", "used_xprompts"),
    ("src/sase/core/agent_scan_wire_conversion.py", "used_xprompts"),
    ("tests/test_core_agent_scan_wire_macros.py", "used_xprompts"),
    # The doctor's required legacy id and retired-name table (cli-doctor
    # phase sase-1eq.4.1.4, permanent by parent plan 202610/macro_syntax_cutover.md).
    ("src/sase/doctor/checks_config_retired.py", "RETIRED_XPROMPT_NAMES_CHECK_ID"),
    (
        "src/sase/doctor/checks_config_retired.py",
        "check_config_retired_xprompt_names",
    ),
    (
        "tests/doctor/test_checks_config_retired.py",
        "RETIRED_XPROMPT_NAMES_CHECK_ID",
    ),
    (
        "tests/doctor/test_checks_config_retired.py",
        "check_config_retired_xprompt_names",
    ),
    ("src/sase/doctor/checks_config.py", "check_config_retired_xprompt_names"),
    ("src/sase/doctor/checks_config.py", "_check_config_retired_xprompt_names"),
    # TUI-local helpers followed by project-tag tests.
    ("tests/test_project_tags_expansion.py", "submitted_vcs_xprompt_prefix"),
    ("tests/test_project_tag_surfaces.py", "_tag_styled_xprompt_body"),
    ("tests/test_embedded_workflows_per_step.py", "load_xprompts_used"),
    ("tests/test_legacy_macro_names.py", "load_xprompts_used"),
    # Config-frontmatter follows of TUI-owned spellings kept verbatim for
    # the TUI phase (sase-1eq.5 owns the rename); remove with that phase.
    ("tests/test_config_macro_frontmatter.py", "auto_xprompt_menu"),
    ("tests/test_config_macro_frontmatter.py", "_xprompt_placeholder_args_enabled"),
    # TUI keymap action and field spellings, which stay verbatim.
    ("tests/test_keymaps_defaults_panels.py", "start_last_vcs_xprompt_in_editor"),
    ("tests/test_keymaps_registry_loading_panes.py", "focus_xprompt"),
    ("tests/test_keymaps_registry_loading_panes.py", "clear_xprompt_focus"),
    ("tests/test_keymaps_validation.py", "focus_xprompt"),
    ("tests/test_keymaps_validation.py", "clear_xprompt_focus"),
    ("tests/test_timezone_display_tui.py", "xprompts_group_by"),
}


def _is_allowlisted_path(relative: Path) -> bool:
    if relative in MACRO_PATH_ALLOWLIST:
        return True
    # The shim directory itself carries the retired component; only the
    # package file inside is landing behavior, and it is allowlisted above.
    # The component test below limits this to homes nested in a retired
    # directory, so `src/sase` itself is never exempted.
    return any(
        relative == home.parent and "xprompt" in relative.name.lower()
        for home in MACRO_PATH_ALLOWLIST
    )


def _allowed_name(relative: Path, name: str, line: str) -> bool:
    if relative in SELF_TESTS:
        return True
    if _SHIM_MARK in line:
        return True
    if _is_legacy_identifier(name):
        return True
    if (relative.as_posix(), name) in _MACRO_TRANSPORT_SINGLETONS:
        return True
    if name in _TUI_MODULE_BASENAMES:
        return True
    return (relative.as_posix(), name) in _MACRO_NAME_ALLOWLIST


def _allowed_module(relative: Path, module: str, line: str) -> bool:
    if _SHIM_MARK in line:
        return True
    if module == "sase.legacy_xprompt_names":
        # The canonical legacy home; callers import it on purpose.
        return True
    if module == "sase.legacy_xprompt_syntax":
        # The cutover's temporary syntax home owns every sunset alias and
        # the flag-gated normalization policy (plan 202610/macro_syntax_cutover.md).
        # Remove when the sunset flag and this module are deleted.
        return True
    if module.startswith("sase.ace.tui."):
        # TUI paths keep xprompt components by plan scope.
        return True
    return False


def test_macro_paths_avoid_xprompt_components() -> None:
    findings: list[str] = []
    for path in iter_scope_files():
        relative = path.relative_to(ROOT)
        if _is_allowlisted_path(relative):
            continue
        if LEGACY_FIXTURE_MARK in relative.as_posix():
            continue
        for part in relative.parts:
            if "xprompt" in part.lower():
                findings.append(f"{relative}: path component {part!r}")
                break

    assert findings == []


def test_macro_source_avoids_xprompt_identifiers() -> None:
    findings: list[str] = []
    for path in iter_scope_files(suffix=".py"):
        relative = path.relative_to(ROOT)
        if _is_allowlisted_path(relative):
            continue
        if LEGACY_FIXTURE_MARK in relative.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        if "xprompt" not in text.lower():
            # Conservative prefilter: no NAME token can match without the
            # substring. Path scan above still runs for every file.
            continue
        lines = text.splitlines()
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        except (tokenize.TokenError, SyntaxError, IndentationError):
            findings.append(f"{relative}: unable to tokenize")
            continue
        for token in tokens:
            if token.type != tokenize.NAME or "xprompt" not in token.string.lower():
                continue
            line = lines[token.start[0] - 1] if token.start[0] <= len(lines) else ""
            if not _allowed_name(relative, token.string, line):
                findings.append(
                    f"{relative}:{token.start[0]}: identifier {token.string!r}"
                )

    assert findings == []


def test_macro_imports_avoid_xprompt_modules() -> None:
    findings: list[str] = []
    for path in iter_scope_files(suffix=".py"):
        relative = path.relative_to(ROOT)
        if _is_allowlisted_path(relative):
            continue
        if LEGACY_FIXTURE_MARK in relative.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        if "xprompt" not in text.lower():
            # Conservative prefilter: no import module string can match
            # without the substring. NAME/path detection is unchanged.
            continue
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                targets = [node.module or ""]
            else:
                continue
            lineno = getattr(node, "lineno", 0)
            line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
            for module in targets:
                if "xprompt" in module.lower() and not _allowed_module(
                    relative, module, line
                ):
                    findings.append(f"{relative}:{lineno}: import {module!r}")

    assert findings == []
