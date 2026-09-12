"""Guard the module-scope import boundary between ``sase.agent`` and monitor.

``sase.monitor`` imports ``sase.agent`` at module scope, so a reverse
module-scope edge from ``sase.agent`` back into the ``sase.monitor`` package is
a circular import. If a reverse edge is ever genuinely needed, keep it
function-local instead.
"""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import textwrap

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
_AGENT_DIR = _SRC_DIR / "sase" / "agent"


def _run_probe(source: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def _module_scope_imports(node: ast.AST) -> list[ast.Import | ast.ImportFrom]:
    if isinstance(node, ast.Import | ast.ImportFrom):
        return [node]
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return []
    imports: list[ast.Import | ast.ImportFrom] = []
    for child in ast.iter_child_nodes(node):
        imports.extend(_module_scope_imports(child))
    return imports


def _package_for_path(path: Path) -> str:
    relative = path.relative_to(_SRC_DIR).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] != "__init__":
        parts.pop()
    else:
        parts.pop()
    return ".".join(parts)


def _resolve_from_module(node: ast.ImportFrom, package: str) -> str:
    if node.level == 0:
        return node.module or ""
    base_parts = package.split(".") if package else []
    parent_levels = node.level - 1
    if parent_levels:
        base_parts = base_parts[:-parent_levels]
    if node.module:
        base_parts.extend(node.module.split("."))
    return ".".join(base_parts)


def _imported_modules(
    node: ast.Import | ast.ImportFrom,
    *,
    package: str,
) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names}
    module = _resolve_from_module(node, package)
    modules = {module} if module else set()
    for alias in node.names:
        if alias.name == "*" or not module:
            continue
        modules.add(f"{module}.{alias.name}")
    return modules


def _is_monitor_package(module: str) -> bool:
    return module == "sase.monitor" or module.startswith("sase.monitor.")


def _agent_monitor_package_imports() -> list[tuple[str, str]]:
    offenders: list[tuple[str, str]] = []
    for path in sorted(_AGENT_DIR.rglob("*.py")):
        relative = path.relative_to(_SRC_DIR).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        package = _package_for_path(path)
        modules = sorted(
            {
                module
                for node in _module_scope_imports(tree)
                for module in _imported_modules(node, package=package)
                if _is_monitor_package(module)
            }
        )
        offenders.extend((relative, module) for module in modules)
    return offenders


def test_agent_modules_do_not_import_monitor_package_at_module_scope() -> None:
    offenders = _agent_monitor_package_imports()

    assert not offenders, (
        "sase.agent must not import the sase.monitor package at module scope: "
        + ", ".join(f"{path} -> {module}" for path, module in offenders)
    )


def test_launch_admission_store_cold_import_succeeds() -> None:
    _run_probe(
        """
        import sase.agent.launch_admission_store as store

        assert store.ADMISSION_DIRNAME == "launch_admission"
        """
    )


def test_lumberjack_then_launch_admission_store_keeps_monitor_unloaded() -> None:
    _run_probe(
        """
        import sys

        import sase.axe.lumberjack
        import sase.agent.launch_admission_store as store

        assert store.ADMISSION_DIRNAME == "launch_admission"
        monitor_modules = [
            name
            for name in sys.modules
            if name == "sase.monitor" or name.startswith("sase.monitor.")
        ]
        assert not monitor_modules, monitor_modules
        """
    )
