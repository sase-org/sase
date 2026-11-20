"""The installer's last-swap stamp matches ``sase``'s, and every run records one.

The stdlib-only installer mirrors ``sase.dev_update.code_swap_stamp`` instead of
importing it. These tests pin the mirror: same file, same shape, one shared
generation counter across both writers, and a stamp on every release, so the
chop runner's post-swap grace sees ``just install`` and ``just install-dev``
swaps exactly like ``sase dev update`` ones.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sase.dev_update import code_swap_stamp as stamp_mod
from sase.dev_update.code_swap_lock import code_swap_writer_lock
from tests.sase_install._run_dev_harness import Harness as DevHarness
from tests.sase_install._run_pypi_harness import Harness, install_run


def _read_sase_stamp(
    monkeypatch: pytest.MonkeyPatch, sase_home: Path
) -> stamp_mod._LastCodeSwap | None:
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    return stamp_mod.read_last_code_swap()


def test_stamp_path_matches_sase(tmp_path: Path, monkeypatch: Any) -> None:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    assert install_run.LAST_SWAP_FILENAME == stamp_mod.CODE_SWAP_LAST_SWAP_FILENAME
    assert install_run.last_swap_path_for(sase_home) == stamp_mod._last_code_swap_path()
    assert (
        install_run.last_swap_path_for(sase_home).parent
        == install_run.lock_path_for(sase_home).parent
    )


def test_installer_release_writes_a_stamp_sase_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sase_home = tmp_path / "sase-home"
    before = datetime.now(UTC)
    lock, blocker = install_run.acquire_swap_lock(
        install_run.lock_path_for(sase_home),
        op="install.dev",
        command=["just", "install-dev"],
    )
    assert blocker is None and lock is not None
    assert not install_run.last_swap_path_for(sase_home).exists()
    lock.release()
    lock.release()  # idempotent: one release, one stamp

    swap = _read_sase_stamp(monkeypatch, sase_home)
    assert swap is not None
    assert swap.op == "install.dev"
    assert swap.generation == 1
    assert before <= swap.started_at <= swap.completed_at
    payload = json.loads(install_run.last_swap_path_for(sase_home).read_text())
    assert sorted(payload) == [
        "completed_at",
        "generation",
        "op",
        "pid",
        "started_at",
    ]


def test_installer_and_sase_share_one_generation_counter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    with code_swap_writer_lock() as sase_lock:
        assert sase_lock.acquired is True
    assert stamp_mod.read_last_code_swap() is not None

    lock, _ = install_run.acquire_swap_lock(
        install_run.lock_path_for(sase_home), op="install.pypi"
    )
    assert lock is not None
    lock.release()
    installer_swap = stamp_mod.read_last_code_swap()
    assert installer_swap is not None
    assert (installer_swap.op, installer_swap.generation) == ("install.pypi", 2)

    with code_swap_writer_lock() as sase_lock:
        assert sase_lock.acquired is True
    sase_swap = stamp_mod.read_last_code_swap()
    assert sase_swap is not None
    assert (sase_swap.op, sase_swap.generation) == ("dev.update", 3)


def test_installer_restarts_generation_over_a_corrupt_stamp(tmp_path: Path) -> None:
    path = install_run.last_swap_path_for(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    install_run.record_last_swap(
        path, op="install.pypi", started_at="2026-11-20T00:00:00+00:00"
    )
    assert json.loads(path.read_text())["generation"] == 1


def test_disabled_installer_lock_writes_no_stamp(tmp_path: Path) -> None:
    lock, _ = install_run.acquire_swap_lock(
        install_run.lock_path_for(tmp_path), op="install.pypi", disabled=True
    )
    assert lock is not None
    lock.release()
    assert not install_run.last_swap_path_for(tmp_path).exists()


def test_pypi_run_records_the_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    exit_code, _, _ = harness.run(["pypi", "-y"])
    assert exit_code == 0

    swap = _read_sase_stamp(monkeypatch, harness.sase_home)
    assert swap is not None
    assert swap.op == "install.pypi"


def test_failed_pypi_swap_still_records_the_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed swap may have torn the install, so it still opens the grace."""
    harness = Harness(tmp_path, monkeypatch)
    harness.env["UV_EXIT"] = "1"
    exit_code, _, _ = harness.run(["pypi", "-y"])
    assert exit_code == 1

    swap = _read_sase_stamp(monkeypatch, harness.sase_home)
    assert swap is not None
    assert swap.op == "install.pypi"


def test_dev_run_records_the_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = DevHarness(tmp_path, monkeypatch)
    exit_code, _, _ = harness.run(["dev", "-y"])
    assert exit_code == 0

    swap = _read_sase_stamp(monkeypatch, harness.sase_home)
    assert swap is not None
    assert swap.op == "install.dev"
