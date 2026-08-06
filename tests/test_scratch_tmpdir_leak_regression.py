"""Regression test pinning the TMPDIR/SASE_PYTEST_TMP_REDIRECTED ordering leak.

``test_prepare_pytest_tmpdir_honors_override`` (tests/test_run_pytest_tmpdir.py)
calls the real ``_prepare_pytest_tmpdir()``, which mutates ``TMPDIR`` and
``SASE_PYTEST_TMP_REDIRECTED`` directly on ``os.environ``.
``test_scoped_run_lands_in_the_durable_health_store``
(tests/test_run_pytest_health.py) reaches the same two writes by driving the
real ``main()`` through scoped mode -- one of ten sibling tests that leak the
same way by calling ``main()`` at all, not just the one that calls
``_prepare_pytest_tmpdir()`` directly. Both are now isolated by the autouse
``isolate_run_pytest_environment`` fixture (tests/_run_pytest_fixtures.py),
and any regression is additionally contained by
``check_tmp_env_leak_guard()`` (tests/_tmp_leak_guard.py), which restores the
watched vars to their baseline before failing the offender.

That containment changes what a regression here looks like. Before, an
unrestored ``TMPDIR`` pointed ``$TMPDIR`` at a ``tmp_path`` pytest had already
deleted (``tmp_path_retention_policy = "failed"``), so any later test on the
same xdist worker that reads it directly -- as sase-core's
``commit_log_output`` does -- resolved a directory that no longer existed, and
the downstream catalog test failed with no clue why. Now a regression shows up
as an **error** on the offender itself (the guard's own ``pytest.fail()``),
not as a failure on its unrelated neighbor.

Running the exact node IDs from the CI failure in one nested pytest subprocess
pins the fix at the ordering level. Asserting on ``os.environ["TMPDIR"]``
after the fact would only re-test the fix in isolation from the sequencing
that actually broke it.
"""

from __future__ import annotations

from pathlib import Path

import pytest


pytest_plugins = ["pytester"]

_ROOT = Path(__file__).resolve().parents[1]

_LEAKING_NODE_ID = (
    str(_ROOT / "tests/test_run_pytest_tmpdir.py")
    + "::test_prepare_pytest_tmpdir_honors_override"
)
_MAIN_DRIVEN_LEAKING_NODE_ID = (
    str(_ROOT / "tests/test_run_pytest_health.py")
    + "::test_scoped_run_lands_in_the_durable_health_store"
)
_DOWNSTREAM_NODE_ID = (
    str(_ROOT / "tests/ace/tui/widgets/test_artifact_ref_completion_catalog.py")
    + "::test_commit_completion_rows_match_shared_inventory_and_resolve"
)


def test_prepare_pytest_tmpdir_leak_does_not_break_a_later_scratch_read(
    pytester: pytest.Pytester,
) -> None:
    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-c",
        str(_ROOT / "pyproject.toml"),
        "--rootdir",
        str(_ROOT),
        _LEAKING_NODE_ID,
        _MAIN_DRIVEN_LEAKING_NODE_ID,
        _DOWNSTREAM_NODE_ID,
        timeout=60,
    )
    result.assert_outcomes(passed=3)
