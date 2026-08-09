"""Regression tests for bounded completed hook-output captures."""

from __future__ import annotations

from pathlib import Path

from sase.ace.patch import Patch, HookEntry, HookStatusLine
from sase.ace.hooks import execution
from sase.ace.hooks.output_capture import compact_completed_hook_output
from sase.config import metahook


def test_small_completed_capture_is_byte_for_byte_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "small.txt"
    content = b"head\n===HOOK_COMPLETE=== END_TIMESTAMP: 260720_120000 EXIT_CODE: 0\n"
    path.write_bytes(content)

    assert not compact_completed_hook_output(path, content)
    assert path.read_bytes() == content


def test_large_capture_preserves_head_elision_marker_and_tail(tmp_path: Path) -> None:
    path = tmp_path / "large.txt"
    content = (
        b"HEAD-DIAGNOSTIC\n"
        + b"m" * 500
        + b"\n===HOOK_COMPLETE=== END_TIMESTAMP: 260720_120000 EXIT_CODE: 0\n"
        + b"42 passed, 1 warning in 12.34s\n"
    )
    path.write_bytes(content)

    assert compact_completed_hook_output(path, content, head_bytes=64, tail_bytes=128)

    compacted = path.read_bytes()
    assert compacted.startswith(b"HEAD-DIAGNOSTIC")
    assert b"SASE HOOK OUTPUT ELIDED" in compacted
    assert b"bytes omitted" in compacted
    assert b"===HOOK_COMPLETE===" in compacted
    assert compacted.endswith(b"42 passed, 1 warning in 12.34s\n")
    assert not compact_completed_hook_output(
        path,
        compacted,
        head_bytes=64,
        tail_bytes=128,
    )
    assert path.read_bytes() == compacted


def test_running_capture_without_completion_marker_is_untouched(tmp_path: Path) -> None:
    path = tmp_path / "running.txt"
    content = b"still running\n" + b"x" * 1000
    path.write_bytes(content)

    assert not compact_completed_hook_output(
        path, content, head_bytes=10, tail_bytes=10
    )
    assert path.read_bytes() == content


def test_completion_path_compacts_only_after_parsing_full_capture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "hook.txt"
    content = (
        b"important head\n"
        + b"x" * (600 * 1024)
        + b"\n===HOOK_COMPLETE=== END_TIMESTAMP: 260720_120000 EXIT_CODE: 0\n"
        + b"pytest summary: 120 passed\n"
    )
    path.write_bytes(content)
    monkeypatch.setattr(execution, "get_hook_output_path", lambda *_: str(path))
    status = HookStatusLine(
        commit_entry_num="1",
        timestamp="260720_120000",
        status="RUNNING",
    )
    hook = HookEntry(command="just test", status_lines=[status])
    patch = Patch(
        name="test",
        description="test",
        parent=None,
        status="Ready",
        hooks=[hook],
    )

    completed = execution.check_hook_completion(patch, hook)

    assert completed is not None
    assert completed.status_lines is not None
    assert completed.status_lines[0].status == "PASSED"
    compacted = path.read_bytes()
    assert len(compacted) < len(content)
    assert b"===HOOK_COMPLETE===" in compacted
    assert compacted.endswith(b"pytest summary: 120 passed\n")


def test_metahook_matches_full_output_before_completed_capture_is_compacted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "failed-hook.txt"
    full_only_match = b"MATCH-ONLY-IN-ELIDED-MIDDLE"
    content = (
        b"head\n"
        + b"x" * (300 * 1024)
        + full_only_match
        + b"y" * (400 * 1024)
        + b"\n===HOOK_COMPLETE=== END_TIMESTAMP: 260720_120000 EXIT_CODE: 1\n"
    )
    path.write_bytes(content)
    monkeypatch.setattr(execution, "get_hook_output_path", lambda *_: str(path))
    seen: list[str] = []

    def match_full_output(command: str, output: str) -> bool:
        seen.append(command)
        assert full_only_match.decode() in output
        return True

    monkeypatch.setattr(metahook, "find_matching_metahook", match_full_output)
    status = HookStatusLine(
        commit_entry_num="1",
        timestamp="260720_120000",
        status="RUNNING",
    )
    hook = HookEntry(command="!just test", status_lines=[status])
    patch = Patch(
        name="test",
        description="test",
        parent=None,
        status="Ready",
        hooks=[hook],
    )

    completed = execution.check_hook_completion(patch, hook)

    assert completed is not None
    assert completed.status_lines is not None
    assert completed.status_lines[0].status == "FAILED"
    assert completed.status_lines[0].suffix is None
    assert seen == ["!just test"]
    compacted = path.read_bytes()
    assert full_only_match not in compacted
    assert b"===HOOK_COMPLETE===" in compacted
