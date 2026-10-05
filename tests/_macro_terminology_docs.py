"""Documentation and memory checks for the macro terminology contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._macro_terminology_common import ROOT, SELF_TESTS, literal_key

pytestmark = pytest.mark.contract

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
    (
        "docs/editor.md",
        "| Diagnostics           | Reports macro/directive issues, macro call arguments that are unknown (`unknown_macro_arg`), repeated (`duplicate_macro_arg`), or the wrong type for the declared input (`inva",
    ),
}


_MACRO_DOCS_REASONS: dict[str, str] = {
    "docs/_redirects": "hosting redirect keeps the retired page URL working",
    "docs/blog/posts/structured-agentic-software-engineering.md": "published-post rename note required by docs-memory",
    "docs/editor.md": "diagnostics table names the plan-mandated invalid_xprompt_arg_choice code",
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
        root = ROOT / scope
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
        relative = path.relative_to(ROOT)
        for part in relative.parts:
            if "xprompt" in part.lower():
                findings.append(f"{relative}: path component {part!r}")
                break

    assert findings == []


def test_macro_docs_and_memory_avoid_xprompt_terms() -> None:
    findings: list[str] = []
    for path in _iter_docs_files():
        relative = path.relative_to(ROOT)
        if relative in SELF_TESTS:
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
            if (relative.as_posix(), literal_key(line)) not in _MACRO_DOCS_ALLOWLIST:
                findings.append(f"{relative}: {line.strip()[:160]!r}")

    assert findings == []


def test_macro_docs_allowlist_is_classified() -> None:
    for relative, _ in _MACRO_DOCS_ALLOWLIST:
        assert relative in _MACRO_DOCS_REASONS, relative
    for relative in _MACRO_DOCS_REASONS:
        assert (ROOT / relative).exists(), relative
