"""PyPI-run flow tests (success, swap argv, overrides, failure, locks).

Split from ``tests.sase_install.test_run_pypi``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from pathlib import Path
from typing import Any

from tests.sase_install._run_pypi_harness import Harness, install_run, kit


def test_pypi_run_success_end_to_end(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    exit_code, out, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert (
        "✓ sase 0.17.1 from PyPI is installed (sase-core-rs 0.35.4 · 0 plugins)" in out
    )
    assert "update later: sase update" in out
    assert "develop on this checkout: just install-dev" in out  # engine-dev landed
    assert "✓ Take the code-swap lock — code-swap writer lock" in err
    assert "✓ Install from PyPI" in err
    assert "✓ Verify the new install" in err
    assert re.search(r"\[\d\d:\d\d\] ✓", err)  # plain append-only progress lines

    swaps = harness.swap_argvs()
    assert len(swaps) == 1
    argv = swaps[0]
    assert argv[:6] == ["tool", "install", "--color", "never", "--force", "--reinstall"]
    assert "sase" in argv

    logs = harness.log_files()
    assert len(logs) == 1
    assert "$ uv tool install" in logs[0].read_text()

    backup = harness.sase_home / "install" / "last-install.json"
    assert backup.is_file()
    payload = json.loads(backup.read_text())
    assert payload["previous_requirements"][0]["name"] == "sase"


def test_swap_argv_pins_existing_interpreter(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    exit_code, _, _ = harness.run(["pypi", "-y"])
    assert exit_code == 0
    argv = harness.swap_argvs()[0]
    python = argv[argv.index("--reinstall") + 1 :]
    # uv recreates the env with its default interpreter instead of keeping
    # the existing one, so the swap pins the env's own python (measured).
    assert python[0] == "--python"
    assert python[1] == str(harness.tool_dir / "bin" / "python")


def test_explicit_python_request_wins_over_pin(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    exit_code, _, _ = harness.run(["pypi", "-y", "--python", "3.13"])
    assert exit_code == 0
    argv = harness.swap_argvs()[0]
    python = argv[argv.index("--reinstall") + 1 :]
    assert python[:2] == ["--python", "3.13"]


def test_overrides_written_only_when_editables_remain(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    # Pure-PyPI run: no overrides file is written.
    assert harness.run(["pypi", "-y"])[0] == 0
    overrides = Path(harness.env["SASE_HOME"]) / "uv" / "editable-overrides.txt"
    assert not overrides.exists()

    # A plugin that stays editable (not published) keeps an -e override.
    harness._write_tool_env(plugins=(("bugyi-chops", "editable", "/durable/chops"),))
    harness.lookup = kit.FakePyPI(
        {"sase": "0.17.1", "sase-core-rs": "0.35.4"},
        unpublished=("bugyi-chops",),
    )
    (tmp_path / "durable-chops").mkdir(exist_ok=True)
    assert harness.run(["pypi", "-y"])[0] == 0
    assert "-e /durable/chops" in overrides.read_text()
    argv = harness.swap_argvs()[-1]
    assert "--overrides" in argv


def test_swap_failure_prints_restore_command(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness._write_tool_env(
        host=("editable", str(harness.checkout)),
        core=("pypi", "0.35.4"),
    )
    harness.env["UV_EXIT"] = "1"
    exit_code, out, err = harness.run(["pypi", "-y"])
    assert exit_code == 1
    assert out == ""
    assert "✗ Swap failed" in err
    assert "log:" in err
    assert "to restore the previous install, run:" in err
    assert "--editable" in err  # previous host was editable: restore keeps it
    assert " uv tool install " in err
    assert "--overrides None" not in err
    assert "rolled back" not in err  # never claim a rollback that did not happen


def test_lock_contention_times_out_naming_holder(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    lock_path = harness.sase_home / "locks" / "code-swap-v2.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "pid": 4242,
                "op": "dev.update",
                "command": ["sase", "dev", "update"],
                "started_at": "2026-10-09T00:00:00+00:00",
                "blocking": True,
            }
        ),
        encoding="utf-8",
    )
    holder_fd = os.open(lock_path, os.O_RDWR)
    try:
        fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        exit_code, _, err = harness.run(["pypi", "-y"], lock_timeout=1.0)
    finally:
        try:
            fcntl.flock(holder_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(holder_fd)
    assert exit_code == 1
    assert "Lock failed" in err
    assert "sase dev update (pid 4242)" in err
    assert harness.swap_argvs() == []  # the swap never ran
    assert "to restore the previous install" not in err  # nothing changed yet


def test_lock_path_and_holder_match_sase(tmp_path: Path, monkeypatch: Any) -> None:
    from sase.dev_update import code_swap_lock as sase_lock

    harness = Harness(tmp_path, monkeypatch)
    monkeypatch.setenv("SASE_HOME", str(harness.sase_home))
    assert install_run.LOCK_FILENAME == sase_lock.CODE_SWAP_LOCK_FILENAME
    assert (
        install_run.lock_path_for(harness.sase_home) == sase_lock.code_swap_lock_path()
    )
    assert install_run.holders_dir_for(harness.sase_home) == sase_lock._holders_dir()
    shared = {
        "pid": 7,
        "op": "dev.update",
        "command": ["sase", "dev", "update"],
        "started_at": "2026-10-09T00:00:00+00:00",
        "blocking": True,
    }
    assert install_run.format_holder(shared) == sase_lock._format_holder(shared)
    assert (
        install_run.format_holder({**shared, "op": "install.pypi"})
        == "just install (pid 7); running `sase dev update`; "
        "started 2026-10-09T00:00:00+00:00"
    )


def test_advisory_runners_warn_but_do_not_block(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    holders = harness.sase_home / "locks" / "code-swap.holders"
    holders.mkdir(parents=True, exist_ok=True)
    (holders / f"{os.getpid()}.advisory.json").write_text(
        json.dumps({"pid": os.getpid(), "op": "agent.runner", "blocking": False}),
        encoding="utf-8",
    )
    (holders / "999999999.advisory.json").write_text(
        json.dumps({"pid": 999999999, "op": "agent.runner", "blocking": False}),
        encoding="utf-8",
    )
    assert install_run.count_live_advisory_runners(harness.sase_home) == 1
    assert not (holders / "999999999.advisory.json").exists()  # dead files reap

    exit_code, _, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "1 agent runner(s) are running from this install" in err
