"""Proc log path, tail, pipe-bounding, and deletion tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from sase.procs import (
    delete_proc_logs,
    open_proc_log,
    proc_log_path,
    read_proc_log_tail,
)


def test_proc_log_pipe_bounds_subprocess_output(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setenv("SASE_PROC_LOG_MAX_BYTES", "64")

    with open_proc_log("proc-one") as output:
        subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; print('A' * 100); sys.stdout.flush(); "
                    "print('tail', file=sys.stderr)"
                ),
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
            check=True,
        )

    path = proc_log_path("proc-one")
    assert path.stat().st_size <= 64
    assert "tail" in path.read_text(encoding="utf-8")


def test_proc_log_tail_spans_rotation_and_delete(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = proc_log_path("proc-one")
    path.parent.mkdir(parents=True)
    path.with_name(f"{path.name}.1").write_text("one\ntwo\n", encoding="utf-8")
    path.write_text("three\nfour\n", encoding="utf-8")

    assert read_proc_log_tail("proc-one", 3) == "two\nthree\nfour\n"
    delete_proc_logs(["proc-one", "missing"])
    assert not path.exists()
    assert not path.with_name(f"{path.name}.1").exists()


def test_proc_log_path_rejects_traversal(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    with pytest.raises(ValueError, match="invalid proc id"):
        proc_log_path("../escape")


def test_delete_proc_logs_skips_paths_outside_the_proc_log_root(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    outside = tmp_path / "artifacts" / "owned.log"
    outside.parent.mkdir(parents=True)
    outside.write_text("keep", encoding="utf-8")

    delete_proc_logs(["escape-proc"], log_paths={"escape-proc": str(outside)})

    assert outside.read_text(encoding="utf-8") == "keep"


def test_read_proc_log_tail_follows_an_explicit_log_path(tmp_path: Path) -> None:
    custom = tmp_path / "custom" / "out.log"
    custom.parent.mkdir(parents=True)
    custom.write_text("alpha\nbeta\n", encoding="utf-8")

    assert read_proc_log_tail("ignored-id", 1, log_path=custom) == "beta\n"
