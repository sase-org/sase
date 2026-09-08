"""Guard against a package shadowing a same-named sibling module in ``src/sase``.

Python's import machinery resolves a regular package before a module of the
same name, so adding ``foo/`` next to an existing ``foo.py`` silently hides the
module: ``from .foo import Bar`` starts raising ``ImportError`` at import time
and takes the whole ``sase`` CLI down with it. Two concurrently landed features
did exactly that to ``sase.llm_provider.usage``, so the layout is asserted here.
"""

from __future__ import annotations

from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "sase"


def _shadowed_module(directory: Path) -> Path:
    return directory.parent / f"{directory.name}.py"


def test_no_package_shadows_a_sibling_module() -> None:
    collisions = sorted(
        f"{directory.relative_to(_SRC_ROOT.parent)}/ shadows "
        f"{_shadowed_module(directory).relative_to(_SRC_ROOT.parent)}"
        for directory in _SRC_ROOT.rglob("*")
        if directory.is_dir()
        and directory.name != "__pycache__"
        and _shadowed_module(directory).is_file()
    )
    assert not collisions, (
        "a package hides a same-named sibling module; rename one of them:\n"
        + "\n".join(collisions)
    )
