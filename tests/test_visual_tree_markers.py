"""Every test module under a visual root must run in the visual lane.

A ``test_*.py`` file under ``tests/ace/tui/visual/`` or ``tests/pager/visual/``
without ``pytestmark = pytest.mark.visual`` silently drops out of the visual
lane (``-m visual`` deselects it), so a requested full capture inventory can
never be proven. This parses each module statically (no imports) and requires
a module-level ``pytestmark`` that includes ``pytest.mark.visual``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_VISUAL_DIRS = (
    _REPO_ROOT / "tests" / "ace" / "tui" / "visual",
    _REPO_ROOT / "tests" / "pager" / "visual",
)


def _has_visual_mark(value: ast.AST) -> bool:
    for node in ast.walk(value):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "visual"
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "mark"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "pytest"
        ):
            return True
    return False


def _module_marks_visual(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if value is not None and any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in targets
        ):
            if _has_visual_mark(value):
                return True
    return False


def test_every_visual_tree_test_module_is_marked_visual() -> None:
    offenders: list[str] = []
    checked = 0
    for visual_dir in _VISUAL_DIRS:
        assert visual_dir.is_dir(), f"visual root is missing: {visual_dir}"
        for path in sorted(visual_dir.glob("test_*.py")):
            checked += 1
            if not _module_marks_visual(path):
                offenders.append(
                    path.relative_to(_REPO_ROOT).as_posix(),
                )
    assert checked > 0, "no visual test modules found"
    assert not offenders, (
        "test modules under a visual root without "
        "`pytestmark = pytest.mark.visual` (they are deselected from the "
        "visual lane and block full inventories): " + ", ".join(offenders)
    )
