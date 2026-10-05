"""Shared public helpers for the private macro terminology test modules."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_FIXTURE_MARK = "legacy_xprompt"
SELF_TESTS = frozenset(
    {
        Path("tests/test_macro_terminology.py"),
        Path("tests/_macro_terminology_common.py"),
        Path("tests/_macro_terminology_identifiers.py"),
        Path("tests/_macro_terminology_strings.py"),
        Path("tests/_macro_terminology_docs.py"),
    }
)

# Legacy homes and the sunset-flag syntax module, each kept on purpose.
MACRO_PATH_ALLOWLIST = {
    Path("src/sase/legacy_xprompt_names.py"),
}
if (ROOT / "src/sase/legacy_xprompt_syntax.py").exists():
    MACRO_PATH_ALLOWLIST.add(Path("src/sase/legacy_xprompt_syntax.py"))

# History, sidecar archives, and the docs/memory scan (owned by
# `_macro_terminology_docs`) stay out of the whole-repo pass. `git ls-files`
# also drops ignored leftovers such as `tests/xprompt/` so other workspaces
# do not fail this contract.
_SKIP_SCAN_PREFIXES = (
    "CHANGELOG.md",
    "sdd/",
    "sase/repos/",
    "sase/memory/",
    "docs/",
    "README.md",
    "mkdocs.yml",
    "mkdocs-pdf.yml",
    "local/",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "OPENCODE.md",
    "QWEN.md",
)


def _should_skip_tracked(relative: Path) -> bool:
    posix = relative.as_posix()
    for prefix in _SKIP_SCAN_PREFIXES:
        if prefix.endswith("/"):
            if posix == prefix[:-1] or posix.startswith(prefix):
                return True
        elif posix == prefix:
            return True
    return False


def iter_scope_files(suffix: str | None = None) -> list[Path]:
    """Return tracked and untracked, non-ignored files via ``git ls-files``.

    The audit-deploy guard covers the whole repo (Justfile, tools/, .github/,
    smoke/, demos/, and the rest), not only ``src/`` and ``tests/``.
    """
    completed = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    found: list[Path] = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode())
        if _should_skip_tracked(relative):
            continue
        if suffix is not None and not relative.name.endswith(suffix):
            continue
        path = ROOT / relative
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        found.append(path)
    found.sort()
    return found


def literal_key(line: str) -> str:
    return line.strip()[:200]
