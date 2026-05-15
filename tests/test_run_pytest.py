from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest


RUN_PYTEST_PATH = Path(__file__).resolve().parents[1] / "tools" / "run_pytest"


def _load_run_pytest() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "sase_test_run_pytest", str(RUN_PYTEST_PATH)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise AssertionError("failed to create module spec for tools/run_pytest")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class _ExecvCalled(RuntimeError):
    def __init__(self, executable: str, command: list[str]) -> None:
        super().__init__("os.execv called")
        self.executable = executable
        self.command = command


@pytest.fixture
def run_pytest() -> ModuleType:
    return _load_run_pytest()


def test_fast_visual_invocation_keeps_broad_png_tolerance(
    run_pytest: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SASE_VISUAL_PNG_MAX_DIFF_RATIO", raising=False)
    monkeypatch.setattr(os, "chdir", lambda path: None)

    def fake_execv(executable: str, command: list[str]) -> None:
        raise _ExecvCalled(executable, command)

    monkeypatch.setattr(os, "execv", fake_execv)

    with pytest.raises(_ExecvCalled) as exc_info:
        run_pytest.main(["fast", "--visual"])

    assert os.environ["SASE_VISUAL_PNG_MAX_DIFF_RATIO"] == "0.001"
    assert exc_info.value.executable == sys.executable
    assert exc_info.value.command[-2:] == ["-m", "visual"]


def test_dedicated_visual_invocation_stays_strict(
    run_pytest: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SASE_VISUAL_PNG_MAX_DIFF_RATIO", raising=False)
    monkeypatch.setattr(os, "chdir", lambda path: None)

    def fake_execv(executable: str, command: list[str]) -> None:
        raise _ExecvCalled(executable, command)

    monkeypatch.setattr(os, "execv", fake_execv)

    with pytest.raises(_ExecvCalled):
        run_pytest.main(["visual"])

    assert "SASE_VISUAL_PNG_MAX_DIFF_RATIO" not in os.environ
