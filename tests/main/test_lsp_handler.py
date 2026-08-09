"""Command construction and subprocess tests for ``sase lsp``."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sase.integrations.xprompt_lsp import (
    SASE_XPROMPT_LSP_CMD_ENV,
    _XPromptLspLaunchError,
    _build_xprompt_lsp_argv,
)
from sase.main.parser import create_parser


def _point_sys_executable_at_tmp_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    python_name = "python.exe" if os.name == "nt" else "python"
    python = tmp_path / "venv" / bin_dir / python_name
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    monkeypatch.setattr("sase.integrations.xprompt_lsp.sys.executable", str(python))
    return python


def _lsp_binary_name() -> str:
    return "sase-xprompt-lsp.exe" if os.name == "nt" else "sase-xprompt-lsp"


def _write_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    path.chmod(0o755)


def test_parser_accepts_lsp_version() -> None:
    args = create_parser().parse_args(["lsp", "--version"])

    assert args.command == "lsp"
    assert args.version is True
    assert args.lsp_args == []


def test_build_lsp_argv_uses_env_override_and_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    args = create_parser().parse_args(["lsp", "--version"])
    python = _point_sys_executable_at_tmp_venv(monkeypatch, tmp_path)
    _write_executable(python.parent / _lsp_binary_name())

    argv = _build_xprompt_lsp_argv(
        args,
        environ={SASE_XPROMPT_LSP_CMD_ENV: "cargo run -p sase_xprompt_lsp --"},
        which=lambda _name: None,
        repo_root=Path("/missing"),
    )

    assert argv == [
        "cargo",
        "run",
        "-p",
        "sase_xprompt_lsp",
        "--",
        "--version",
    ]


def test_build_lsp_argv_strips_remainder_separator() -> None:
    args = create_parser().parse_args(["lsp", "--", "--probe"])

    argv = _build_xprompt_lsp_argv(
        args,
        environ={SASE_XPROMPT_LSP_CMD_ENV: "sase-xprompt-lsp"},
        which=lambda _name: None,
        repo_root=Path("/missing"),
    )

    assert argv == ["sase-xprompt-lsp", "--probe"]


def test_build_lsp_argv_errors_without_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    args = create_parser().parse_args(["lsp"])
    _point_sys_executable_at_tmp_venv(monkeypatch, tmp_path)

    try:
        _build_xprompt_lsp_argv(
            args,
            environ={},
            which=lambda _name: None,
            repo_root=Path("/missing"),
        )
    except _XPromptLspLaunchError as exc:
        assert "SASE_XPROMPT_LSP_CMD" in str(exc)
    else:
        raise AssertionError("expected XPromptLspLaunchError")


def test_build_lsp_argv_prefers_venv_binary_over_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    args = create_parser().parse_args(["lsp"])
    python = _point_sys_executable_at_tmp_venv(monkeypatch, tmp_path)
    venv_lsp = python.parent / _lsp_binary_name()
    _write_executable(venv_lsp)

    argv = _build_xprompt_lsp_argv(
        args,
        environ={},
        which=lambda _name: "/path/bin/sase-xprompt-lsp",
        repo_root=Path("/missing"),
    )

    assert argv == [str(venv_lsp)]


def test_build_lsp_argv_uses_path_when_venv_binary_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    args = create_parser().parse_args(["lsp"])
    _point_sys_executable_at_tmp_venv(monkeypatch, tmp_path)

    argv = _build_xprompt_lsp_argv(
        args,
        environ={},
        which=lambda _name: "/path/bin/sase-xprompt-lsp",
        repo_root=Path("/missing"),
    )

    assert argv == ["/path/bin/sase-xprompt-lsp"]


def test_build_lsp_argv_uses_newer_release_target_than_debug(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    args = create_parser().parse_args(["lsp"])
    _point_sys_executable_at_tmp_venv(monkeypatch, tmp_path)
    repo_root = tmp_path / "sase"
    repo_root.mkdir()
    sibling_core = tmp_path / "sase-core"
    debug = sibling_core / "target" / "debug" / _lsp_binary_name()
    release = sibling_core / "target" / "release" / _lsp_binary_name()
    _write_executable(debug)
    _write_executable(release)
    os.utime(debug, (100, 100))
    os.utime(release, (200, 200))

    argv = _build_xprompt_lsp_argv(
        args,
        environ={},
        which=lambda _name: None,
        repo_root=repo_root,
    )

    assert argv == [str(release)]


def test_build_lsp_argv_uses_newer_debug_target_than_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    args = create_parser().parse_args(["lsp"])
    _point_sys_executable_at_tmp_venv(monkeypatch, tmp_path)
    repo_root = tmp_path / "sase"
    repo_root.mkdir()
    sibling_core = tmp_path / "sase-core"
    debug = sibling_core / "target" / "debug" / _lsp_binary_name()
    release = sibling_core / "target" / "release" / _lsp_binary_name()
    _write_executable(debug)
    _write_executable(release)
    os.utime(debug, (300, 300))
    os.utime(release, (200, 200))

    argv = _build_xprompt_lsp_argv(
        args,
        environ={},
        which=lambda _name: None,
        repo_root=repo_root,
    )

    assert argv == [str(debug)]


def test_sase_lsp_execs_env_override_in_subprocess(tmp_path: Path) -> None:
    fake_lsp = tmp_path / "fake_lsp.py"
    fake_lsp.write_text(
        "from __future__ import annotations\n"
        "import json\n"
        "import sys\n"
        "print(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    src_path = str(repo_root / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    )
    env[SASE_XPROMPT_LSP_CMD_ENV] = f"{sys.executable} {fake_lsp}"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from sase.main.entry import main; main()",
            "lsp",
            "--version",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == ["--version"]


def test_sase_lsp_subprocess_preserves_version_and_server_args(
    tmp_path: Path,
) -> None:
    fake_lsp = tmp_path / "fake_lsp.py"
    fake_lsp.write_text(
        "from __future__ import annotations\n"
        "import json\n"
        "import sys\n"
        "print(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    src_path = str(repo_root / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    )
    env[SASE_XPROMPT_LSP_CMD_ENV] = f"{sys.executable} {fake_lsp}"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from sase.main.entry import main; main()",
            "lsp",
            "--version",
            "--",
            "--probe",
            "value",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == ["--version", "--probe", "value"]
