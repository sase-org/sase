"""PyPI execution pipeline: hermetic end-to-end runs plus unit coverage.

Every test here runs the real entry point with fake ``uv``/``sase``/``python``
executables on ``PATH`` and temporary ``HOME``, ``SASE_HOME``,
``UV_TOOL_DIR``, and ``UV_TOOL_BIN_DIR`` — no network, no real tool
environment, and no prompt is ever answered by a human. Covered: step
sequencing and swap argv, exit codes, lock contention, scheduler-restart
branches, failure output with the restore command, plain-renderer output,
quiet and JSON modes, and repeat-run no-op.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

import tests._sase_install_testkit as kit
from tests._sase_install_testkit import install_run


FAKE_UV = """\
#!/usr/bin/env python3
import json as _j, os as _o, sys as _s
_a = _s.argv[1:]
if _a == ["--version"]:
    print("uv 0.12.10")
elif _a == ["tool", "dir"]:
    print(_o.environ["UV_TOOL_DIR"])
elif _a == ["tool", "dir", "--bin"]:
    print(_o.environ["UV_TOOL_BIN_DIR"])
elif _a[:2] == ["tool", "install"]:
    _c = _o.environ.get("UV_CAPTURE")
    if _c:
        with open(_c, "a", encoding="utf-8") as _f:
            _f.write(_j.dumps(_a) + "\\n")
    _rc = int(_o.environ.get("UV_EXIT", "0"))
    _m = _o.environ.get("HEALTH_MARKER")
    if _rc == 0 and _m:
        import pathlib as _p
        _p.Path(_m).touch()
    _s.exit(_rc)
else:
    print("unexpected uv args: %r" % (_a,), file=_s.stderr)
    _s.exit(2)
"""

FAKE_SASE = """\
#!/usr/bin/env python3
import json as _j, os as _o, sys as _s, time as _t
_a = _s.argv[1:]
if _a == ["core", "health", "-j"]:
    import pathlib as _p
    _m = _o.environ.get("HEALTH_MARKER")
    if _m and _p.Path(_m).exists():
        print('{"status": "ok"}')
        _s.exit(0)
    print(_o.environ.get("FAKE_HEALTH_JSON", '{"status": "ok"}'))
    _s.exit(int(_o.environ.get("FAKE_HEALTH_EXIT", "0")))
if _a == ["version", "-j"]:
    print(_o.environ["FAKE_VERSION_JSON"])
    _s.exit(int(_o.environ.get("FAKE_VERSION_EXIT", "0")))
if _a == ["update", "-n", "-j"]:
    print(_o.environ.get("FAKE_UPDATE_JSON", '{"mode": "managed"}'))
    _s.exit(int(_o.environ.get("FAKE_UPDATE_EXIT", "0")))
if _a == ["scheduler", "restart"]:
    _c = _o.environ.get("SASE_CAPTURE")
    if _c:
        with open(_c, "a", encoding="utf-8") as _f:
            _f.write("scheduler-restart\\n")
    _s.exit(int(_o.environ.get("FAKE_RESTART_EXIT", "0")))
print("unexpected sase args: %r" % (_a,), file=_s.stderr)
_s.exit(2)
"""

FAKE_TOOL_PYTHON = """\
#!/usr/bin/env python3
import json as _j, os as _o, sys as _s
if _o.environ.get("FAKE_PYTHON_FAIL"):
    print("fake tool python is broken", file=_s.stderr)
    _s.exit(1)
_site = _o.environ["FAKE_SITE_PACKAGES"]
_missing = set(_o.environ.get("FAKE_MISSING_PLUGINS", "").split())
_script = _s.argv[_s.argv.index("-c") + 1]
_rest = _s.argv[_s.argv.index("-c") + 2:]
if "importlib" in _script:
    print(_j.dumps({n: (None if n in _missing else "9.9.9") for n in _rest}))
else:
    print(_j.dumps(_site + "/" + _rest[0].replace("_", "-") + "/__init__.py"))
