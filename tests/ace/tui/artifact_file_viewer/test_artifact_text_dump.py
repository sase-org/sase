from __future__ import annotations

from io import StringIO
from pathlib import Path

from sase.ace.tui.graphics.artifact_text_dump import (
    BINARY_FILE_NOTICE,
    _dump_artifact_text,
    main,
)


def test_dump_utf8_document_round_trips(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("alpha\ncaf\u00e9\n", encoding="utf-8")

    assert _dump_artifact_text(artifact) == "alpha\ncaf\u00e9\n"


def test_dump_neutralizes_terminal_control_sequences(tmp_path: Path) -> None:
    artifact = tmp_path / "hostile.txt"
    artifact.write_text(
        "start\x1b]2;owned\x07 mid \x1b[31mred\x1b[0m\rend",
        encoding="utf-8",
    )

    output = _dump_artifact_text(artifact)

    assert "\x1b" not in output
    assert "\x07" not in output
    assert "\\x1b]2;owned\\x07" in output
    assert "red" in output
    assert output.endswith("\nend")


def test_dump_refuses_nul_containing_file(tmp_path: Path) -> None:
    artifact = tmp_path / "binary.bin"
    artifact.write_bytes(b"alpha\x00beta")

    assert _dump_artifact_text(artifact) == BINARY_FILE_NOTICE


def test_dump_refuses_decode_failure_heavy_file(tmp_path: Path) -> None:
    artifact = tmp_path / "invalid.bin"
    artifact.write_bytes(b"\xff" * 100)

    assert _dump_artifact_text(artifact) == BINARY_FILE_NOTICE


def test_dump_truncates_large_file_with_notice(tmp_path: Path) -> None:
    artifact = tmp_path / "large.txt"
    artifact.write_bytes(b"a" * 17)

    output = _dump_artifact_text(artifact, limit_bytes=16)

    assert output.startswith("a" * 16)
    assert "truncated after 16 bytes" in output
    assert "a" * 17 not in output


def test_main_handles_filename_beginning_with_dash(tmp_path: Path) -> None:
    artifact = tmp_path / "-artifact.txt"
    artifact.write_text("dash-name\n", encoding="utf-8")
    stdout = StringIO()
    stderr = StringIO()

    result = main(["--", str(artifact)], stdout=stdout, stderr=stderr)

    assert result == 0
    assert stdout.getvalue() == "dash-name\n"
    assert stderr.getvalue() == ""
