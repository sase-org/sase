"""Pre-swap build check tests: fake ``uv``/``maturin``/``cargo`` on PATH."""

from __future__ import annotations

import os
from pathlib import Path

import tests._sase_install_testkit as kit
from tests._sase_install_testkit import install_core


def _fake_bin(tmp_path: Path, name: str, body: str) -> Path:
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    script = bindir / name
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(0o755)
    return bindir


def _core_with_crate(tmp_path: Path) -> Path:
    core = kit.make_core_checkout(tmp_path)
    crate = core / "crates" / "sase_core_py"
    crate.mkdir(parents=True)
    return core


def _env_without_toolchains(tmp_path: Path) -> dict[str, str]:
    env = kit.make_env(tmp_path)
    env["PATH"] = str(tmp_path / "emptybin")
    (tmp_path / "emptybin").mkdir(exist_ok=True)
    return env


def test_maturin_build_pass(tmp_path: Path) -> None:
    core = _core_with_crate(tmp_path)
    bindir = _fake_bin(tmp_path, "uv", "exit 0")
    env = kit.make_env(tmp_path)
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    result = install_core.pre_swap_build_check(
        core, tool_python="/fake/tool/bin/python", env=env
    )
    assert result.ok
    assert result.method == "maturin-build"
    assert result.elapsed >= 0


def test_maturin_build_fail_reports_tail(tmp_path: Path) -> None:
    core = _core_with_crate(tmp_path)
    bindir = _fake_bin(tmp_path, "uv", 'echo "error: broken tree" >&2\nexit 1')
    env = kit.make_env(tmp_path)
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    result = install_core.pre_swap_build_check(
        core, tool_python="/fake/tool/bin/python", env=env
    )
    assert not result.ok
    assert result.method == "maturin-build"
    assert "broken tree" in result.detail


def test_cargo_check_fallback_without_uv(tmp_path: Path) -> None:
    core = _core_with_crate(tmp_path)
    bindir = _fake_bin(tmp_path, "cargo", "exit 0")
    env = kit.make_env(tmp_path)
    env["PATH"] = str(bindir)
    result = install_core.pre_swap_build_check(
        core, tool_python="/fake/tool/bin/python", env=env
    )
    assert result.ok
    assert result.method == "cargo-check"


def test_cargo_check_fail_without_uv(tmp_path: Path) -> None:
    core = _core_with_crate(tmp_path)
    bindir = _fake_bin(tmp_path, "cargo", 'echo "error: type boom" >&2\nexit 101')
    env = kit.make_env(tmp_path)
    env["PATH"] = str(bindir)
    result = install_core.pre_swap_build_check(
        core, tool_python="/fake/tool/bin/python", env=env
    )
    assert not result.ok
    assert result.method == "cargo-check"
    assert "type boom" in result.detail


def test_missing_crate_fails_fast(tmp_path: Path) -> None:
    core = kit.make_core_checkout(tmp_path)
    result = install_core.pre_swap_build_check(
        core, tool_python="/fake/tool/bin/python", env=_env_without_toolchains(tmp_path)
    )
    assert not result.ok
    assert result.method == "none"
    assert "no sase_core_py crate" in result.detail


def test_no_toolchain_fails_with_guidance(tmp_path: Path) -> None:
    core = _core_with_crate(tmp_path)
    result = install_core.pre_swap_build_check(
        core, tool_python="/fake/tool/bin/python", env=_env_without_toolchains(tmp_path)
    )
    assert not result.ok
    assert "need uv or cargo" in result.detail


def _uv_argv_capture(tmp_path: Path) -> tuple[Path, Path]:
    """Return (bindir, capture) with a fake uv that records its argv."""
    capture = tmp_path / "uv-argv.txt"
    bindir = _fake_bin(tmp_path, "uv", 'echo "$@" > "$UV_ARGV_CAPTURE"\nexit 0')
    return bindir, capture


def test_maturin_build_pins_interpreter_when_tool_env_exists(
    tmp_path: Path,
) -> None:
    core = _core_with_crate(tmp_path)
    tool_python = tmp_path / "tool" / "bin" / "python"
    tool_python.parent.mkdir(parents=True)
    tool_python.write_bytes(b"fake")
    bindir, capture = _uv_argv_capture(tmp_path)
    env = kit.make_env(tmp_path)
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    env["UV_ARGV_CAPTURE"] = str(capture)
    result = install_core.pre_swap_build_check(
        core, tool_python=str(tool_python), env=env
    )
    assert result.ok
    argv = capture.read_text(encoding="utf-8")
    assert f"--interpreter {tool_python}" in argv
    assert f"VIRTUAL_ENV={tool_python.parent.parent}" in argv


def test_maturin_build_unpinned_without_tool_env(tmp_path: Path) -> None:
    core = _core_with_crate(tmp_path)
    bindir, capture = _uv_argv_capture(tmp_path)
    env = kit.make_env(tmp_path)
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    env["UV_ARGV_CAPTURE"] = str(capture)
    result = install_core.pre_swap_build_check(
        core, tool_python="/fake/tool/bin/python", env=env
    )
    assert result.ok
    argv = capture.read_text(encoding="utf-8")
    assert "--interpreter" not in argv
    assert "VIRTUAL_ENV=" not in argv
