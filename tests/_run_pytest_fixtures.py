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

from tests._test_selection_health import STORE_ENV
from tests._tmp_leak_guard import PYTEST_TMP_REDIRECTED_ENV


ROOT = Path(__file__).resolve().parents[1]
RUN_PYTEST_PATH = ROOT / "tools" / "run_pytest"
# The keys ``_prepare_pytest_tmpdir`` assigns straight into ``os.environ``.
PROCESS_ENV_KEYS = ("TMPDIR", PYTEST_TMP_REDIRECTED_ENV)


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


def pin_process_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confine ``run_pytest``'s raw ``TMPDIR`` redirect to the calling test.

    ``_prepare_pytest_tmpdir`` redirects scratch by assigning ``os.environ``
    directly, which is right for the runner process but leaks out of any test
    that reaches it: monkeypatch never saw the write, so the redirect outlives
    the test and every later test in the same xdist worker inherits a
    ``TMPDIR`` pointing at a ``tmp_path`` pytest has since deleted. Python's
    ``tempfile`` caches its directory on first use and never notices, but
    native code re-reads ``TMPDIR`` on every call — sase-core's ``git log``
    scratch file is one, and it silently dropped every commit row from the
    artifact-ref inventory once a leaked value reached it.

    Registering the keys up front gives monkeypatch a baseline to roll back to.
    """
    for key in PROCESS_ENV_KEYS:
        was_set = key in os.environ
        # Records the pre-test value (``notset`` when the key was absent).
        monkeypatch.setenv(key, os.environ.get(key, ""))
        if not was_set:
            # Undo the placeholder without dropping the recorded baseline.
            monkeypatch.delenv(key)


def health_store(tmp_path: Path) -> Path:
    """Where a test's scoped and full-lane health records should land."""
    return tmp_path / "health-store"


def scoped_selection(
    runner: ModuleType,
    *,
    selected: tuple[str, ...] = (),
    escalated: bool = False,
    rules: tuple[str, ...] = ("contract-set-always",),
) -> object:
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
