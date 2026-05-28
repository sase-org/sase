from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from sase.integrations.xprompt_lsp import (
    SASE_DEFAULT_CONFIG_PATH_ENV,
    SASE_XPROMPT_LSP_CMD_ENV,
    SASE_XPROMPT_BUILTIN_DIR_ENV,
    SASE_XPROMPT_DEFAULT_DIR_ENV,
    SASE_XPROMPT_PACKAGE_DIR_ENV,
    SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV,
    SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV,
    _XPromptLspLaunchError,
    _build_xprompt_lsp_argv,
    _prepare_xprompt_lsp_environment,
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


def test_prepare_lsp_environment_sets_package_catalog_paths(tmp_path: Path) -> None:
    package_dir = tmp_path / "sase"
    env: dict[str, str] = {
        SASE_XPROMPT_BUILTIN_DIR_ENV: "/custom/xprompts",
    }

    _prepare_xprompt_lsp_environment(env, package_dir=package_dir)

    assert env[SASE_XPROMPT_PACKAGE_DIR_ENV] == str(package_dir)
    assert env[SASE_XPROMPT_BUILTIN_DIR_ENV] == "/custom/xprompts"
    assert env[SASE_XPROMPT_DEFAULT_DIR_ENV] == str(package_dir / "default_xprompts")
    assert env[SASE_DEFAULT_CONFIG_PATH_ENV] == str(package_dir / "default_config.yml")


def test_prepare_lsp_environment_emits_plugin_metadata(tmp_path: Path) -> None:
    xprompt_module = ModuleType("fake_plugin.prompts")
    config_module = ModuleType("fake_plugin.config")
    xprompts_dir = tmp_path / "plugin" / "xprompts"
    config_dir = tmp_path / "plugin_config"
    xprompts_dir.mkdir(parents=True)
    config_dir.mkdir()
    config_path = config_dir / "default_config.yml"
    config_path.write_text("xprompts: {}\n", encoding="utf-8")

    def fake_resources_files(module: ModuleType) -> Path:
        if module is xprompt_module:
            return tmp_path / "plugin"
        if module is config_module:
            return config_dir
        raise AssertionError(f"unexpected module {module!r}")

    def fake_discover(group: str) -> list[ModuleType]:
        if group == "sase_xprompts":
            return [xprompt_module]
        if group == "sase_config":
            return [config_module]
        return []

    env: dict[str, str] = {}
    with (
        patch(
            "sase.integrations.xprompt_lsp.discover_plugin_resources",
            side_effect=fake_discover,
        ),
        patch(
            "sase.integrations.xprompt_lsp.importlib.resources.files",
            side_effect=fake_resources_files,
        ),
    ):
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

    assert json.loads(env[SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV]) == [
        {"module": "fake_plugin.prompts", "path": str(xprompts_dir)}
    ]
    assert json.loads(env[SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV]) == [
        {"module": "fake_plugin.config", "path": str(config_path)}
    ]


def test_prepare_lsp_environment_preserves_plugin_metadata_overrides(
    tmp_path: Path,
) -> None:
    env = {
        SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV: '[{"module":"custom","path":"/x"}]',
        SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV: '[{"module":"custom","path":"/c"}]',
    }

    _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV] == (
        '[{"module":"custom","path":"/x"}]'
    )
    assert env[SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV] == (
        '[{"module":"custom","path":"/c"}]'
    )


def test_prepare_lsp_environment_respects_plugin_disable_env(
    tmp_path: Path,
) -> None:
    module = ModuleType("fake_plugin")
    plugin_root = tmp_path / "plugin"
    (plugin_root / "xprompts").mkdir(parents=True)
    (plugin_root / "default_config.yml").write_text("xprompts: {}\n", encoding="utf-8")

    with (
        patch.dict(
            os.environ,
            {
                "SASE_DISABLE_PLUGIN_XPROMPTS": "1",
                "SASE_DISABLE_PLUGIN_CONFIG": "1",
            },
        ),
        patch(
            "sase.integrations.xprompt_lsp.discover_plugin_resources",
            return_value=[module],
        ),
        patch(
            "sase.integrations.xprompt_lsp.importlib.resources.files",
            return_value=plugin_root,
        ),
    ):
        env: dict[str, str] = {}
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

    assert json.loads(env[SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV]) == []
    assert json.loads(env[SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV]) == []


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
