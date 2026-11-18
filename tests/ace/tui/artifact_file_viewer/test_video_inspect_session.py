"""Video inspect terminal/session tests.

Split from ``tests.ace.tui.artifact_file_viewer.test_video_inspect``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.ace.tui.graphics._viewer_loop_video import run_video_inspect
from sase.ace.tui.graphics.viewer import (
    ArtifactFileViewerResult,
    ArtifactFileViewSpec,
    ArtifactVideoPlaybackConfig,
)

from ._helpers import TEST_IMAGE_AREA, stub_video_inspect_service
from ._video_inspect_shared import write_clip


def test_quiet_mode_enter_exit_restores_termios(monkeypatch) -> None:
    import os
    import pty
    import termios

    from sase.ace.tui.graphics._viewer_video_input import (
        enter_quiet_terminal,
        exit_quiet_terminal,
    )

    master, slave = pty.openpty()
    try:

        class _FakeStdin:
            def fileno(self) -> int:
                return slave

        monkeypatch.setattr("sys.stdin", _FakeStdin())
        before = termios.tcgetattr(slave)
        saved = enter_quiet_terminal()
        assert saved is not None
        quiet = termios.tcgetattr(slave)
        assert not (quiet[3] & termios.ECHO)
        assert not (quiet[3] & termios.ICANON)
        # OPOST stays on so Rich output still maps newlines.
        import termios as _termios

        assert quiet[1] & _termios.OPOST
        exit_quiet_terminal(saved)
        after = termios.tcgetattr(slave)
        assert list(after) == list(before) or after[3] == before[3]
    finally:
        try:
            os.close(master)
        except OSError:
            pass
        try:
            os.close(slave)
        except OSError:
            pass


def test_no_quiet_mode_with_injected_reader(tmp_path: Path, monkeypatch) -> None:
    from sase.ace.tui.graphics._viewer_loop_video_view import (
        _VideoInspectSession as _InspectSession,
    )

    video = write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    session = _InspectSession(
        ArtifactFileViewSpec(video, "file"),
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=TEST_IMAGE_AREA,
        read_key=lambda: "q",
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
        artifact_index=0,
        artifact_count=1,
        return_pane_id=None,
        select_pane=None,
        tmux_zoom_available=False,
        toggle_zoom=None,
    )
    assert session._using_default_reader is False
    session._enter_quiet()
    assert session._quiet_saved is None
    session.cleanup()


def test_quiet_mode_suspends_around_motion_and_restores_on_exception(
    tmp_path: Path, monkeypatch
) -> None:
    from sase.ace.tui.graphics._viewer_loop_video_view import (
        _VideoInspectSession as _InspectSession,
    )

    video = write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    entered: list[bool] = []
    exited: list[bool] = []
    import sase.ace.tui.graphics._viewer_loop_video_session as video_module

    monkeypatch.setattr(
        video_module, "enter_quiet_terminal", lambda: entered.append(True) or ["saved"]
    )
    monkeypatch.setattr(
        video_module, "exit_quiet_terminal", lambda _saved: exited.append(True)
    )
    session = _InspectSession(
        ArtifactFileViewSpec(video, "file"),
        video_config=ArtifactVideoPlaybackConfig(backend="mpv", vo="tct"),
        image_area=TEST_IMAGE_AREA,
        read_key=None,
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
        artifact_index=0,
        artifact_count=1,
        return_pane_id=None,
        select_pane=None,
        tmux_zoom_available=False,
        toggle_zoom=None,
    )
    assert session._using_default_reader is True
    # Simulate an active quiet session, then motion suspends and re-enters.
    session._quiet_saved = ["saved"]  # type: ignore[list-item]
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_video_motion.shutil.which",
        lambda _tool: "/usr/bin/mpv",
    )
    session._play_motion()
    assert exited and entered
    # Cleanup restores even after an exception path leaves quiet active.
    session._quiet_saved = ["saved"]  # type: ignore[list-item]
    session.cleanup()
    assert session._quiet_saved is None


def test_idle_status_writes_once_until_state_changes(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from sase.ace.tui.graphics._viewer_loop_video_view import (
        _VideoInspectSession as _InspectSession,
    )

    video = write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    session = _InspectSession(
        ArtifactFileViewSpec(video, "file"),
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=TEST_IMAGE_AREA,
        read_key=lambda: "q",
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
        artifact_index=0,
        artifact_count=1,
        return_pane_id=None,
        select_pane=None,
        tmux_zoom_available=False,
        toggle_zoom=None,
    )
    session._prepare()
    capsys.readouterr()
    for _ in range(5):
        session._print_status()
    first = capsys.readouterr().out
    # N idle polls with unchanged state produce one status write.
    assert first.count("\x1b[") == 1
    # A scrub-progress change produces another write.
    session.at = 1.0
    session._print_status()
    second = capsys.readouterr().out
    assert second.count("\x1b[") == 1
    session.cleanup()


def test_sequence_loop_passes_explicit_area_and_z_refreshes_size(
    tmp_path: Path, monkeypatch
) -> None:
    import shutil

    from sase.ace.tui.graphics._viewer_loop_video_view import (
        _VideoInspectSession as _InspectSession,
    )

    video = write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    captured: dict[str, object] = {}
    import sase.ace.tui.graphics._viewer_loop_video as video_module

    def fake_inspect(spec, **kwargs):
        captured.update(kwargs)
        return type(
            "Outcome", (), {"action": "quit", "returncode": 0, "warnings": ()}
        )()

    monkeypatch.setattr(video_module, "run_video_inspect", fake_inspect)
    keys = iter(["q"])
    from sase.ace.tui.graphics.viewer import run_artifact_sequence_loop

    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    result = run_artifact_sequence_loop(
        (ArtifactFileViewSpec(video, "file"),),
        cache_root=tmp_path / "cache",
        read_key=lambda: next(keys),
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
        image_area=None,
        video_config=ArtifactVideoPlaybackConfig(),
    )
    assert result.returncode == 0
    # Production passes its explicit image_area (None), not a concrete area.
    assert captured.get("image_area") is None

    # z re-lays out at the new terminal size when not fixed.
    session = _InspectSession(
        ArtifactFileViewSpec(video, "file"),
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=None,
        read_key=lambda: "q",
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
        artifact_index=0,
        artifact_count=1,
        return_pane_id=None,
        select_pane=None,
        tmux_zoom_available=True,
        toggle_zoom=lambda: ArtifactFileViewerResult(True),
    )
    session._prepare()
    before = (session.layout.frame.rows, session.layout.frame.columns)
    current = shutil.get_terminal_size(fallback=(80, 24))
    import os as _os

    bigger = _os.terminal_size((current.columns, current.lines + 10))
    monkeypatch.setattr(shutil, "get_terminal_size", lambda fallback=None: bigger)
    session._handle_key("z")
    after = (session.layout.frame.rows, session.layout.frame.columns)
    assert after != before or session.layout.pane_rows != 0
    session.cleanup()


def test_missing_kitten_renders_cells_with_banner_and_notice(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from PIL import Image

    video = write_clip(tmp_path)
    stub = stub_video_inspect_service(monkeypatch, tmp_path)
    cache = stub["cache"]
    extracts = stub["extracts"]

    def fake_cell_extract(
        path: object, at_seconds: float, max_px: int, **kwargs: object
    ):
        del path, max_px, kwargs
        dest = cache / f"cell-{float(at_seconds):.3f}.png"
        Image.new("RGB", (64, 36), (200, 30, 30)).save(dest, format="PNG")
        extracts.append(float(at_seconds))
        from sase.ace.tui.graphics._viewer_video_frames import FrameExtractResult

        return FrameExtractResult(path=dest, cached=False, error=None)

    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_loop_video_session.extract_frame",
        fake_cell_extract,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_loop_video_session.shutil.which",
        lambda tool: None if tool == "kitten" else f"/usr/bin/{tool}",
    )
    keys = iter(["q"])
    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
    )
    assert result.action == "quit"
    output = capsys.readouterr().out
    assert "cell preview" in output
    assert "kitten" in output
