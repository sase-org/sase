"""Active-surface guard for the Gemini CLI -> Antigravity (`agy`) migration.

Phase 6 of the agy migration removed the consumer Gemini CLI provider from
SASE's active surface. This guard keeps it removed: it fails if the Gemini CLI
*provider* surface (its module, entry point, env var, helpers, or install/auth
docs) reappears in product code, config, or user-facing reference docs.

It deliberately ALLOWS the narrow Antigravity-owned references that the
migration plan keeps:

- ``.gemini/antigravity-cli`` skill/config paths (Antigravity's own home dir),
- exact ``agy models`` slugs that contain "gemini" (e.g.
  ``gemini-3.6-flash-high``),
- the OpenCode-routed ``google/gemini-3-flash-preview`` model alias,
- the ``GEMINI.md`` provider context shim and ``GEMINI_PROJECT_DIR`` env var
  that the Antigravity CLI inherited from the ``.gemini`` namespace,
- the intentionally Gemini-scoped ``sase_hg_commit`` skill (not migrated to agy).

None of those are matched by the forbidden patterns below, so they pass without
an explicit allowlist.
"""

from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Active product + reference surface scanned by the guard. Tests, SDD records,
# protected memory notes, and generated chezmoi output are intentionally out of
# scope (tests exercise both kept and removed behavior; SDD/memory are history).
_SCAN_ROOTS = (
    "src",
    "config",
    "xprompts",
    "docs",
)
_SCAN_FILES = (
    "pyproject.toml",
    "README.md",
)
_SCAN_SUFFIXES = {".py", ".toml", ".yml", ".yaml", ".json", ".md"}

# Forbidden Gemini-CLI-provider surface. These are the identifiers, env vars,
# module paths, CLI names, and install/auth strings of the *removed* provider.
# They are precise on purpose so legitimate Antigravity/model facts are not hit.
_FORBIDDEN = (
    re.compile(r"gemini-cli"),
    re.compile(r"@google/gemini-cli"),
    re.compile(r"SASE_GEMINI_PATH"),
    re.compile(r"SASE_GEMINI_CLI_TMP"),
    re.compile(r"GeminiProvider"),
    re.compile(r"GeminiCommandWrapper"),
    re.compile(r"gemini_wrapper"),
    re.compile(r"gemini_timer"),
    re.compile(r"_subprocess_gemini"),
    re.compile(r"_tool_call_gemini"),
    re.compile(r"stream_and_parse_gemini"),
    re.compile(r"_process_gemini_json_line"),
    re.compile(r"_capture_gemini_diagnostic"),
    re.compile(r"append_gemini_tool_call_event"),
    re.compile(r"normalize_gemini_tool_call_event"),
    re.compile(r"read_gemini_log"),
    re.compile(r"gemini_api_proxy"),
    re.compile(r"_extract_gemini_thoughts"),
    re.compile(r"_format_gemini_function_call"),
    re.compile(r"_parse_gemini_log_timestamp"),
    re.compile(r"llm_provider\.gemini\b"),
)


def _iter_scanned_files() -> list[Path]:
    paths: list[Path] = []
    for name in _SCAN_FILES:
        candidate = _REPO_ROOT / name
        if candidate.is_file():
            paths.append(candidate)
    for root in _SCAN_ROOTS:
        base = _REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in _SCAN_SUFFIXES:
                paths.append(path)
    return paths


def test_gemini_cli_provider_is_not_registered() -> None:
    """The Gemini CLI provider entry point is gone; `agy` replaces it."""
    registered = {ep.name for ep in importlib.metadata.entry_points(group="sase_llm")}
    assert "gemini" not in registered
    assert "agy" in registered


def test_no_gemini_cli_provider_surface_in_active_tree() -> None:
    """No removed Gemini-CLI-provider identifier survives in product/docs."""
    violations: list[str] = []
    for path in _iter_scanned_files():
        rel = path.relative_to(_REPO_ROOT)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in _FORBIDDEN:
                if pattern.search(line):
                    violations.append(
                        f"{rel}:{lineno}: {pattern.pattern} :: {line.strip()}"
                    )

    assert not violations, (
        "Removed Gemini CLI provider surface found in the active tree. These "
        "must use the Antigravity (`agy`) provider instead:\n" + "\n".join(violations)
    )
