from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_repair_tool() -> ModuleType:
    loader = SourceFileLoader(
        "repair_venv_entrypoints_tool",
        str(ROOT / "tools" / "repair_venv_entrypoints"),
    )
    spec = importlib.util.spec_from_file_location(
        "repair_venv_entrypoints_tool",
        ROOT / "tools" / "repair_venv_entrypoints",
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repair_venv_entrypoints_rewrites_stale_python_shebang(
    tmp_path: Path,
) -> None:
    repair_tool = _load_repair_tool()
    venv = tmp_path / "repo" / ".venv"
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    target_python = bin_dir / "python3"
    target_python.write_text("", encoding="utf-8")
    script = bin_dir / "pytest"
    script.write_text(
        f"#!{tmp_path}/other/.venv/bin/python3\nprint('ok')\n",
        encoding="utf-8",
    )

    repaired = repair_tool.repair_venv_entrypoints(venv)

    assert repaired == [script]
    assert script.read_text(encoding="utf-8").splitlines()[0] == f"#!{target_python}"


def test_repair_venv_entrypoints_preserves_current_shebang(tmp_path: Path) -> None:
    repair_tool = _load_repair_tool()
    venv = tmp_path / "repo" / ".venv"
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    target_python = bin_dir / "python3"
    target_python.write_text("", encoding="utf-8")
    script = bin_dir / "pytest"
    original = f"#!{target_python}\nprint('ok')\n"
    script.write_text(original, encoding="utf-8")

    repaired = repair_tool.repair_venv_entrypoints(venv)

    assert repaired == []
    assert script.read_text(encoding="utf-8") == original


def test_repair_venv_entrypoints_ignores_env_shebang(tmp_path: Path) -> None:
    repair_tool = _load_repair_tool()
    venv = tmp_path / "repo" / ".venv"
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python3").write_text("", encoding="utf-8")
    script = bin_dir / "custom"
    original = "#!/usr/bin/env python3\nprint('ok')\n"
    script.write_text(original, encoding="utf-8")

    repaired = repair_tool.repair_venv_entrypoints(venv)

    assert repaired == []
    assert script.read_text(encoding="utf-8") == original
