"""Tests for the extensionless tools mypy helper."""

from __future__ import annotations

import importlib.util
import json
import shutil
import stat
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "typecheck_extensionless_tools"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("typecheck_extensionless_tools_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "typecheck_extensionless_tools_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_tool_script_is_executable() -> None:
    assert TOOL_PATH.exists()
    assert TOOL_PATH.stat().st_mode & 0o111


def test_discovers_extensionless_python_tools_and_skips_transient_dirs(
    tmp_path: Path,
) -> None:
    tools_dir = tmp_path / "tools"
    selected = tools_dir / "selected"
    nested = tools_dir / "nested" / "also_selected"
    _write_executable(selected, "#!/usr/bin/env python3\nprint('ok')\n")
    _write_executable(nested, "#!/usr/bin/python3\nprint('ok')\n")
    _write_executable(tools_dir / "with_suffix.py", "#!/usr/bin/env python3\n")
    _write_executable(tools_dir / "shell_tool", "#!/usr/bin/env bash\n")
    _write_executable(
        tools_dir / ".mypy_cache" / "cached_tool",
        "#!/usr/bin/env python3\n",
    )
    _write_executable(
        tools_dir / "__pycache__" / "cached_tool",
        "#!/usr/bin/env python3\n",
    )

    tool = _load_tool()

    assert tool.discover_extensionless_python_tools(tools_dir) == [nested, selected]


def test_invokes_mypy_once_with_script_flags_and_propagates_exit(
    tmp_path: Path,
) -> None:
    tools_dir = tmp_path / "tools"
    script = tools_dir / "selected"
    argv_path = tmp_path / "argv.json"
    _write_executable(script, "#!/usr/bin/env python3\nprint('ok')\n")
    fake_mypy = tmp_path / "fake_mypy"
    _write_executable(
        fake_mypy,
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "import json\n"
        "import sys\n"
        f"open({str(argv_path)!r}, 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n"
        "raise SystemExit(17)\n",
    )

    tool = _load_tool()

    assert tool.main(["--tools-dir", str(tools_dir), "--mypy", str(fake_mypy)]) == 17
    assert json.loads(argv_path.read_text(encoding="utf-8")) == [
        "--scripts-are-modules",
        "--follow-imports=skip",
        "--ignore-missing-imports",
        "tools/selected",
    ]


def test_assignment_error_in_temporary_extensionless_tool_fails_mypy(
    tmp_path: Path,
) -> None:
    mypy = shutil.which("mypy")
    if mypy is None:
        pytest.skip("mypy executable is not available")

    tools_dir = tmp_path / "tools"
    _write_executable(
        tools_dir / "bad_tool",
        "#!/usr/bin/env python3\n"
        "def main() -> int:\n"
        "    value: int = 'not an int'\n"
        "    return value\n",
    )
    tool = _load_tool()

    assert tool.main(["--tools-dir", str(tools_dir), "--mypy", mypy]) != 0
