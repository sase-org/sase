from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sase.integrations.xprompt_lsp import (
    SASE_XPROMPT_LSP_CMD_ENV,
    _XPromptLspLaunchError,
    _build_xprompt_lsp_argv,
)
from sase.main.parser import create_parser


def test_parser_accepts_lsp_version() -> None:
    args = create_parser().parse_args(["lsp", "--version"])

    assert args.command == "lsp"
    assert args.version is True
    assert args.lsp_args == []


def test_build_lsp_argv_uses_env_override_and_version() -> None:
    args = create_parser().parse_args(["lsp", "--version"])

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


def test_build_lsp_argv_errors_without_command() -> None:
    args = create_parser().parse_args(["lsp"])

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
