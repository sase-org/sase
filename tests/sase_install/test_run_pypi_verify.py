"""PyPI-run verify tests (verify gates, update agreement, backup, render).

Split from ``tests.sase_install.test_run_pypi``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tests.sase_install._run_pypi_harness import (
    Harness,
    install_run,
    kit,
    write_exe,
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


def test_verify_failure_blocks_the_install(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.env["FAKE_HEALTH_JSON"] = '{"status": "error", "error": "no rust"}'
    exit_code, out, err = harness.run(["pypi", "-y"])
    assert exit_code == 1
    assert out == ""
    assert "✗ Verify failed" in err
    assert "health" in err
    assert "to restore the previous install, run:" in err


def test_update_disagreement_is_warning_only(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.env["FAKE_UPDATE_JSON"] = '{"mode": "dev"}'
    exit_code, _, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "did not report managed (inconclusive)" in err


def test_mixed_agrees_when_keeping_an_editable_plugin(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    # An unpublished plugin stays editable, so the install receipt is
    # mixed: the update agreement is ok, not an inconclusive warning.
    harness._write_tool_env(plugins=(("bugyi-chops", "editable", "/durable/chops"),))
    harness.lookup = kit.FakePyPI(
        {"sase": "0.17.1", "sase-core-rs": "0.35.4"},
        unpublished=("bugyi-chops",),
    )
    harness.env["FAKE_UPDATE_JSON"] = '{"mode": "mixed"}'
    exit_code, _, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "did not report managed (inconclusive)" not in err


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
    harness = Harness(tmp_path, monkeypatch)
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    write_exe(shadow_dir / "sase", "#!/bin/sh\nexit 0\n")
    harness.env["PATH"] = str(shadow_dir) + os.pathsep + harness.env["PATH"]
    exit_code, _, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "is not the managed install" in err
    assert "left untouched" in err


def test_fresh_install_suggests_missing_plugins(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
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

    harness = Harness(tmp_path, monkeypatch)
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
