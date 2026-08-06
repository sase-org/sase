"""Tests for the per-test TMPDIR/SASE_PYTEST_TMP_REDIRECTED env-leak guard.

This guard is the per-test companion to the session-scoped directory-entry
guard covered by test_tmp_leak_guard.py: it watches the two env vars
``tools/run_pytest``'s ``_prepare_pytest_tmpdir()`` writes directly to
``os.environ`` and fails whichever test leaves one changed past its own
teardown, instead of letting the mutation silently redirect every later test
on the same xdist worker at a ``tmp_path`` pytest has already deleted.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from tests._tmp_leak_guard import (
    ENV_LEAK_WATCHED_VARS,
    check_tmp_env_leak_guard,
    snapshot_env_leak_watch,
    start_tmp_env_leak_guard,
)


pytest_plugins = ["pytester"]

_ROOT = Path(__file__).resolve().parents[1]


class _FakeItem:
    """A stand-in for ``pytest.Item`` that only needs a nodeid and attrs."""

    def __init__(self, nodeid: str = "tests/test_example.py::test_thing") -> None:
        self.nodeid = nodeid


def test_watched_vars_cover_what_prepare_pytest_tmpdir_mutates() -> None:
    assert ENV_LEAK_WATCHED_VARS == ("TMPDIR", "SASE_PYTEST_TMP_REDIRECTED")


def test_snapshot_reads_the_watched_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", "/tmp/example")
    monkeypatch.delenv("SASE_PYTEST_TMP_REDIRECTED", raising=False)

    assert snapshot_env_leak_watch() == {
        "TMPDIR": "/tmp/example",
        "SASE_PYTEST_TMP_REDIRECTED": None,
    }


def test_check_passes_when_nothing_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", "/tmp/stable")
    item: Any = _FakeItem()
    start_tmp_env_leak_guard(item)

    check_tmp_env_leak_guard(item)  # must not raise


def test_check_is_a_no_op_without_a_recorded_baseline() -> None:
    item: Any = _FakeItem()

    check_tmp_env_leak_guard(item)  # must not raise; nothing was started


def test_check_fails_and_names_the_offending_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TMPDIR", raising=False)
    item: Any = _FakeItem("tests/test_leaky.py::test_leaks_tmpdir")
    start_tmp_env_leak_guard(item)

    os.environ["TMPDIR"] = "/tmp/leaked-by-test"
    try:
        with pytest.raises(pytest.fail.Exception, match="test_leaks_tmpdir"):
            check_tmp_env_leak_guard(item)
    finally:
        os.environ.pop("TMPDIR", None)


def test_check_names_every_var_that_leaked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.delenv("SASE_PYTEST_TMP_REDIRECTED", raising=False)
    item: Any = _FakeItem()
    start_tmp_env_leak_guard(item)

    os.environ["TMPDIR"] = "/tmp/leaked"
    os.environ["SASE_PYTEST_TMP_REDIRECTED"] = "1"
    try:
        with pytest.raises(pytest.fail.Exception) as excinfo:
            check_tmp_env_leak_guard(item)
    finally:
        os.environ.pop("TMPDIR", None)
        os.environ.pop("SASE_PYTEST_TMP_REDIRECTED", None)

    message = str(excinfo.value)
    assert "TMPDIR" in message
    assert "SASE_PYTEST_TMP_REDIRECTED" in message


def test_guard_wiring_fails_a_leaking_test_but_not_a_monkeypatched_one(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end proof of the hooks wired into tests/conftest.py.

    Runs a nested pytest subprocess (so the deliberate leak below cannot
    reach this outer session) with a throwaway conftest that reproduces the
    exact pytest_runtest_setup/pytest_runtest_teardown wiring in
    tests/conftest.py, calling the real guard functions under test.
    """
    monkeypatch.setenv("PYTHONPATH", str(_ROOT))
    pytester.makeconftest(
        """
        from tests._tmp_leak_guard import (
            check_tmp_env_leak_guard,
            start_tmp_env_leak_guard,
        )
        import pytest

        def pytest_runtest_setup(item):
            start_tmp_env_leak_guard(item)

        @pytest.hookimpl(wrapper=True)
        def pytest_runtest_teardown(item, nextitem):
            yield
            check_tmp_env_leak_guard(item)
        """
    )
    pytester.makepyfile(
        """
        import os

        def test_leaks_tmpdir():
            os.environ["TMPDIR"] = "/tmp/leaked-by-this-test"

        def test_uses_monkeypatch_correctly(monkeypatch):
            monkeypatch.setenv("TMPDIR", "/tmp/set-by-monkeypatch")
        """
    )

    result = pytester.runpytest_subprocess(
        "-p", "no:randomly", "-c", str(_ROOT / "pyproject.toml"), timeout=60
    )

    # A failing teardown reports separately from a passing call phase, so the
    # leaking test contributes to both "passed" (its call) and "errors" (its
    # teardown); the monkeypatched test only ever passes.
    result.assert_outcomes(passed=2, failed=0, errors=1)
    result.stdout.fnmatch_lines(["*ERROR*test_leaks_tmpdir*"])
