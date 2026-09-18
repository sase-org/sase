"""Justfile wiring for TUI screenshot maintenance."""

from __future__ import annotations

from pathlib import Path
import subprocess

from tests.test_justfile_lint import (
    ROOT,
    _clean_sase_core_env,
    _copy_justfile,
    _dry_run,
)


def _install_visual_spy_python(root: Path) -> None:
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        """#!/bin/sh
{
  printf 'BEGIN\\n'
  printf 'SASE_JUST_INVOCATION_DIR=%s\\n' "${SASE_JUST_INVOCATION_DIR-}"
  for arg in "$@"; do
    printf 'ARG=%s\\n' "$arg"
  done
  printf 'END\\n'
} >> "$JUST_SPY_FILE"
for arg in "$@"; do
  if [ "$arg" = "tools/fix_tui_screenshots" ]; then
    exit "${JUST_SPY_EXIT:-0}"
  fi
done
exit 0
""",
        encoding="utf-8",
    )
    python.chmod(0o755)


def _run_visual_recipe(
    root: Path,
    recipe: str,
    *recipe_args: str,
    spy_exit: str = "0",
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    calls = root / "calls.log"
    env = _clean_sase_core_env() | {
        "JUST_SPY_FILE": str(calls),
        "JUST_SPY_EXIT": spy_exit,
    }
    command = [
        "just",
        "--justfile",
        str(root / "Justfile"),
        "--set",
        "venv_dir",
        ".venv",
        "--set",
        "sase_core_dir",
        str(root / "sase-core"),
        "--",
        recipe,
        *recipe_args,
    ]
    return subprocess.run(
        command,
        cwd=cwd or root,
        env=env,
        capture_output=True,
        text=True,
    )


def _last_spy_block(root: Path) -> list[str]:
    text = (root / "calls.log").read_text(encoding="utf-8")
    blocks = text.split("BEGIN\n")
    assert len(blocks) > 1, text
    last = blocks[-1]
    end = last.find("END\n")
    assert end != -1, last
    return [line for line in last[:end].splitlines() if line]


def test_test_visual_contention_keeps_the_governed_visual_runner() -> None:
    output = _dry_run("test-visual-contention")

    assert "tools/run_pytest visual" in output
    assert "tools/fix_tui_screenshots" not in output


def test_visual_fixture_modules_do_not_honor_the_retired_update_flag() -> None:
    for relative in (
        "tests/ace/tui/visual/conftest.py",
        "tests/pager/visual/conftest.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert 'getoption("--sase-update-visual-snapshots")' not in source
        assert "update=False" in source


def test_fix_tui_screenshots_forwards_check_flag_and_selectors(
    tmp_path: Path,
) -> None:
    _copy_justfile(tmp_path)
    _install_visual_spy_python(tmp_path)

    result = _run_visual_recipe(
        tmp_path,
        "fix-tui-screenshots",
        "--check",
        "--",
        "tests/ace/tui/visual/test_example.py",
        "-k",
        "example",
    )

    assert result.returncode == 0, result.stderr
    args = _last_spy_block(tmp_path)
    assert "ARG=tools/fix_tui_screenshots" in args
    assert "ARG=--check" in args
    assert "ARG=tests/ace/tui/visual/test_example.py" in args
    assert "ARG=-k" in args
    assert "ARG=example" in args
    assert any(
        line.startswith("SASE_JUST_INVOCATION_DIR=") and line.endswith(str(tmp_path))
        for line in args
    )


def test_test_visual_alias_routes_to_check_mode(tmp_path: Path) -> None:
    _copy_justfile(tmp_path)
    _install_visual_spy_python(tmp_path)

    result = _run_visual_recipe(
        tmp_path,
        "test-visual",
        "--",
        "tests/pager/visual/test_example.py",
    )

    assert result.returncode == 0, result.stderr
    args = _last_spy_block(tmp_path)
    assert args.count("ARG=--check") == 1
    assert args[args.index("ARG=tools/fix_tui_screenshots") + 1] == "ARG=--check"
    assert "ARG=tests/pager/visual/test_example.py" in args


def test_update_visual_snapshots_alias_routes_to_update_mode(
    tmp_path: Path,
) -> None:
    _copy_justfile(tmp_path)
    _install_visual_spy_python(tmp_path)

    result = _run_visual_recipe(tmp_path, "update-visual-snapshots")

    assert result.returncode == 0, result.stderr
    args = _last_spy_block(tmp_path)
    assert "ARG=tools/fix_tui_screenshots" in args
    assert "ARG=--check" not in args


def test_fix_tui_screenshots_preserves_invocation_directory(
    tmp_path: Path,
) -> None:
    _copy_justfile(tmp_path)
    _install_visual_spy_python(tmp_path)
    subdir = tmp_path / "subdir"
    subdir.mkdir()

    result = _run_visual_recipe(
        tmp_path,
        "fix-tui-screenshots",
        "--check",
        cwd=subdir,
    )

    assert result.returncode == 0, result.stderr
    args = _last_spy_block(tmp_path)
    assert f"SASE_JUST_INVOCATION_DIR={subdir}" in args


def test_fix_tui_screenshots_propagates_tool_exit_code(tmp_path: Path) -> None:
    _copy_justfile(tmp_path)
    _install_visual_spy_python(tmp_path)

    result = _run_visual_recipe(tmp_path, "fix-tui-screenshots", spy_exit="3")

    assert result.returncode != 0, result.stdout + result.stderr
    assert result.returncode in {1, 3}
    args = _last_spy_block(tmp_path)
    assert "ARG=tools/fix_tui_screenshots" in args
