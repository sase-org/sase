"""Tests for install-context-aware reinstall remedies."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sase.install_remedy import install_context, reinstall_remedy


def _fs(files: dict[str, str]) -> tuple[Callable[[Path], bool], Callable[[Path], str]]:
    """Build faked ``is_file`` / ``read_text`` probes over an in-memory map."""

    def is_file(path: Path) -> bool:
        return str(path) in files

    def read_text(path: Path) -> str:
        return files[str(path)]

    return is_file, read_text


def _checkout_files(root: str, *, name: str = "sase") -> dict[str, str]:
    return {
        f"{root}/Justfile": "# justfile\n",
        f"{root}/pyproject.toml": f'[project]\nname = "{name}"\n',
    }


def test_install_context_uv_tool_dev() -> None:
    context = install_context(
        sys_prefix="/data/uv/tools/sase",
        tool_dir="/data/uv/tools",
        host_editable=True,
    )
    assert context == "uv_tool_dev"


def test_install_context_uv_tool_release() -> None:
    context = install_context(
        sys_prefix="/data/uv/tools/sase",
        tool_dir="/data/uv/tools",
        host_editable=False,
    )
    assert context == "uv_tool_release"


def test_install_context_checkout_venv() -> None:
    is_file, read_text = _fs(_checkout_files("/repo"))
    context = install_context(
        sys_prefix="/repo/.venv",
        tool_dir="/data/uv/tools",
        host_editable=True,
        is_file=is_file,
        read_text=read_text,
    )
    assert context == "checkout_venv"


def test_install_context_other_without_justfile() -> None:
    files = _checkout_files("/repo")
    del files["/repo/Justfile"]
    is_file, read_text = _fs(files)
    context = install_context(
        sys_prefix="/repo/.venv",
        tool_dir="/data/uv/tools",
        is_file=is_file,
        read_text=read_text,
    )
    assert context == "other"


def test_install_context_other_without_sase_pyproject() -> None:
    is_file, read_text = _fs(_checkout_files("/repo", name="other"))
    context = install_context(
        sys_prefix="/repo/.venv",
        tool_dir="/data/uv/tools",
        is_file=is_file,
        read_text=read_text,
    )
    assert context == "other"


def test_install_context_other_for_plain_prefix() -> None:
    context = install_context(
        sys_prefix="/usr",
        tool_dir="/data/uv/tools",
        host_editable=False,
    )
    assert context == "other"


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        (
            "uv_tool_dev",
            "run `sase update` (or `just install-dev` from your sase checkout)",
        ),
        (
            "uv_tool_release",
            "run `sase update` (or `uv tool install --force sase`)",
        ),
        (
            "other",
            "reinstall sase in this environment "
            "(for example `uv tool install --force sase`)",
        ),
    ],
)
def test_reinstall_remedy_phrases(context: str, expected: str) -> None:
    assert reinstall_remedy(context) == expected  # type: ignore[arg-type]


def test_reinstall_remedy_names_checkout_dir() -> None:
    assert (
        reinstall_remedy("checkout_venv", checkout_dir="/repo")
        == "run `just install-venv` in /repo"
    )


def test_reinstall_remedy_live_detection_returns_phrase() -> None:
    assert isinstance(reinstall_remedy(), str)
    assert reinstall_remedy()


@pytest.mark.parametrize(
    "environ",
    [
        {"UV_TOOL_DIR": "/custom/tools"},
        {"XDG_DATA_HOME": "/data"},
        {},
    ],
)
def test_install_remedy_tool_dir_matches_detect(environ: dict[str, str]) -> None:
    """The local tool-dir rule stays in parity with ``uv_tool.detect``."""
    from sase.install_remedy import _default_uv_tool_dir
    from sase.uv_tool.detect import default_uv_tool_dir

    assert _default_uv_tool_dir(environ) == default_uv_tool_dir(environ)
