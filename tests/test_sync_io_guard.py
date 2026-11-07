"""Tests for the caller-scoped synchronous file-I/O guard."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import sase
from tests._sync_io_guard import (
    CODE_UNDER_TEST_DIRS,
    ForbiddenFileIO,
    forbid_sync_file_io,
)

_PROBE_SOURCE = """
def stat_path(path):
    return os.stat(path)

def swallow_exists(path):
    try:
        return Path(path).exists()
    except Exception:
        return None

def call(function, *args):
    return function(*args)
"""


class _Probe:
    """Helpers compiled under a scratch directory standing in for ``sase``.

    The probe never lives under the real ``sase`` tree: coverage measures that
    tree, and a phantom file there breaks every later coverage report.
    """

    def __init__(self, root: Path) -> None:
        directory = root / "cut"
        directory.mkdir()
        self.scope = (os.path.join(str(directory), ""),)
        self.functions: dict[str, Any] = {"os": os, "Path": Path}
        source = compile(_PROBE_SOURCE, str(directory / "probe.py"), "exec")
        exec(source, self.functions)

    def __getitem__(self, name: str) -> Callable[..., Any]:
        return self.functions[name]


@pytest.fixture
def probe(tmp_path: Path) -> _Probe:
    return _Probe(tmp_path)


def test_default_scope_is_the_sase_package() -> None:
    assert CODE_UNDER_TEST_DIRS
    assert all(prefix.endswith(os.sep) for prefix in CODE_UNDER_TEST_DIRS)
    assert sase.__file__ is not None
    assert sase.__file__.startswith(CODE_UNDER_TEST_DIRS)


def test_code_under_test_io_raises_and_names_the_call_site(
    tmp_path: Path, probe: _Probe
) -> None:
    with pytest.raises(ForbiddenFileIO) as raised:
        with forbid_sync_file_io(
            "os.stat", reason="probe must stay in memory", code_under_test=probe.scope
        ):
            probe["stat_path"](tmp_path)

    message = str(raised.value)
    assert message.startswith("probe must stay in memory: os.stat(")
    assert "cut/probe.py:3 in stat_path" in message


def test_swallowed_io_still_fails_the_block(tmp_path: Path, probe: _Probe) -> None:
    with pytest.raises(AssertionError, match="exists") as raised:
        with forbid_sync_file_io(
            "pathlib.Path.exists", reason="no exists", code_under_test=probe.scope
        ):
            assert probe["swallow_exists"](tmp_path) is None

    assert not isinstance(raised.value, ForbiddenFileIO)
    assert "swallow_exists" in str(raised.value)


def test_test_code_and_stdlib_io_pass_through(tmp_path: Path) -> None:
    with forbid_sync_file_io(
        "os.stat", "os.listdir", "pathlib.Path.exists", reason="test code"
    ) as guard:
        assert os.stat(tmp_path).st_size >= 0
        assert os.listdir(tmp_path) == []
        assert tmp_path.exists()

    assert guard.calls == []


def test_harness_frames_nearer_than_sase_pass_through(
    tmp_path: Path, probe: _Probe
) -> None:
    """Coverage's tracer runs on top of sase frames; its I/O is not sase's."""
    inorout = pytest.importorskip("coverage.inorout")

    with forbid_sync_file_io(
        "os.stat", reason="tracer", code_under_test=probe.scope
    ) as guard:
        detail = probe["call"](inorout._analyze_directory, str(tmp_path))

    assert detail.exists is True
    assert guard.calls == []


def test_other_threads_pass_through_unless_any_thread(
    tmp_path: Path, probe: _Probe
) -> None:
    outcomes: list[object] = []

    def run() -> None:
        try:
            outcomes.append(probe["stat_path"](tmp_path).st_size >= 0)
        except ForbiddenFileIO as error:
            outcomes.append(error)

    for any_thread in (False, True):
        try:
            with forbid_sync_file_io(
                "os.stat",
                reason="t",
                any_thread=any_thread,
                code_under_test=probe.scope,
            ):
                worker = threading.Thread(target=run)
                worker.start()
                worker.join()
        except AssertionError:
            pass

    assert outcomes[0] is True
    assert isinstance(outcomes[1], ForbiddenFileIO)


def test_patches_are_restored_after_the_block() -> None:
    original_stat = os.stat
    original_exists = Path.exists

    with forbid_sync_file_io("os.stat", "pathlib.Path.exists", reason="restore"):
        assert os.stat is not original_stat
        assert Path.exists is not original_exists

    assert os.stat is original_stat
    assert Path.exists is original_exists


def test_rejects_unresolvable_and_descriptor_targets() -> None:
    with pytest.raises(ValueError, match="at least one target"):
        with forbid_sync_file_io(reason="none"):
            pass
    with pytest.raises(ValueError, match="cannot import"):
        with forbid_sync_file_io("no_such_module_xyz.thing", reason="bad"):
            pass
    with pytest.raises(TypeError, match="classmethod"):
        with forbid_sync_file_io("pathlib.Path.cwd", reason="bad"):
            pass
