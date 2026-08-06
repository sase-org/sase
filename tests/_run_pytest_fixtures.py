"""Shared harness for the ``tools/run_pytest`` test modules.

``tools/run_pytest`` is a script rather than an importable package module, so
every test that exercises it has to load it by path. These helpers keep that —
and the scoped-mode plumbing several modules need to stub — in one place.
"""

from __future__ import annotations

import importlib.util
import os
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from tests._test_selection_health_store import STORE_ENV


ROOT = Path(__file__).resolve().parents[1]
RUN_PYTEST_PATH = ROOT / "tools" / "run_pytest"

# Every process global `tools/run_pytest`'s main() mutates on its way to
# execv: TMPDIR and SASE_PYTEST_TMP_REDIRECTED (_prepare_pytest_tmpdir()), and
# the four keys _sanitize_pytest_environment() pops
# (run_pytest.PYTEST_ENV_UNSET_KEYS). Duplicated here rather than derived by
# calling load_run_pytest(), which would re-exec the module on every test; a
# contract test in test_run_pytest_main.py pins the two lists together.
PINNED_ENV_VARS: tuple[str, ...] = (
    "TMPDIR",
    "SASE_PYTEST_TMP_REDIRECTED",
    "SASE_COMMIT_METHOD",
    "SASE_COMMIT_METHOD_ALLOW_OVERRIDE",
    "SASE_PR_NAME",
    "SASE_PR_STATUS",
)


@pytest.fixture(autouse=True)
def isolate_run_pytest_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every process global `main()` writes so teardown restores it.

    `main()` writes straight to `os.environ` and calls `os.chdir()` as part of
    its documented contract -- that mutation is real and exercised by every
    `just test` invocation. The defect this closes is tests driving `main()`
    without pinning those globals first, so a leak outlives the test's own
    teardown and poisons every later test on the same xdist worker. Every
    module that calls `load_run_pytest()` imports this fixture.
    """
    for name in PINNED_ENV_VARS:
        current = os.environ.get(name)
        monkeypatch.setenv(name, "" if current is None else current)
        if current is None:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(os.getcwd())


def load_run_pytest() -> ModuleType:
    """Load ``tools/run_pytest`` as a module under a stable name."""
    loader = SourceFileLoader("run_pytest_tool", str(RUN_PYTEST_PATH))
    spec = importlib.util.spec_from_file_location(
        "run_pytest_tool", RUN_PYTEST_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def health_store(tmp_path: Path) -> Path:
    """Where a test's scoped and full-lane health records should land."""
    return tmp_path / "health-store"


def scoped_selection(
    runner: ModuleType,
    *,
    selected: tuple[str, ...] = (),
    escalated: bool = False,
    rules: tuple[str, ...] = ("contract-set-always",),
    gear_candidate: tuple[str, ...] = (),
) -> object:
    """A fabricated `Selection`, as `select_tests` would have returned it.

    ``gear_candidate`` is what the serial budget rejected: non-empty only on
    an escalated selection the middle gear is allowed to try to run.
    """
    return runner.Selection(
        selected=selected,
        escalated=escalated,
        rules=rules,
        manifest={
            "schema": 1,
            "escalated": escalated,
            "selected": list(selected),
            "selected_count": len(selected),
            "universe_count": 2408,
        },
        explanations={path: (path, 0) for path in selected},
        universe_count=2408,
        gear_candidate=gear_candidate,
    )


def install_scoped_selection(
    runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selection: object,
) -> Path:
    """Point scoped mode at a fabricated selection and a scratch manifest."""
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setenv(STORE_ENV, str(health_store(tmp_path)))
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(tmp_path / "scratch"))
    monkeypatch.setattr(runner, "_scoped_manifest_path", lambda: manifest_path)
    monkeypatch.setattr(runner, "select_tests", lambda *_args, **_kwargs: selection)
    return manifest_path


def forbid_pytest_launch(runner: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    def _unexpected_execv(_executable: str, _command: list[str]) -> None:
        raise AssertionError("scoped mode exec'd pytest unexpectedly")

    def _unexpected_run(_command: list[str], **_kwargs: object) -> None:
        raise AssertionError("scoped mode launched pytest unexpectedly")

    monkeypatch.setattr(runner.os, "execv", _unexpected_execv)
    monkeypatch.setattr(runner.subprocess, "run", _unexpected_run)
