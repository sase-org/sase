"""Unit tests for ``@<path>`` CLI free-text value resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.cli_file_values import CliFileValueError, read_at_path_value


def test_plain_value_round_trips_unchanged() -> None:
    assert read_at_path_value("hello", target="--description") == "hello"
    assert read_at_path_value("", target="--description") == ""


def test_at_path_returns_exact_bytes_including_trailing_newline(
    tmp_path: Path,
) -> None:
    path = tmp_path / "desc.md"
    path.write_text("line one\nline two\n", encoding="utf-8")

    assert (
        read_at_path_value(f"@{path}", target="--description") == "line one\nline two\n"
    )


def test_at_path_expands_home_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "nested.txt"
    path.write_text("from home\n", encoding="utf-8")

    assert read_at_path_value("@~/nested.txt", target="--description") == "from home\n"


def test_double_at_escapes_a_literal_leading_at() -> None:
    assert read_at_path_value("@@name", target="--description") == "@name"
    assert read_at_path_value("@@@name", target="--description") == "@@name"
    assert read_at_path_value("@", target="--description") == "@"


def test_missing_path_names_target_and_escape(tmp_path: Path) -> None:
    missing = tmp_path / "gone.md"

    with pytest.raises(CliFileValueError, match="file not found") as exc_info:
        read_at_path_value(f"@{missing}", target="--description")

    message = str(exc_info.value)
    assert "--description" in message
    assert "use @@" in message


def test_directory_path_raises_rather_than_returning_literal(tmp_path: Path) -> None:
    with pytest.raises(CliFileValueError):
        read_at_path_value(f"@{tmp_path}", target="--notes")


def test_non_utf8_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "binary.bin"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(CliFileValueError, match="not valid UTF-8"):
        read_at_path_value(f"@{path}", target="--description")
