"""Guard the xprompt->macro rename outside the TUI.

Non-TUI packages live on macro paths now; the only in-repo xprompt
spellings left outside ``src/sase/ace/tui/`` and ``tests/ace/`` are the
legacy homes, the temporary shim, sase-syntax-owned surface spellings,
core-emitted locator fields, and references to TUI-local definitions.
"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path


import pytest

from tests._macro_terminology_string_pairs_a import (
    _STRING_PAIRS as _MACRO_STRING_PAIRS_A,
)
from tests._macro_terminology_string_pairs_b import (
    _STRING_PAIRS as _MACRO_STRING_PAIRS_B,
)

pytestmark = pytest.mark.contract

_ROOT = Path(__file__).resolve().parents[1]

_TUI_SCOPES = (Path("src/sase/ace/tui"), Path("tests/ace"))

# The plan's allowlist: legacy homes and the temporary shim, each kept on
# purpose (the shim serves external plugins until audit-deploy). The syntax
# home does not exist yet, so it joins only when it lands.
_MACRO_PATH_ALLOWLIST = {
    Path("src/sase/legacy_xprompt_names.py"),
    Path("src/sase/xprompt/__init__.py"),
}
if (_ROOT / "src/sase/legacy_xprompt_syntax.py").exists():
    _MACRO_PATH_ALLOWLIST.add(Path("src/sase/legacy_xprompt_syntax.py"))

# Legacy fixture trees keep their on-disk spellings.
_LEGACY_FIXTURE_MARK = "legacy_xprompt"

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

# The guard names the retired term in its own test functions; that
# meta-use is not a product identifier.
_SELF_TEST = Path("tests/test_macro_terminology.py")


def _in_scope(path: Path) -> bool:
    relative = path.relative_to(_ROOT)
    return not any(
        relative == scope or scope in relative.parents for scope in _TUI_SCOPES
    )


def _iter_scope_files(suffix: str | None = None) -> list[Path]:
    found: list[Path] = []
    for scope in (Path("src"), Path("tests")):
        root = _ROOT / scope
        candidates = sorted(root.rglob(f"*{suffix}" if suffix else "*"))
        for path in candidates:
            if "__pycache__" in path.parts:
                # Generated bytecode mirrors source names; never source.
                continue
            if _in_scope(path):
                found.append(path)
    return found


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
    for scope in _TUI_SCOPES:
        for path in sorted((_ROOT / scope).rglob("*.py")):
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
    # TUI-local widget surfaces followed by macro-parity tests.
    ("tests/macro/test_argument_surface_parity.py", "XPromptSyntaxHighlightMixin"),
    ("tests/macro/test_argument_surface_parity.py", "XPromptAssistEntry"),
    ("tests/macro/test_argument_surface_parity.py", "XPromptInputHint"),
    (
        "tests/macro/test_argument_surface_parity.py",
        "_xprompt_arg_assist_entries_wire",
    ),
    (
        "tests/macro/test_argument_surface_parity.py",
        "_register_xprompt_text_area_theme",
    ),
    ("tests/macro/test_argument_surface_parity.py", "_resolve_xprompt_base_theme"),
    ("tests/macro/test_highlight.py", "xprompt_overlay_spans"),
    ("tests/macro/test_highlight.py", "skip_xprompt"),
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
    if relative in _MACRO_PATH_ALLOWLIST:
        return True
    # The shim directory itself carries the retired component; only the
    # package file inside is landing behavior, and it is allowlisted above.
    # The component test below limits this to homes nested in a retired
    # directory, so `src/sase` itself is never exempted.
    return any(
        relative == home.parent and "xprompt" in relative.name.lower()
        for home in _MACRO_PATH_ALLOWLIST
    )


def _allowed_name(relative: Path, name: str, line: str) -> bool:
    if relative == _SELF_TEST:
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
    for path in _iter_scope_files():
        relative = path.relative_to(_ROOT)
        if _is_allowlisted_path(relative):
            continue
        if _LEGACY_FIXTURE_MARK in relative.as_posix():
            continue
        for part in relative.parts:
            if "xprompt" in part.lower():
                findings.append(f"{relative}: path component {part!r}")
                break

    assert findings == []


def test_macro_source_avoids_xprompt_identifiers() -> None:
    findings: list[str] = []
    for path in _iter_scope_files(suffix=".py"):
        relative = path.relative_to(_ROOT)
        if _is_allowlisted_path(relative):
            continue
        if _LEGACY_FIXTURE_MARK in relative.as_posix():
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
    for path in _iter_scope_files(suffix=".py"):
        relative = path.relative_to(_ROOT)
        if _is_allowlisted_path(relative):
            continue
        if _LEGACY_FIXTURE_MARK in relative.as_posix():
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


# ---------------------------------------------------------------------------
# Strings-guard widened scans (phase sase-1eq.4.1.5).
#
# Beyond identifiers/imports/paths, the guard now inspects string literals,
# comments, and non-Python text resources across all tracked non-TUI
# src/tests/smoke/demos content. Skill sources under
# src/sase/macros/skills/ and smoke/demo scripts carry no exceptions: they
# must stay clean. Every other surviving hit is pinned below as a
# (file, literal-line) pair with a per-file reason; a newly introduced
# non-TUI xprompt string, comment, or resource line fails.
# ---------------------------------------------------------------------------

_LITERAL_CUT = 200


def _literal_key(line: str) -> str:
    return line.strip()[:_LITERAL_CUT]


_STRING_DATA_MODULES = frozenset(
    {
        Path("tests/_macro_terminology_string_pairs_a.py"),
        Path("tests/_macro_terminology_string_pairs_b.py"),
    }
)


def _string_scope_ok(relative: Path) -> bool:
    if relative in _MACRO_PATH_ALLOWLIST or relative == _SELF_TEST:
        return True
    if relative in _STRING_DATA_MODULES:
        # Guard-owned pair tables pin their own rows; the tables are
        # generated, and every row is classified below.
        return True
    if _LEGACY_FIXTURE_MARK in relative.as_posix():
        return True
    return False


_MACRO_SRC_STRING_REASONS: dict[str, str] = {
    "src/sase/_sidecar_ref_constants.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/_sidecar_ref_normalization.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/agent/__init__.py": "temporary import shim (audit-deploy removes it)",
    "src/sase/agent/_macro_swarm_rendering.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/agent/launch_guard.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/agent/launch_proc_runtime.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/agent/macro_swarm.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/agent/multi_prompt.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/agent/multi_prompt_launch_execution.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/agent/multi_prompt_macros.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/agents_sync/inventory_sources.py": "permanent pre-rename artifact reader",
    "src/sase/artifact_ref_scan_models.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/artifact_ref_wire.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/completion/candidates/catalog_snippets.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag; pinned-core adaptation owned by sase-1eq.10",
    "src/sase/completion/candidates/providers.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/completion/kinds.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/completion/run_policy.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/config/_edit_plan.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/config/sase.schema.json": "TUI-owned vocabulary mirrored for parity; owned by sase-1eq.5; flag definition/schema prose; removed with the flag",
    "src/sase/content_layout.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/continuation_capture/segments.py": "stored capture provenance kind; renaming orphans stored rows",
    "src/sase/core/agent_alias_history_wire.py": "permanent pre-rename artifact reader",
    "src/sase/core/agent_archive_facade.py": "permanent pre-rename artifact reader",
    "src/sase/core/agent_scan_wire_conversion.py": "permanent pre-rename artifact reader",
    "src/sase/core/content_layout_wire.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/core/macro_skill_definition_facade.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/core/managed_tmp_reaper.py": "pre-rename residue detection/cleanup",
    "src/sase/default_config.yml": "TUI-owned vocabulary mirrored for parity; owned by sase-1eq.5",
    "src/sase/dev_update/prebuild_cache.py": "pre-flip crate detection is build tooling, not an advertised legacy command",
    "src/sase/doctor/checks_config.py": "doctor retired-names table: required legacy id and retired-name report surface; permanent by parent design",
    "src/sase/doctor/checks_config_retired.py": "doctor retired-names table: required legacy id and retired-name report surface; permanent by parent design",
    "src/sase/doctor/checks_deep_macro_lsp.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/feature_flags/registry.py": "flag definition/schema prose; removed with the flag",
    "src/sase/integrations/macro_lsp.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag; transport owned by sase-1eq.10",
    "src/sase/integrations/mobile_helpers.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/macro/_disabled_regions.py": "dual-spelling reader: canonical writers, legacy storage",
    "src/sase/macro/cli_show_render.py": "TUI-owned vocabulary mirrored for parity; owned by sase-1eq.5",
    "src/sase/macro/config_yaml.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/macro/highlight.py": "TUI-owned vocabulary mirrored for parity; owned by sase-1eq.5",
    "src/sase/macro/highlight_theme.py": "TUI-owned vocabulary mirrored for parity; owned by sase-1eq.5",
    "src/sase/macro/jinja_assist.py": "Jinja scope kind shared with TUI callers; owned by sase-1eq.5",
    "src/sase/macro/loader_sources.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/macro/macro_sources.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/macro/prompt_frontmatter.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/macro/save_index.py": "index kind shared with TUI save surfaces; owned by sase-1eq.5",
    "src/sase/macro/save_state.py": "deliberate in-memory kind; on-disk file and key are canonical",
    "src/sase/macro/used_macros.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/macro/workflow_loader_sources.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/macro/write_targets.py": "commit-type vocabulary shared with the TUI save flow and observed from history; owned by sase-1eq.5",
    "src/sase/main/entry.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/main/macro_handler.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/main/parser_commands.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/main/parser_editor.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/main/parser_macro.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/main/parser_mobile.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/main/parser_registry.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/main/plugin_discovery.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/migration_kit/catalog.py": "pre-rename residue detection/cleanup",
    "src/sase/migration_kit/operations/state_residue.py": "pre-rename residue detection/cleanup",
    "src/sase/monitor/worktree_recovery.py": "dual-spelling reader: canonical writers, legacy storage",
    "src/sase/pager/link_scan.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/patch_stitch_audit.py": "audit matcher over other repos' code; rename with those repos",
    "src/sase/plugins/inventory.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/sdd/_write.py": "dual-spelling reader: canonical writers, legacy storage",
    "src/sase/snippet/catalog.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/snippet/cli_common.py": "stable emitted key: churning it mid-cutover breaks readers",
    "src/sase/snippet/models.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/snippet/mutation.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/stats/_view_builders.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/stats/query.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/vcs_log/_tag_style.py": "color key matches the observed SASE_TYPE vocabulary new saves still emit",
}

_MACRO_TEST_STRING_REASON_DEFAULT = "legacy-input evidence for the both-states compatibility matrix: writers are canonical and the suite is green, so surviving hits are reader inputs, stored fixtures, or deferred-surface pins"

_MACRO_TEST_STRING_REASONS: dict[str, str] = {
    "tests/doctor/test_checks_config_retired.py": "doctor retired-names table: required legacy id and retired-name report surface; permanent by parent design fixtures",
    "tests/fixtures/macro_args_corpus.json": "shared Python/Rust corpus fixture; description renames with the core flip",
    "tests/macro/test_argument_surface_parity.py": "TUI-owned vocabulary mirrored for parity; owned by sase-1eq.5",
    "tests/macro/test_cli_show_body.py": "TUI-owned vocabulary mirrored for parity; owned by sase-1eq.5",
    "tests/macro/test_cli_show_render.py": "TUI-owned vocabulary mirrored for parity; owned by sase-1eq.5",
    "tests/macro/test_highlight.py": "TUI-owned vocabulary mirrored for parity; owned by sase-1eq.5",
    "tests/macro/test_highlight_theme.py": "TUI-owned vocabulary mirrored for parity; owned by sase-1eq.5",
    "tests/macro/test_macro_discovery_policy.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "tests/main/test_lsp_handler.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "tests/main/test_lsp_handler_environment.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "tests/test_axe_chop_agents_identity_scrub.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "tests/test_config_macro_frontmatter.py": "both-states config/frontmatter matrix",
    "tests/test_core_glossary_facade.py": "core glossary terms; vocabulary migrates with the docs/audit phases",
    "tests/test_disabled_regions.py": "dual-spelling reader: canonical writers, legacy storage tests",
    "tests/test_keymaps_defaults_panels.py": "TUI-owned vocabulary mirrored for parity; owned by sase-1eq.5",
    "tests/test_keymaps_registry_loading_panes.py": "TUI-owned vocabulary mirrored for parity; owned by sase-1eq.5",
    "tests/test_keymaps_validation.py": "TUI-owned vocabulary mirrored for parity; owned by sase-1eq.5",
    "tests/test_legacy_macro_names.py": "permanent durable-reader tests",
    "tests/test_legacy_xprompt_syntax.py": "sunset-policy matrix tests (temporary syntax home)",
    "tests/test_macro_swarm_composition.py": "legacy markers plus swarm group naming owned by sase-1eq.10",
    "tests/test_multi_prompt_launcher_launch_env.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "tests/test_multi_prompt_launcher_macro_groups.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "tests/test_run_agent_runner_refresh.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "tests/test_run_agent_runner_setup.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
}

_MACRO_STRING_ALLOWLIST: set[tuple[str, str]] = (
    _MACRO_STRING_PAIRS_A | _MACRO_STRING_PAIRS_B
)

_MACRO_COMMENT_ALLOWLIST: set[tuple[str, str]] = {
    (
        "src/sase/agent/__init__.py",
        "# noqa: E402, F401  # TEMP(xprompt->macro shim): removed in audit-deploy.",
    ),
    (
        "src/sase/agent/multi_prompt.py",
        "# retired ``xprompts`` gated by the sunset flag. Both spellings in one",
    ),
    (
        "src/sase/completion/candidates/catalog_snippets.py",
        "# The pinned core still emits ``xprompt_name``; prefer the canonical key",
    ),
    (
        "src/sase/macro/config_yaml.py",
        "# Migrate a legacy ``xprompts:`` header to canonical ``macros:`` so an",
    ),
    (
        "src/sase/macro/prompt_frontmatter.py",
        "# Retired spellings are known fields, never extras: a legacy ``xprompts:``",
    ),
    (
        "src/sase/main/macro_handler.py",
        '# Narrowed-parser compat: ``create_parser(only="xprompt")`` still',
    ),
    (
        "src/sase/main/parser_macro.py",
        '# Narrowed-parser compat: ``create_parser(only="xprompt")`` still parses',
    ),
    (
        "tests/test_contract_manifest.py",
        "# a conservative case-insensitive `xprompt` substring prefilter before",
    ),
    (
        "tests/test_contract_manifest.py",
        "# terminology audits did: the xprompt->macro rename is a repo-wide invariant no",
    ),
}

_MACRO_RESOURCE_ALLOWLIST: set[tuple[str, str]] = {
    ("src/sase/config/sase.schema.json", '"clear_xprompt_focus": {'),
    (
        "src/sase/config/sase.schema.json",
        '"description": "Clear the active Statistics xprompt focus"',
    ),
    (
        "src/sase/config/sase.schema.json",
        '"description": "Fraction of the Agents tab detail column\'s height that the collapsed header may occupy in total, including its border, two chip rows, and XPROMPT tab row. The rest of the budget is use',
    ),
    (
        "src/sase/config/sase.schema.json",
        '"description": "Most xprompt preview rows the collapsed header shows (at least 1). The collapsed_max_share budget can lower it on short columns. d expands to the full prompt.",',
    ),
    (
        "src/sase/config/sase.schema.json",
        '"description": "Open the Statistics xprompt focus picker"',
    ),
    (
        "src/sase/config/sase.schema.json",
        '"description": "SASE silently accepts retired xprompt spellings as aliases of their macro replacements.",',
    ),
    ("src/sase/config/sase.schema.json", '"focus_xprompt": {'),
    ("src/sase/config/sase.schema.json", '"legacy_xprompt_syntax": {'),
    (
        "src/sase/default_config.yml",
        "# Most xprompt preview rows the collapsed header shows, and fewer when",
    ),
    (
        "src/sase/default_config.yml",
        "# header may occupy in total (border, chip rows, and the XPROMPT tab row",
    ),
    (
        "src/sase/default_config.yml",
        "# included). The rows left over preview the selected agent's xprompt.",
    ),
    ("src/sase/default_config.yml", 'clear_xprompt_focus: "X"'),
    ("src/sase/default_config.yml", 'focus_xprompt: "x"'),
    ("src/sase/default_config.yml", 'start_last_vcs_xprompt_in_editor: "ctrl+g"'),
    (
        "tests/fixtures/macro_args_corpus.json",
        '"description": "Shared Python/Rust xprompt argument-list corpus. Each case.source is the inside of a parenthesized argument list. positional/named are the bound values after [[...]] stripping.",',
    ),
}

# Generated snapshots and historical baselines pin their own content; the
# parser/flag code above is their source of truth.
_MACRO_RESOURCE_SKIPS = frozenset(
    {
        Path("tests/completion/snapshots/cli_spec.json"),
        Path("tests/shard_timings.json"),
        Path("tests/reproducible_flake_baseline.txt"),
    }
)


def _iter_py_string_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if "xprompt" not in text.lower():
        return []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return []
    return [
        _literal_key(line)
        for token in tokens
        if token.type == tokenize.STRING
        for line in token.string.splitlines()
        if "xprompt" in line.lower()
    ]


def _iter_py_comment_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if "xprompt" not in text.lower():
        return []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return []
    return [
        _literal_key(token.string)
        for token in tokens
        if token.type == tokenize.COMMENT and "xprompt" in token.string.lower()
    ]


def _iter_resource_files() -> list[Path]:
    found: list[Path] = []
    for scope in ("src", "tests", "smoke", "demos"):
        root = _ROOT / scope
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix == ".py":
                continue
            if "__pycache__" in path.parts:
                continue
            if _in_scope(path) and path.relative_to(_ROOT) not in _MACRO_RESOURCE_SKIPS:
                found.append(path)
    return found


def test_macro_string_literals_avoid_xprompt_terms() -> None:
    findings: list[str] = []
    for path in _iter_scope_files(suffix=".py"):
        relative = path.relative_to(_ROOT)
        if _string_scope_ok(relative):
            continue
        for literal in _iter_py_string_lines(path):
            if (relative.as_posix(), literal) not in _MACRO_STRING_ALLOWLIST:
                findings.append(f"{relative}: string {literal!r}")
    for path in _iter_resource_files():
        relative = path.relative_to(_ROOT)
        if _string_scope_ok(relative):
            continue
        if relative.as_posix().startswith(("smoke/", "demos/")) or (
            "/skills/" in relative.as_posix()
        ):
            # Strict zones: skill sources and smoke/demo scripts stay clean.
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for line in text.splitlines():
                if "xprompt" in line.lower():
                    findings.append(f"{relative}: resource {line.strip()!r}")
    assert findings == []


def test_macro_comments_avoid_xprompt_terms() -> None:
    findings: list[str] = []
    for path in _iter_scope_files(suffix=".py"):
        relative = path.relative_to(_ROOT)
        if _string_scope_ok(relative):
            continue
        for literal in _iter_py_comment_lines(path):
            if (relative.as_posix(), literal) not in _MACRO_COMMENT_ALLOWLIST:
                findings.append(f"{relative}: comment {literal!r}")
    assert findings == []


def test_macro_resources_avoid_xprompt_terms() -> None:
    findings: list[str] = []
    for path in _iter_resource_files():
        relative = path.relative_to(_ROOT)
        if _string_scope_ok(relative):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line in text.splitlines():
            if "xprompt" not in line.lower():
                continue
            key = _literal_key(line)
            if (relative.as_posix(), key) not in _MACRO_RESOURCE_ALLOWLIST:
                findings.append(f"{relative}: resource {line.strip()!r}")
    assert findings == []


def test_macro_string_allowlist_is_classified() -> None:
    for relative, _ in _MACRO_STRING_ALLOWLIST | _MACRO_COMMENT_ALLOWLIST:
        if relative.startswith("src/"):
            assert relative in _MACRO_SRC_STRING_REASONS, relative
        else:
            assert (
                relative in _MACRO_TEST_STRING_REASONS
                or _MACRO_TEST_STRING_REASON_DEFAULT
            ), relative
    for relative, _ in _MACRO_RESOURCE_ALLOWLIST:
        assert relative in _MACRO_SRC_STRING_REASONS or (
            relative.startswith("tests/")
            and (
                relative in _MACRO_TEST_STRING_REASONS
                or _MACRO_TEST_STRING_REASON_DEFAULT
            )
        ), relative
    for relative in _MACRO_SRC_STRING_REASONS:
        assert (_ROOT / relative).exists(), relative


# ---------------------------------------------------------------------------
# Docs/memory-guard widened scan (phase sase-1eq.6 docs-memory).
#
# docs/, README.md, mkdocs.yml, mkdocs-pdf.yml, and sase/memory/ carry no
# xprompt spelling except the pinned lines below: the mkdocs/hosting redirect
# lines, the "Renamed from xprompts" docs section, the published-post rename
# note, the glossary "formerly" clause and alias (plus the generated roster
# rendering of that alias), the memory discovery line naming the retired
# directory spellings the sunset flag still reads, and the deliberately
# unchanged decision records.
# ---------------------------------------------------------------------------

_MACRO_DOCS_SCOPES = (
    "docs",
    "README.md",
    "mkdocs.yml",
    "mkdocs-pdf.yml",
    "sase/memory",
)

_MACRO_DOCS_DECISIONS = Path("sase/memory/decisions")

_MACRO_DOCS_ALLOWLIST: set[tuple[str, str]] = {
    ("docs/_redirects", "/xprompt/ /macros/ 301"),
    (
        "docs/blog/posts/structured-agentic-software-engineering.md",
        "> Note: SASE xprompts have been renamed to macros since this post was published.",
    ),
    ("docs/macros.md", "## Renamed from xprompts"),
    ("docs/macros.md", "- [Renamed from xprompts](#renamed-from-xprompts)"),
    (
        "docs/macros.md",
        "SASE's reusable prompt definitions were called **xprompts** before this release and are",
    ),
    ("docs/macros.md", "The old page `sase.sh/xprompt/` redirects here."),
    (
        "docs/macros.md",
        "`legacy_xprompt_syntax` sunset flag while callers migrate; help, completion, examples,",
    ),
    (
        "docs/macros.md",
        "and output show only the macro spelling. `%xprompts_enabled` regions stay accepted",
    ),
    (
        "docs/macros.md",
        "| Telegram `/xprompts`; mobile route `/api/v1/xprompts/catalog`                                                                         | `/macros`; `/api/v1/macros/catalog`                           ",
    ),
    (
        "docs/macros.md",
        "| `%proc` origin `xprompt-proc` / field `xprompt_proc`                                                                                  | `prompt-proc` / `prompt_proc`                                 ",
    ),
    (
        "docs/macros.md",
        "| `%xprompts_enabled`                                                                                                                   | `%macros_enabled`                                             ",
    ),
    (
        "docs/macros.md",
        "| `sase xprompt …`, `sase path xprompts-dir`, `xprompts-schema`, `xprompts-collection-schema`, `xprompt-catalog`                        | `sase macro …`, `sase path macros-dir`, `macros-schema`, `macr",
    ),
    (
        "docs/macros.md",
        "| `sase-xprompt-lsp`, crate `sase_xprompt_lsp`, `sase.xpromptLsp.*`                                                                     | `sase-macro-lsp`, `sase_macro_lsp`, `sase.macroLsp.*`         ",
    ),
    (
        "docs/macros.md",
        "| `sase/xprompts/`, `~/sase/xprompts/`, `~/.xprompts/`, `~/xprompts/`                                                                   | `sase/macros/`, `~/sase/macros/`, `~/.macros/`, `~/macros/`   ",
    ),
    (
        "docs/macros.md",
        "| `~/.sase/vcs_xprompt_mru.json`, `~/.sase/xprompt_save_state.json` (key `xprompt`), `~/.sase/xprompt_lsp/`                             | `vcs_macro_mru.json`, `macro_save_state.json` (key `macro`), `",
    ),
    (
        "docs/macros.md",
        "| agent artifacts `xprompts.json`, `xprompts_<step>.json`, `raw_xprompt.md`, `submitted_xprompt.md`                                     | `macros.json`, `macros_<step>.json`, `raw_prompt.md`, `submitt",
    ),
    (
        "docs/macros.md",
        "| config `xprompts:`, `xprompt_aliases:`, `auto_xprompt_menu`, `xprompt_placeholder_args`, `mentors[].xprompt`; frontmatter `xprompts:` | `macros:`, `macro_aliases:`, `auto_macro_menu`, `macro_placeho",
    ),
    (
        "docs/macros.md",
        "| doctor ids `config.model_xprompts`, `config.xprompt_definitions`, `config.xprompt_directives`, `tools.xprompt_lsp`                    | `config.model_macros`, `config.macro_definitions`, `config.mac",
    ),
    (
        "docs/macros.md",
        "| entry-point group `sase_xprompts`; env `SASE_XPROMPT_*`, `SASE_*_XPROMPTS`                                                            | `sase_macros`; `SASE_MACRO_*`, `SASE_*_MACROS`                ",
    ),
    (
        "docs/macros.md",
        "| keymap actions `focus_xprompt`, `clear_xprompt_focus`, `start_last_vcs_xprompt_in_editor`                                             | `focus_macro`, `clear_macro_focus`, `start_last_vcs_macro_in_e",
    ),
    (
        "docs/macros.md",
        "| package `sase.xprompt`, `src/sase/xprompts/`, `src/sase/default_xprompts/`                                                            | `sase.macro`, `src/sase/macros/`, `src/sase/default_macros/`  ",
    ),
    ("mkdocs-pdf.yml", "'xprompt.md': 'macros.md'"),
    ("mkdocs.yml", "'xprompt.md': 'macros.md'"),
    (
        "sase/memory/glossary.md",
        "Calls; Machine Tab; Macro (xprompt); Macro Memory (memory file, sase memory); Macro",
    ),
    ("sase/memory/glossary/macro.md", "- xprompt"),
    (
        "sase/memory/glossary/macro.md",
        "Formerly called an xprompt. Triggered with `#foo` in agent prompts. Defined in a",
    ),
    (
        "sase/memory/macros.md",
        "- **Discovery, first wins:** project `sase/macros/` -> legacy project `.xprompts/`,",
    ),
    (
        "sase/memory/macros.md",
        "`xprompts/` -> home `~/sase/macros/` -> legacy home `~/.xprompts/`, `~/xprompts/` ->",
    ),
    (
        "sase/memory/macros.md",
        "`~/.config/sase/xprompts/<project>/` -> project/user config -> plugins -> package",
    ),
}


_MACRO_DOCS_REASONS: dict[str, str] = {
    "docs/_redirects": "hosting redirect keeps the retired page URL working",
    "docs/blog/posts/structured-agentic-software-engineering.md": "published-post rename note required by docs-memory",
    "docs/macros.md": "the 'Renamed from xprompts' docs section is the docs allowlist",
    "mkdocs-pdf.yml": "mkdocs redirect keeps the retired page URL working",
    "mkdocs.yml": "mkdocs redirect keeps the retired page URL working",
    "sase/memory/glossary.md": "generated roster renders the Macro strand's xprompt alias",
    "sase/memory/glossary/macro.md": "glossary 'formerly' clause and alias keep old glossary:xprompt reads resolving",
    "sase/memory/macros.md": "memory discovery line names the retired directory spellings the sunset flag still reads",
}


def _iter_docs_files() -> list[Path]:
    # Worktree walk (not `git ls-files`): uncommitted renames leave the index
    # ahead of or behind the files on disk, and the guard must judge the tree
    # the docs build and memory init actually read.
    found: list[Path] = []
    for scope in _MACRO_DOCS_SCOPES:
        root = _ROOT / scope
        if root.is_file():
            found.append(root)
            continue
        for path in sorted(root.rglob("*")):
            if "__pycache__" in path.parts or not path.is_file():
                continue
            found.append(path)
    return found


def test_macro_docs_paths_avoid_xprompt_components() -> None:
    findings: list[str] = []
    for path in _iter_docs_files():
        relative = path.relative_to(_ROOT)
        for part in relative.parts:
            if "xprompt" in part.lower():
                findings.append(f"{relative}: path component {part!r}")
                break

    assert findings == []


def test_macro_docs_and_memory_avoid_xprompt_terms() -> None:
    findings: list[str] = []
    for path in _iter_docs_files():
        relative = path.relative_to(_ROOT)
        if relative == _SELF_TEST:
            continue
        if relative == _MACRO_DOCS_DECISIONS or (
            _MACRO_DOCS_DECISIONS in relative.parents
        ):
            # Deliberately unchanged history; only the link target moved.
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            # Binary assets (the infographic PNG regenerates in a follow-up).
            continue
        for line in text.splitlines():
            if "xprompt" not in line.lower():
                continue
            if (relative.as_posix(), _literal_key(line)) not in _MACRO_DOCS_ALLOWLIST:
                findings.append(f"{relative}: {line.strip()[:160]!r}")

    assert findings == []


def test_macro_docs_allowlist_is_classified() -> None:
    for relative, _ in _MACRO_DOCS_ALLOWLIST:
        assert relative in _MACRO_DOCS_REASONS, relative
    for relative in _MACRO_DOCS_REASONS:
        assert (_ROOT / relative).exists(), relative
