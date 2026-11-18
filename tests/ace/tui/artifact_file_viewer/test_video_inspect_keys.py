"""Video inspect key/input and timestamp-math tests.

Split from ``tests.ace.tui.artifact_file_viewer.test_video_inspect``.
"""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.graphics._viewer_loop_video_common import (
    clamp_timestamp,
    compute_inspect_layout,
    decile_timestamp,
    format_inspect_status,
    snap_timestamp,
    step_timestamp,
)
from sase.ace.tui.graphics._viewer_video_input import (
    _assemble_inspect_key,
    _decode_inspect_key,
)
from sase.ace.tui.graphics.viewer import ArtifactFileImageArea

from ._helpers import TEST_IMAGE_AREA
from ._video_inspect_shared import FakeScrub


def test_decode_inspect_key_maps_arrow_sequences() -> None:
    assert _decode_inspect_key("\x1b[C") == "right"
    assert _decode_inspect_key("\x1b[D") == "left"
    assert _decode_inspect_key("\x1bOC") == "right"
    assert _decode_inspect_key("\x1bOD") == "left"
    assert _decode_inspect_key("l") == "l"


def test_assemble_inspect_key_joins_arrow_bytes_split_across_reads() -> None:
    chunks = [b"\x1b", b"[", b"C"]

    def read_chunk(_timeout: float | None) -> bytes | None:
        return chunks.pop(0) if chunks else None

    assert _assemble_inspect_key(read_chunk, timeout=0.05) == "right"


def test_assemble_inspect_key_times_out_without_input() -> None:
    assert _assemble_inspect_key(lambda _timeout: None, timeout=0.0) is None


def test_assemble_inspect_key_lone_escape_does_not_steal_next_key() -> None:
    chunks = [b"\x1b"]

    def read_chunk(_timeout: float | None) -> bytes | None:
        return chunks.pop(0) if chunks else None

    assert _assemble_inspect_key(read_chunk, timeout=0.05, esc_timeout=0.0) == "\x1b"


def test_step_and_decile_math_clamps_at_both_ends() -> None:
    assert clamp_timestamp(-1.0, 7.0) == 0.0
    assert clamp_timestamp(9.0, 7.0) == 7.0
    assert step_timestamp(0.0, 1.0, 7.0) == 1.0
    assert step_timestamp(0.2, -1.0, 7.0) == 0.0
    assert step_timestamp(6.5, 1.0, 7.0) == 7.0
    assert decile_timestamp(0, 10.0) == 0.0
    assert decile_timestamp(9, 10.0) == 9.0
    assert decile_timestamp(3, None) == 0.0


def testsnap_timestamp_uses_completed_scrub_track(tmp_path: Path) -> None:
    frames = tuple(tmp_path / f"frame-{index:04d}.png" for index in range(8))
    for frame in frames:
        frame.write_bytes(b"PNG")
    scrub = FakeScrub(done=True, fps=1.0, frames=frames)

    assert snap_timestamp(2.4, scrub) == 2.0
    assert step_timestamp(0.0, 2.4, 7.0, scrub=scrub, snap=True) == 2.0


def testformat_inspect_status_includes_bar_and_scrub_progress() -> None:
    line = format_inspect_status(2.0, 7.0, scrub_progress=0.4)
    assert line.startswith("00:02.0 / 00:07.0")
    assert "scrub 40%" in line
    assert ">" in line


def test_storyboard_auto_hides_on_small_panes() -> None:
    small = ArtifactFileImageArea(columns=80, rows=10, top=0)
    hidden = compute_inspect_layout(small, storyboard_enabled=True, pane_rows=12)
    shown = compute_inspect_layout(
        TEST_IMAGE_AREA, storyboard_enabled=True, pane_rows=26
    )

    assert hidden.show_storyboard is False
    assert hidden.storyboard is None
    assert shown.show_storyboard is True
    assert shown.storyboard is not None
    assert shown.storyboard.rows >= 5


def test_read_inspect_key_does_not_flush_queued_keys(monkeypatch) -> None:
    import os
    import pty

    from sase.ace.tui.graphics._viewer_video_input import read_inspect_key

    master, slave = pty.openpty()
    try:
        os.write(master, b"lllll")

        class _FakeStdin:
            def fileno(self) -> int:
                return slave

        monkeypatch.setattr("sys.stdin", _FakeStdin())
        # Each queued byte must be returned by successive reads, not flushed.
        keys = [read_inspect_key(timeout=0.2) for _ in range(5)]
        assert keys == ["l", "l", "l", "l", "l"]
    finally:
        try:
            os.close(master)
        except OSError:
            pass
        try:
            os.close(slave)
        except OSError:
            pass
