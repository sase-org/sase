"""String, comment, and resource checks for the macro terminology contract."""

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
    in_scope,
    iter_scope_files,
    literal_key,
)
from tests._macro_terminology_string_pairs_a import STRING_PAIRS as STRING_PAIRS_A
from tests._macro_terminology_string_pairs_b import STRING_PAIRS as STRING_PAIRS_B

pytestmark = pytest.mark.contract

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

_STRING_DATA_MODULES = frozenset(
    {
        Path("tests/_macro_terminology_string_pairs_a.py"),
        Path("tests/_macro_terminology_string_pairs_a_early.py"),
        Path("tests/_macro_terminology_string_pairs_a_late.py"),
        Path("tests/_macro_terminology_string_pairs_b.py"),
        Path("tests/_macro_terminology_string_pairs_b_early.py"),
        Path("tests/_macro_terminology_string_pairs_b_late.py"),
    }
)


def _string_scope_ok(relative: Path) -> bool:
    if relative in MACRO_PATH_ALLOWLIST or relative in SELF_TESTS:
        return True
    if relative in _STRING_DATA_MODULES:
        # Guard-owned pair tables pin their own rows; the tables are
        # generated, and every row is classified below.
        return True
    if LEGACY_FIXTURE_MARK in relative.as_posix():
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
    "src/sase/config/sase.schema.json": "flag definition/schema prose; removed with the flag",
    "src/sase/content_layout.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/continuation_capture/segments.py": "stored capture provenance kind; renaming orphans stored rows",
    "src/sase/core/agent_alias_history_wire.py": "permanent pre-rename artifact reader",
    "src/sase/core/agent_archive_facade.py": "permanent pre-rename artifact reader",
    "src/sase/core/agent_scan_wire_conversion.py": "permanent pre-rename artifact reader",
    "src/sase/core/content_layout_wire.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/core/macro_skill_definition_facade.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/core/managed_tmp_reaper.py": "pre-rename residue detection/cleanup",
    "src/sase/dev_update/prebuild_cache.py": "pre-flip crate detection is build tooling, not an advertised legacy command",
    "src/sase/doctor/checks_config.py": "doctor retired-names table: required legacy id and retired-name report surface; permanent by parent design",
    "src/sase/doctor/checks_config_retired.py": "doctor retired-names table: required legacy id and retired-name report surface; permanent by parent design",
    "src/sase/doctor/checks_deep_macro_lsp.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/feature_flags/registry.py": "flag definition/schema prose; removed with the flag",
    "src/sase/integrations/macro_lsp.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag; transport owned by sase-1eq.10",
    "src/sase/integrations/mobile_helpers.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/macro/_disabled_regions.py": "dual-spelling reader: canonical writers, legacy storage",
    "src/sase/macro/config_yaml.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/macro/highlight.py": "dual-spelling reader: canonical writers, legacy source value",
    "src/sase/macro/jinja_assist.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/macro/loader_sources.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/macro/macro_sources.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/macro/prompt_frontmatter.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "src/sase/macro/save_state.py": "deliberate in-memory kind; on-disk file and key are canonical",
    "src/sase/macro/used_macros.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "src/sase/macro/workflow_loader_sources.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
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
    "src/sase/vcs_log/_tag_style.py": "color key matches the observed SASE_TYPE vocabulary new saves still emit",
}

_MACRO_TEST_STRING_REASON_DEFAULT = "legacy-input evidence for the both-states compatibility matrix: writers are canonical and the suite is green, so surviving hits are reader inputs, stored fixtures, or deferred-surface pins"

_MACRO_TEST_STRING_REASONS: dict[str, str] = {
    "tests/doctor/test_checks_config_retired.py": "doctor retired-names table: required legacy id and retired-name report surface; permanent by parent design fixtures",
    "tests/fixtures/macro_args_corpus.json": "shared Python/Rust corpus fixture; description renames with the core flip",
    "tests/macro/test_argument_surface_parity.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "tests/macro/test_highlight.py": "dual-spelling reader: canonical writers, legacy source value",
    "tests/macro/test_macro_discovery_policy.py": "sunset-policy implementation: flag-gated aliases, gated legacy directories, or retired-spelling readers; removed with the flag",
    "tests/main/test_lsp_handler.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "tests/main/test_lsp_handler_environment.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "tests/test_axe_chop_agents_identity_scrub.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "tests/test_config_macro_frontmatter.py": "both-states config/frontmatter matrix",
    "tests/test_core_glossary_facade.py": "core glossary terms; vocabulary migrates with the docs/audit phases",
    "tests/test_disabled_regions.py": "dual-spelling reader: canonical writers, legacy storage tests",
    "tests/test_legacy_macro_names.py": "permanent durable-reader tests",
    "tests/test_legacy_xprompt_syntax.py": "sunset-policy matrix tests (temporary syntax home)",
    "tests/test_macro_swarm_composition.py": "legacy markers plus swarm group naming owned by sase-1eq.10",
    "tests/test_multi_prompt_launcher_launch_env.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "tests/test_multi_prompt_launcher_macro_groups.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "tests/test_run_agent_runner_refresh.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
    "tests/test_run_agent_runner_setup.py": "pre-flip wire/transport vocabulary; owned by sase-1eq.10",
}

_MACRO_STRING_ALLOWLIST: set[tuple[str, str]] = STRING_PAIRS_A | STRING_PAIRS_B

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
    (
        "src/sase/config/sase.schema.json",
        '"description": "SASE silently accepts retired xprompt spellings as aliases of their macro replacements.",',
    ),
    ("src/sase/config/sase.schema.json", '"legacy_xprompt_syntax": {'),
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
        literal_key(line)
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
        literal_key(token.string)
        for token in tokens
        if token.type == tokenize.COMMENT and "xprompt" in token.string.lower()
    ]


def _iter_resource_files() -> list[Path]:
    found: list[Path] = []
    for scope in ("src", "tests", "smoke", "demos"):
        root = ROOT / scope
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix == ".py":
                continue
            if "__pycache__" in path.parts:
                continue
            if in_scope(path) and path.relative_to(ROOT) not in _MACRO_RESOURCE_SKIPS:
                found.append(path)
    return found


def test_macro_string_literals_avoid_xprompt_terms() -> None:
    findings: list[str] = []
    for path in iter_scope_files(suffix=".py"):
        relative = path.relative_to(ROOT)
        if _string_scope_ok(relative):
            continue
        for literal in _iter_py_string_lines(path):
            if (relative.as_posix(), literal) not in _MACRO_STRING_ALLOWLIST:
                findings.append(f"{relative}: string {literal!r}")
    for path in _iter_resource_files():
        relative = path.relative_to(ROOT)
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
    for path in iter_scope_files(suffix=".py"):
        relative = path.relative_to(ROOT)
        if _string_scope_ok(relative):
            continue
        for literal in _iter_py_comment_lines(path):
            if (relative.as_posix(), literal) not in _MACRO_COMMENT_ALLOWLIST:
                findings.append(f"{relative}: comment {literal!r}")
    assert findings == []


def test_macro_resources_avoid_xprompt_terms() -> None:
    findings: list[str] = []
    for path in _iter_resource_files():
        relative = path.relative_to(ROOT)
        if _string_scope_ok(relative):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line in text.splitlines():
            if "xprompt" not in line.lower():
                continue
            key = literal_key(line)
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
        assert (ROOT / relative).exists(), relative