"""


def _write_exe(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class Harness:
    """One hermetic install world: fakes, tool env, and env mapping."""

    def __init__(self, tmp_path: Path, monkeypatch: Any) -> None:
        self.root = tmp_path
        self.fakes = tmp_path / "fakes"
        self.fakes.mkdir()
        _write_exe(self.fakes / "uv", FAKE_UV)
        self.tool_root = tmp_path / "tools"
        self.bin_root = tmp_path / "bin"
        self.bin_root.mkdir(parents=True)
        self.sase_home = tmp_path / "sase-home"
        self.env = kit.make_env(tmp_path)
        self.env["PATH"] = str(self.fakes) + os.pathsep + self.env["PATH"]
        self.env["UV_TOOL_DIR"] = str(self.tool_root)
        self.env["UV_TOOL_BIN_DIR"] = str(self.bin_root)
        self.env["UV_CAPTURE"] = str(tmp_path / "uv-capture.jsonl")
        self.env["SASE_CAPTURE"] = str(tmp_path / "sase-capture.txt")
        self.checkout = kit.make_checkout(tmp_path)
        self.lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.35.4"})
        self.tool_dir = self.tool_root / "sase"
        self._write_tool_env()
        self._write_version_json("0.17.1")

    def _write_tool_env(
        self,
        *,
        host: tuple[str, str | None] | None = ("pypi", "0.17.0"),
        core: tuple[str, str | None] | None = ("pypi", "0.35.4"),
        plugins: tuple[tuple[str, str, str | None], ...] = (),
        with_receipt: bool = True,
        python_version: str = "3.14.7",
    ) -> None:
        if self.tool_dir.exists():
            import shutil

            shutil.rmtree(self.tool_dir)
        bin_dir = self.tool_dir / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        _write_exe(bin_dir / "python", FAKE_TOOL_PYTHON)
        site = self.tool_dir / "lib" / "python3.14" / "site-packages"
        site.mkdir(parents=True, exist_ok=True)
        self.env["FAKE_SITE_PACKAGES"] = str(site)
        self.tool_dir.joinpath("pyvenv.cfg").write_text(
            "home = /fake/bin\nversion_info = "
            f"{python_version}\ninclude-system-site-packages = false\n",
            encoding="utf-8",
        )
        entries: list[dict[str, str]] = []
        if host is not None:
            kind, value = host
            if kind == "editable":
                entries.append({"name": "sase", "editable": str(value)})
                kit.write_dist(site, "sase", "0.17.1", editable=str(value))
            else:
                entries.append({"name": "sase", "specifier": f"=={value}"})
                kit.write_dist(site, "sase", value or "0.17.1")
        for plugin_name, source, target in plugins:
            if source == "editable":
                assert target is not None
                entries.append({"name": plugin_name, "editable": target})
                kit.write_dist(site, plugin_name, "0.4.2", editable=target)
            else:
                entries.append({"name": plugin_name, "specifier": ">=0.1"})
                kit.write_dist(site, plugin_name, target or "0.4.2")
        if core is not None:
            kind, value = core
            if kind == "editable":
                assert value is not None
                kit.write_dist(site, "sase-core-rs", "0.37.0", editable=value)
            else:
                kit.write_dist(site, "sase-core-rs", value or "0.37.0")
        if with_receipt:
            kit.write_receipt(self.tool_dir, entries)
        _write_exe(self.bin_root / "sase", FAKE_SASE)

    def _write_version_json(self, host_version: str) -> None:
        self.env["FAKE_VERSION_JSON"] = json.dumps(
            {
                "schema_version": 1,
                "packages": [
                    {
                        "name": "sase",
                        "role": "host",
                        "install_type": "wheel",
                        "distribution_version": host_version,
                    },
                    {"name": "sase-core-rs", "role": "core"},
                ],
            }
        )

    def run(self, args: list[str], **kwargs: Any) -> tuple[int, str, str]:
        """Run the real entry point against this harness (no path overrides).

        ``tool_dir``/``bin_dir`` are deliberately *not* passed: the entry
        point resolves them through the fake ``uv`` on ``PATH``, exactly like
        production.
        """
        entry = kit.load_entry()
        return kit.run_entry(
            entry,
            args,
            env=self.env,
            pypi_lookup=self.lookup,
            checkout_root=self.checkout,
            **kwargs,
        )

    def swap_argvs(self) -> list[list[str]]:
        capture = Path(self.env["UV_CAPTURE"])
        if not capture.exists():
            return []
        return [json.loads(line) for line in capture.read_text().splitlines()]

    def log_files(self) -> list[Path]:
        log_dir = self.sase_home / "logs" / "install"
        if not log_dir.is_dir():
            return []
        return sorted(log_dir.glob("install-*.log"))


def _harness(tmp_path: Path, monkeypatch: Any) -> Harness:
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    return Harness(tmp_path, monkeypatch)


def test_pypi_run_success_end_to_end(tmp_path: Path, monkeypatch: Any) -> None:
    harness = _harness(tmp_path, monkeypatch)
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
    harness = _harness(tmp_path, monkeypatch)
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
    harness = _harness(tmp_path, monkeypatch)
    exit_code, _, _ = harness.run(["pypi", "-y", "--python", "3.13"])
    assert exit_code == 0
    argv = harness.swap_argvs()[0]
    python = argv[argv.index("--reinstall") + 1 :]
    assert python[:2] == ["--python", "3.13"]


def test_overrides_written_only_when_editables_remain(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = _harness(tmp_path, monkeypatch)
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
    harness = _harness(tmp_path, monkeypatch)
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
    harness = _harness(tmp_path, monkeypatch)
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

    harness = _harness(tmp_path, monkeypatch)
    monkeypatch.setenv("SASE_HOME", str(harness.sase_home))
    assert install_run.LOCK_FILENAME == sase_lock.CODE_SWAP_LOCK_FILENAME
    assert install_run.lock_path_for(harness.sase_home) == sase_lock._lock_path()
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
    harness = _harness(tmp_path, monkeypatch)
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


def test_scheduler_restart_runs_when_scheduler_is_live(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = _harness(tmp_path, monkeypatch)
    axe_dir = harness.sase_home / "axe"
    axe_dir.mkdir(parents=True, exist_ok=True)
    (axe_dir / "orchestrator.pid").write_text(str(os.getpid()), encoding="utf-8")
    assert install_run.scheduler_running(harness.sase_home) is True

    exit_code, _, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "✓ Restart the scheduler — scheduler restarted" in err
    capture = Path(harness.env["SASE_CAPTURE"])
    assert capture.is_file() and "scheduler-restart" in capture.read_text()


def test_scheduler_restart_skipped_when_idle(tmp_path: Path, monkeypatch: Any) -> None:
    harness = _harness(tmp_path, monkeypatch)
    assert install_run.scheduler_running(harness.sase_home) is False
    exit_code, _, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "scheduler was not running" in err
    assert not Path(harness.env["SASE_CAPTURE"]).exists()


def test_scheduler_restart_failure_warns_without_failing(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = _harness(tmp_path, monkeypatch)
    axe_dir = harness.sase_home / "axe"
    axe_dir.mkdir(parents=True, exist_ok=True)
    (axe_dir / "orchestrator.pid").write_text(str(os.getpid()), encoding="utf-8")
    harness.env["FAKE_RESTART_EXIT"] = "1"
    exit_code, _, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "scheduler restart failed" in err


def test_quiet_prints_only_the_summary(tmp_path: Path, monkeypatch: Any) -> None:
    harness = _harness(tmp_path, monkeypatch)
    exit_code, out, err = harness.run(["pypi", "-y", "-q"])
    assert exit_code == 0
    assert err == ""
    assert len(out.splitlines()) == 1
    assert out.startswith("just install: ")


def test_json_reports_success_with_log_path(tmp_path: Path, monkeypatch: Any) -> None:
    harness = _harness(tmp_path, monkeypatch)
    exit_code, out, err = harness.run(["pypi", "-y", "-j"])
    assert exit_code == 0
    assert err == ""
    doc = json.loads(out)
    assert doc["schema_version"] == 1
    assert doc["dry_run"] is False
    assert doc["outcome"] == "success"
    assert doc["log_path"].endswith(".log")
    assert Path(doc["log_path"]).is_file()
    assert doc["steps"] == [
        "preflight",
        "plan",
        "confirm",
        "lock",
        "swap",
        "verify",
        "restart",
        "summary",
    ]


def test_json_reports_failure_with_error(tmp_path: Path, monkeypatch: Any) -> None:
    harness = _harness(tmp_path, monkeypatch)
    harness.env["UV_EXIT"] = "3"
    exit_code, out, err = harness.run(["pypi", "-y", "-j"])
    assert exit_code == 1
    doc = json.loads(out)
    assert doc["outcome"] == "failed"
    assert "Swap" in (doc["error"] or "")
    assert doc["log_path"].endswith(".log")
    assert "✗ Swap failed" in err


def test_noop_when_current_and_healthy(tmp_path: Path, monkeypatch: Any) -> None:
    harness = _harness(tmp_path, monkeypatch)
    harness._write_tool_env(host=("pypi", "0.17.1"), core=("pypi", "0.35.4"))
    exit_code, out, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert (
        "✓ sase 0.17.1 from PyPI is already installed — nothing to do "
        "(--force reinstalls)" in out
    )
    assert harness.swap_argvs() == []  # no swap ran
    assert harness.log_files() != []  # the run is still logged


def test_noop_skipped_when_health_fails(tmp_path: Path, monkeypatch: Any) -> None:
    harness = _harness(tmp_path, monkeypatch)
    harness._write_tool_env(host=("pypi", "0.17.1"), core=("pypi", "0.35.4"))
    harness.env["FAKE_HEALTH_EXIT"] = "1"
    # The reinstall heals the install: the fake uv drops this marker on a
    # successful swap, and the fake sase answers healthy once it exists.
    harness.env["HEALTH_MARKER"] = str(tmp_path / "health-marker")
    exit_code, out, _ = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "is installed" in out  # full pipeline ran instead of the no-op
    assert len(harness.swap_argvs()) == 1


def test_force_reinstalls_when_current(tmp_path: Path, monkeypatch: Any) -> None:
    harness = _harness(tmp_path, monkeypatch)
    harness._write_tool_env(host=("pypi", "0.17.1"), core=("pypi", "0.35.4"))
    exit_code, _, _ = harness.run(["pypi", "-y", "--force"])
    assert exit_code == 0
    assert len(harness.swap_argvs()) == 1


def test_verify_failure_blocks_the_install(tmp_path: Path, monkeypatch: Any) -> None:
    harness = _harness(tmp_path, monkeypatch)
    harness.env["FAKE_HEALTH_JSON"] = '{"status": "error", "error": "no rust"}'
    exit_code, out, err = harness.run(["pypi", "-y"])
    assert exit_code == 1
    assert out == ""
    assert "✗ Verify failed" in err
    assert "health" in err
    assert "to restore the previous install, run:" in err


def test_update_disagreement_is_warning_only(tmp_path: Path, monkeypatch: Any) -> None:
    harness = _harness(tmp_path, monkeypatch)
    harness.env["FAKE_UPDATE_JSON"] = '{"mode": "dev"}'
    exit_code, _, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "did not report managed (inconclusive)" in err


def test_update_timeout_is_warning_only() -> None:
    def _hang(argv: object, **kwargs: object) -> Any:
        return install_run.RunnerResult(
            returncode=124, stdout="", stderr="", timed_out=True
        )

    checks = install_run.verify_pypi_install(
        plan=_pypi_plan(),
        state=_pypi_state(),
        tool_dir="/tmp/tool",
        sase_exe="/tmp/tool/bin/sase",
        tool_python="/tmp/tool/bin/python",
        env={},
        run=_hang,
    )
    by_name = {check.name: check for check in checks}
    assert by_name["update-agreement"].warning_only is True
    assert "inconclusive" in by_name["update-agreement"].detail
    assert any(not check.ok and not check.warning_only for check in checks)


def test_path_shadow_is_warning_only(tmp_path: Path, monkeypatch: Any) -> None:
    harness = _harness(tmp_path, monkeypatch)
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    _write_exe(shadow_dir / "sase", "#!/bin/sh\nexit 0\n")
    harness.env["PATH"] = str(shadow_dir) + os.pathsep + harness.env["PATH"]
    exit_code, _, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "is not the managed install" in err
    assert "left untouched" in err


def test_fresh_install_suggests_missing_plugins(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = _harness(tmp_path, monkeypatch)
    harness._write_tool_env(host=None, core=None, with_receipt=False)
    harness.env["FAKE_MISSING_PLUGINS"] = "sase-github"
    exit_code, out, _ = harness.run(["pypi", "-y", "--with", "sase-github"])
    assert exit_code == 0
    assert "Next: sase plugin install sase-github" in out


def test_missing_plugin_probe_error_prints_nothing() -> None:
    def _boom(argv: object, **kwargs: object) -> Any:
        raise OSError("no interpreter")

    assert (
        install_run.missing_plugin_names(
            ["sase-github"],
            tool_python="/tmp/tool/bin/python",
            env={},
            run=_boom,
        )
        == []
    )


def _pypi_plan() -> Any:
    from tests._sase_install_testkit import install_plan

    return install_plan.InstallPlan(
        mode="pypi",
        command="just install",
        rows=(),
        python=install_plan.PythonPlan(current=None, target=None),
        target_dir="/tmp/tool",
        current_mode="none",
        consequential=False,
        noop=False,
        warnings=(),
        swap_argv=("uv", "tool", "install"),
        overrides_lines=(),
        overrides_path=None,
        checkout_root="/tmp/checkout",
        core_dir="/tmp/sase-core",
    )


def _pypi_state() -> Any:
    from tests._sase_install_testkit import install_state

    return install_state.InstallState(
        tool_dir=Path("/tmp/tool"), bin_dir=Path("/tmp/tool/bin"), env_exists=False
    )


def test_swap_argv_for_fresh_env_takes_uv_default() -> None:
    plan = _pypi_plan()
    assert install_run.swap_argv_for(plan, env_exists=False) == [
        "uv",
        "tool",
        "install",
    ]


def test_backup_restore_names_editable_rebuild(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from tests._sase_install_testkit import install_state

    harness = _harness(tmp_path, monkeypatch)
    harness._write_tool_env(
        host=("editable", str(harness.checkout)),
        core=("editable", "/durable/core"),
    )
    state = install_state.read_state(
        tool_dir=harness.tool_dir, bin_dir=harness.tool_dir / "bin"
    )
    backup = install_run.write_backup(
        tmp_path / "last-install.json", state=state, env=harness.env
    )
    assert "--editable" in backup.restore_command
    assert "--overrides" in backup.restore_command
    assert backup.restore_command.endswith("&& just rust-dev-install-uv-tool")
    assert backup.previous_core_editable is True
    payload = json.loads(backup.path.read_text())
    assert payload["restore_argv"] == backup.restore_argv


def test_progress_plain_quiet_and_live() -> None:
    import io

    from tests._sase_install_testkit import install_ui

    clock = iter([100.0, 100.9])
    plain_out = io.StringIO()
    progress = install_ui.Progress(plain_out, mode="plain", clock=lambda: next(clock))
    progress.start("swap", "Install from PyPI")
    progress.finish("ok", "done")
    assert plain_out.getvalue() == "[00:00] ✓ Install from PyPI — done (0.9s)\n"

    quiet_out = io.StringIO()
    quiet = install_ui.Progress(quiet_out, mode="quiet")
    quiet.start("swap", "Install from PyPI")
    quiet.warn("hidden")
    quiet.finish("ok", "done")
    assert quiet_out.getvalue() == ""

    live_out = io.StringIO()
    live = install_ui.Progress(live_out, mode="live")
    live.start("swap", "Install from PyPI")
    live.tick("halfway")
    live.finish("ok", "done")
    rendered = live_out.getvalue().replace("\r", "\n")
    assert "Install from PyPI" in rendered
    assert "✓" in rendered and "(0.0s)" in rendered

    assert install_ui.format_duration(0.4) == "0.4s"
    assert install_ui.format_duration(62.0) == "1:02"
    assert install_ui.render_pypi_success(_pypi_plan()) == (
        "✓ sase from PyPI is installed (sase-core-rs · 0 plugins)\n"
        "  update later: sase update · develop on this checkout: just install-dev"
    )
