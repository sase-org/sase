"""Synthetic-repository fixtures for the test-selection engine's tests.

The tree has a deliberate shape: an import chain deep enough to show depth
bounding, a fan-out hub, a mutual cycle, a ring large enough that an unbounded
walk would swallow it whole, a test-support helper that is the only route to
one test file, and a visual test that the selector must never return.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


RING_SIZE = 12


def _write(root: Path, path: str, content: str = "") -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _fixture_files() -> dict[str, str]:
    files = {
        ".gitignore": ".pytest_cache/\n",
        "pyproject.toml": "[project]\nname = 'fixture'\n",
        "uv.lock": "",
        "Justfile": "check:\n\t@true\n",
        "tools/run_pytest": "#!/usr/bin/env python3\n",
        "docs/development.md": "# docs\n",
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "VALUE = 1\n",
        "src/pkg/b.py": "from pkg.a import VALUE\n",
        "src/pkg/c.py": "from pkg import b\n",
        "src/pkg/d.py": "import pkg.c\n",
        "src/pkg/hub.py": "from .a import VALUE\n",
        "src/pkg/cycle_x.py": "from pkg import cycle_y\n",
        "src/pkg/cycle_y.py": "from pkg import a, cycle_x\n",
        "src/pkg/config.yml": "key: value\n",
        "tests/__init__.py": "",
        "tests/conftest.py": "from tests import _suite_gate\n",
        "tests/_suite_gate.py": "",
        "tests/_helper.py": "from pkg.a import VALUE\n",
        "tests/test_a.py": "from pkg import a\n",
        "tests/test_b.py": "from pkg import b\n",
        "tests/test_c.py": "from pkg import c\n",
        "tests/test_d.py": "from pkg import d\n",
        "tests/test_via_helper.py": "from tests._helper import VALUE\n",
        "tests/test_cycle.py": "from pkg import cycle_x\n",
        "tests/sub/__init__.py": "",
        "tests/sub/conftest.py": "",
        "tests/sub/test_sub.py": "",
        "tests/sub/test_sub_other.py": "",
        "tests/ace/tui/visual/test_visual.py": "from tests._helper import VALUE\n",
    }
    for index in range(RING_SIZE):
        successor = (index + 1) % RING_SIZE
        files[f"src/pkg/ring{index}.py"] = f"from pkg import ring{successor}\n"
        files[f"tests/test_ring{index}.py"] = f"from pkg import ring{index}\n"
    return files


def build_fixture_repo(tmp_path: Path) -> Path:
    """Materialize and commit the synthetic repository under ``tmp_path``."""
    root = tmp_path / "repo"
    root.mkdir()
    for path, content in _fixture_files().items():
        _write(root, path, content)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "fixture")
    return root


def _touch(root: Path, path: str) -> None:
    """Make a benign, content-changing edit to a tracked file."""
    target = root / path
    target.write_text(target.read_text(encoding="utf-8") + "\n# touched\n", "utf-8")
