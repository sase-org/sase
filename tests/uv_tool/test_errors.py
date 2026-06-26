"""Tests for the renderable uv-tool error messages."""

from __future__ import annotations

from pathlib import Path

from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason
from sase.uv_tool.errors import (
    NotAUvToolInstallError,
    ReceiptError,
    UvCommandFailedError,
    UvNotFoundError,
    UvToolError,
)


def _not_install(reason: NotUvToolReason) -> NotUvToolInstall:
    return NotUvToolInstall(
        reason=reason,
        sys_prefix=Path("/home/u/code/sase/.venv"),
        expected_sase_dir=Path("/t/sase"),
        receipt_path=Path("/t/sase/uv-receipt.toml"),
        uv_path=None,
    )


def test_all_errors_subclass_base() -> None:
    for exc in (
        UvNotFoundError(),
        NotAUvToolInstallError(_not_install(NotUvToolReason.UV_MISSING)),
        UvCommandFailedError(argv=["uv"], returncode=1),
        ReceiptError("bad"),
    ):
        assert isinstance(exc, UvToolError)


def test_uv_not_found_default_message_mentions_install_paths() -> None:
    message = str(UvNotFoundError())
    assert "uv" in message
    assert "uv tool install sase" in message


def test_not_a_uv_tool_install_uv_missing_message() -> None:
    error = NotAUvToolInstallError(_not_install(NotUvToolReason.UV_MISSING))
    assert error.reason is NotUvToolReason.UV_MISSING
    assert "uv" in str(error)


def test_not_a_uv_tool_install_wrong_prefix_names_the_prefix() -> None:
    error = NotAUvToolInstallError(_not_install(NotUvToolReason.WRONG_PREFIX))
    message = str(error)
    assert "/home/u/code/sase/.venv" in message
    assert "uv tool install sase" in message


def test_not_a_uv_tool_install_no_receipt_names_the_path() -> None:
    error = NotAUvToolInstallError(_not_install(NotUvToolReason.NO_RECEIPT))
    assert "/t/sase/uv-receipt.toml" in str(error)


def test_command_failed_nonzero_includes_detail_and_command() -> None:
    error = UvCommandFailedError(
        argv=["uv", "tool", "install", "sase"],
        returncode=2,
        stderr="error: No solution found\nmore noise",
    )
    message = str(error)
    assert "uv tool install sase" in message
    assert "exit 2" in message
    # Only the first non-empty stderr line is surfaced.
    assert "No solution found" in message
    assert "more noise" not in message


def test_command_failed_timeout_message() -> None:
    error = UvCommandFailedError(argv=["uv", "tool", "upgrade", "sase"], timeout=300.0)
    message = str(error)
    assert "timed out" in message
    assert "300s" in message


def test_command_failed_unknown_returncode_renders_question_mark() -> None:
    error = UvCommandFailedError(argv=["uv"], stderr="boom")
    assert "exit ?" in str(error)


def test_command_failed_preserves_fields() -> None:
    error = UvCommandFailedError(argv=["uv", "x"], returncode=1, stderr="e", stdout="o")
    assert error.argv == ("uv", "x")
    assert error.returncode == 1
    assert error.stderr == "e"
    assert error.stdout == "o"
