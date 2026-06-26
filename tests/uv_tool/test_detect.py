"""Tests for the pure uv-tool detection predicate and its probes."""

from __future__ import annotations

from pathlib import Path

from sase.uv_tool.detect import (
    NotUvToolInstall,
    NotUvToolReason,
    UvToolInstall,
    default_uv_tool_dir,
    detect_uv_tool_install,
    probe_uv_tool_install,
    sase_receipt_path,
)

_TOOL_DIR = "/home/u/.local/share/uv/tools"
_SASE_DIR = f"{_TOOL_DIR}/sase"


def test_detect_success_returns_install_with_paths() -> None:
    result = detect_uv_tool_install(
        which_uv="/usr/bin/uv",
        tool_dir=_TOOL_DIR,
        sys_prefix=_SASE_DIR,
        receipt_exists=True,
    )
    assert isinstance(result, UvToolInstall)
    assert result.uv_path == "/usr/bin/uv"
    assert result.tool_dir == Path(_TOOL_DIR)
    assert result.sase_dir == Path(_SASE_DIR)
    assert result.receipt_path == Path(_SASE_DIR) / "uv-receipt.toml"


def test_detect_uv_missing_takes_precedence() -> None:
    # uv missing wins even when the prefix is wrong and the receipt is absent.
    result = detect_uv_tool_install(
        which_uv=None,
        tool_dir=_TOOL_DIR,
        sys_prefix="/some/dev/.venv",
        receipt_exists=False,
    )
    assert isinstance(result, NotUvToolInstall)
    assert result.reason is NotUvToolReason.UV_MISSING
    assert result.uv_path is None
    assert result.expected_sase_dir == Path(_SASE_DIR)


def test_detect_wrong_prefix_is_a_dev_venv() -> None:
    result = detect_uv_tool_install(
        which_uv="/usr/bin/uv",
        tool_dir=_TOOL_DIR,
        sys_prefix="/home/u/code/sase/.venv",
        receipt_exists=True,
    )
    assert isinstance(result, NotUvToolInstall)
    assert result.reason is NotUvToolReason.WRONG_PREFIX
    assert result.sys_prefix == Path("/home/u/code/sase/.venv")


def test_detect_no_receipt_when_prefix_matches_but_receipt_absent() -> None:
    result = detect_uv_tool_install(
        which_uv="/usr/bin/uv",
        tool_dir=_TOOL_DIR,
        sys_prefix=_SASE_DIR,
        receipt_exists=False,
    )
    assert isinstance(result, NotUvToolInstall)
    assert result.reason is NotUvToolReason.NO_RECEIPT
    assert result.receipt_path == Path(_SASE_DIR) / "uv-receipt.toml"


def test_detect_normalizes_prefix_before_comparing() -> None:
    result = detect_uv_tool_install(
        which_uv="/usr/bin/uv",
        tool_dir=_TOOL_DIR,
        sys_prefix=f"{_TOOL_DIR}/./sase/",
        receipt_exists=True,
    )
    assert isinstance(result, UvToolInstall)


def test_default_uv_tool_dir_prefers_uv_tool_dir_override() -> None:
    env = {"UV_TOOL_DIR": "/custom/tools", "XDG_DATA_HOME": "/xdg"}
    assert default_uv_tool_dir(env) == Path("/custom/tools")


def test_default_uv_tool_dir_uses_xdg_data_home() -> None:
    env = {"XDG_DATA_HOME": "/xdg/data"}
    assert default_uv_tool_dir(env) == Path("/xdg/data/uv/tools")


def test_default_uv_tool_dir_falls_back_to_home(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/home/someone")
    assert default_uv_tool_dir({}) == Path("/home/someone/.local/share/uv/tools")


def test_sase_receipt_path() -> None:
    assert sase_receipt_path("/t") == Path("/t/sase/uv-receipt.toml")


def test_probe_success_uses_injected_environment(tmp_path: Path) -> None:
    tool_dir = tmp_path / "tools"
    receipt = tool_dir / "sase" / "uv-receipt.toml"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('[tool]\nrequirements = [{ name = "sase" }]\n')

    result = probe_uv_tool_install(
        which_fn=lambda _name: "/usr/bin/uv",
        environ={"UV_TOOL_DIR": str(tool_dir)},
        sys_prefix=str(tool_dir / "sase"),
    )
    assert isinstance(result, UvToolInstall)
    assert result.receipt_path == receipt


def test_probe_reports_missing_receipt_when_file_absent(tmp_path: Path) -> None:
    tool_dir = tmp_path / "tools"
    (tool_dir / "sase").mkdir(parents=True)

    result = probe_uv_tool_install(
        which_fn=lambda _name: "/usr/bin/uv",
        environ={"UV_TOOL_DIR": str(tool_dir)},
        sys_prefix=str(tool_dir / "sase"),
    )
    assert isinstance(result, NotUvToolInstall)
    assert result.reason is NotUvToolReason.NO_RECEIPT


def test_probe_reports_uv_missing(tmp_path: Path) -> None:
    result = probe_uv_tool_install(
        which_fn=lambda _name: None,
        environ={"UV_TOOL_DIR": str(tmp_path)},
        sys_prefix=str(tmp_path / "sase"),
    )
    assert isinstance(result, NotUvToolInstall)
    assert result.reason is NotUvToolReason.UV_MISSING
