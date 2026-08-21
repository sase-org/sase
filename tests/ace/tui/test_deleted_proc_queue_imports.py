from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest


def test_deleted_proc_queue_module_is_not_importable() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("sase.ace.tui.proc_queue")


def test_tests_do_not_import_deleted_proc_queue_module() -> None:
    tests_root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []

    for path in tests_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "sase.ace.tui.proc_queue"
            ):
                offenders.append(str(path.relative_to(tests_root)))
            elif isinstance(node, ast.Import):
                if any(alias.name == "sase.ace.tui.proc_queue" for alias in node.names):
                    offenders.append(str(path.relative_to(tests_root)))

    assert offenders == []
