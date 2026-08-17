"""Ordering regression for the ACE proc-observer leak (sase-mv).

Constructing ``AceApp`` starts ``sase-ace-proc-observer`` in ``__init__``.
Tests that never mount/unmount used to leave that poller alive, and its
timezone path called ``load_merged_config()`` during later config-cache
tests. The autouse isolation fixture now stops orphaned observers before
clearing config caches. Running the poisoner then the victim in one nested
pytest subprocess pins that fixture lifecycle.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest
from sase.ace.tui.app import AceApp
from sase.ace.tui.proc_observer import PROC_OBSERVER_THREAD_NAME


pytest_plugins = ["pytester"]

_ROOT = Path(__file__).resolve().parents[1]
_THIS_FILE = str(Path(__file__).resolve())
_ISOLATION_CHILD_ENV = "SASE_TEST_OBSERVER_ISOLATION_CHILD"


def _live_proc_observer_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == PROC_OBSERVER_THREAD_NAME and thread.is_alive()
    ]


def test_poisoner_constructs_ace_app_without_unmount() -> None:
    """Start the proc observer the way construction-only ACE tests do."""
    app = AceApp(query="!!!", auto_start_axe=False)
    assert app._proc_observer.running
    assert _live_proc_observer_threads()


def test_victim_sees_no_live_proc_observer_after_isolation_drain() -> None:
    """Successor tests must not inherit a construction-only observer thread."""
    if os.environ.get(_ISOLATION_CHILD_ENV) != "1":
        pytest.skip("paired isolation victim; run via nested pytest")
    assert _live_proc_observer_threads() == []


def test_constructed_ace_app_does_not_poison_a_later_test(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ISOLATION_CHILD_ENV, "1")
    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-c",
        str(_ROOT / "pyproject.toml"),
        "--rootdir",
        str(_ROOT),
        f"{_THIS_FILE}::test_poisoner_constructs_ace_app_without_unmount",
        f"{_THIS_FILE}::test_victim_sees_no_live_proc_observer_after_isolation_drain",
        timeout=60,
    )
    result.assert_outcomes(passed=2)
