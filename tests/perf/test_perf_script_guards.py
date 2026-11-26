"""Static guard for Justfile-invoked perf scripts.

Perf scripts run directly by python from the Justfile (e.g.
``python tests/perf/<name>.py``) only get ``tests/perf/`` on ``sys.path``
by default. If a script has top-level ``tests.`` imports, it must bootstrap
the repository root into ``sys.path`` before those imports.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _justfile_perf_scripts(repo_root: Path) -> list[Path]:
    """Return every tests/perf/*.py script invoked by python in Justfile."""
    justfile = repo_root / "Justfile"
    if not justfile.is_file():
        return []
    content = justfile.read_text(encoding="utf-8")
    matches = re.findall(
        r"\{\{\s*venv_bin\s*\}\}/python\s+(tests/perf/\S+\.py)", content
    )
    return sorted({repo_root / match for match in matches})


def _has_tests_import(node: ast.AST) -> bool:
    """Return True if statement imports from `tests` or `tests.*`."""
    if isinstance(node, ast.ImportFrom):
        return bool(
            node.module and (node.module == "tests" or node.module.startswith("tests."))
        )
    if isinstance(node, ast.Import):
        return any(
            alias.name == "tests" or alias.name.startswith("tests.")
            for alias in node.names
        )
    return False


def _is_sys_path_insert(node: ast.AST) -> bool:
    """Return True if statement calls `sys.path.insert`."""
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "insert"
            and isinstance(child.func.value, ast.Attribute)
            and child.func.value.attr == "path"
            and isinstance(child.func.value.value, ast.Name)
            and child.func.value.value.id == "sys"
        ):
            return True
    return False


def test_justfile_perf_scripts_bootstrap_sys_path() -> None:
    """Assert all Justfile-invoked perf scripts with tests.* imports bootstrap sys.path."""
    scripts = _justfile_perf_scripts(_REPO_ROOT)
    assert scripts, "Expected at least one perf script in Justfile"

    failing: list[str] = []
    for script in scripts:
        tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
        first_tests_idx: int | None = None
        first_sys_path_idx: int | None = None

        for idx, stmt in enumerate(tree.body):
            if first_tests_idx is None and _has_tests_import(stmt):
                first_tests_idx = idx
            if first_sys_path_idx is None and _is_sys_path_insert(stmt):
                first_sys_path_idx = idx

        if first_tests_idx is not None:
            if first_sys_path_idx is None or first_sys_path_idx > first_tests_idx:
                failing.append(
                    f"{script.relative_to(_REPO_ROOT)}: tests.* import at statement {first_tests_idx} "
                    f"before sys.path.insert ({first_sys_path_idx})"
                )

    assert not failing, (
        "Perf scripts missing sys.path bootstrap before tests.* imports:\n"
        + "\n".join(failing)
    )
