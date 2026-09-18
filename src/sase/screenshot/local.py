"""Local ``sase screenshot`` orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from typing import Any, Protocol, cast

from sase.ace.tui.screenshot_export import screenshot_request_dir
from sase.core.paths import get_sase_managed_tmpdir
from sase.core.time import generate_timestamp
from sase.main import ace_tmux

DEFAULT_COLS = 120
DEFAULT_ROWS = 40
DEFAULT_SETTLE_MS = 0
DEFAULT_TIMEOUT_SECONDS = 60.0
SCREENSHOT_CONTRACT_SCHEMA_VERSION = 1

_SCREEN_RESULT_RE = re.compile(r"^screen_(\d+)\.(done|error)$")
_SCREEN_SVG_RE = re.compile(r"^screen_(\d+)\.svg$")
_TRANSIENT_EXPORT_ERRORS = (
    "Node must be running before calling wait_for_refresh",
    "timed out before requesting screenshot refresh",
    "timed out waiting for screenshot refresh",
    "timed out waiting for screenshot refresh acknowledgement",
    "timed out waiting for screenshot frame convergence",
    "startup-visible:",
)
_EXPORT_RETRY_DELAY_SECONDS = 0.25
_STARTUP_STABLE_FRAME_COUNT = 2
_DEBUG_CAPTURE_TIMEOUT_SECONDS = 0.5


class CommandRunner(Protocol):
    """Command runner seam for tests and future remote transports."""

    def run(
        self,
        cmd: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        """Run *cmd* and return its completed process."""


class _SubprocessRunner:
    """Production command runner using :func:`subprocess.run`."""

    def run(
        self,
        cmd: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return cast(
            subprocess.CompletedProcess[str], subprocess.run(list(cmd), **kwargs)
        )


@dataclass(frozen=True)
class ScreenshotOptions:
    """User-selected local screenshot capture settings."""

    output: Path | None
    size: tuple[int, int]
    presses: tuple[str, ...]
    wait_for: tuple[str, ...]
    settle_ms: int
    svg_only: bool
    keep: bool
    window: str | None
    timeout: float
    tui_args: tuple[str, ...]


@dataclass(frozen=True)
class _ScreenshotResult:
    """Paths and tmux target details for a completed capture."""

    svg: Path
    png: Path | None
    screenshot_dir: Path
    tmux_session: str
    tmux_window: str
    tmux_target: str
    tmux_pid: int
    created_window: bool
    kept_window: bool


@dataclass(frozen=True)
class _InspectedTmuxWindow:
    """Tmux target details for a supplied or newly-created screenshot window."""

    session: str
    window_name: str
    target: str
    pane_pid: int
    request_dir: Path


class ScreenshotCaptureError(RuntimeError):
    """Raised when the local screenshot pipeline cannot complete."""


def capture_local_screenshot(
    options: ScreenshotOptions,
    *,
    runner: CommandRunner | None = None,
) -> _ScreenshotResult:
    """Launch or reuse a local tmux TUI and capture a PNG or SVG screenshot."""
    active_runner = runner or _SubprocessRunner()
    deadline = _Deadline(options.timeout)
    created_window = False
    window_name: str
    session: str
    pane_pid: int
    request_dir: Path
    target = ""

    try:
        if options.window:
            inspected = _inspect_tmux_window(
                options.window,
                runner=active_runner,
                deadline=deadline,
            )
            session = inspected.session
            window_name = inspected.window_name
            pane_pid = inspected.pane_pid
            request_dir = inspected.request_dir
            target = inspected.target
        else:
            relaunch_cmd = _build_tui_relaunch_cmd(options.tui_args)
            cols, rows = options.size
            try:
                window = ace_tmux.create_agent_tmux_window(
                    relaunch_cmd,
                    cols=cols,
                    rows=rows,
                    extra_env=_tui_env_pins(),
                    runner=active_runner.run,
                    timeout=lambda: deadline.remaining,
                )
            except ace_tmux.TmuxLaunchError as exc:
                raise ScreenshotCaptureError(str(exc)) from exc
            session = window.session
            window_name = window.window_name
            pane_pid = window.pane_pid
            request_dir = Path(window.screenshot_dir)
            target = window.target
            created_window = True

        last_capture = _wait_for_startup_frame(
            target,
            runner=active_runner,
            deadline=deadline,
        )
        for key in options.presses:
            _run_tmux(
                ["tmux", "send-keys", "-t", target, key],
                runner=active_runner,
                deadline=deadline,
                action=f"send key {key!r} to {target}",
            )
        for pattern in options.wait_for:
            last_capture = _wait_for_capture_match(
                target,
                pattern,
                runner=active_runner,
                deadline=deadline,
                last_capture=last_capture,
            )
        if options.settle_ms > 0:
            deadline.sleep(options.settle_ms / 1000)

        svg_path = _request_export_with_retries(
            request_dir,
            pane_pid=pane_pid,
            target=target,
            runner=active_runner,
            deadline=deadline,
            last_capture=last_capture,
        )
        output_svg = _copy_svg_if_requested(svg_path, options)
        png_path = (
            None
            if options.svg_only
            else render_png_from_svg_file(svg_path, options.output)
        )
        return _ScreenshotResult(
            svg=output_svg,
            png=png_path,
            screenshot_dir=request_dir,
            tmux_session=session,
            tmux_window=window_name,
            tmux_target=target,
            tmux_pid=pane_pid,
            created_window=created_window,
            kept_window=bool(options.window) or options.keep,
        )
    finally:
        if created_window and not options.keep:
            _kill_window_best_effort(target, runner=active_runner)
            ace_tmux.release_tmux_window_claim(request_dir)


def _build_tui_relaunch_cmd(tui_args: Sequence[str]) -> str:
    forwarded = _normalize_tui_args(tui_args)
    argv = [
        sys.executable,
        "-m",
        "sase",
        "tui",
        "-x",
        "-r",
        "0",
        *forwarded,
    ]
    return "exec " + shlex.join(argv)


def _normalize_tui_args(tui_args: Sequence[str]) -> list[str]:
    args = list(tui_args)
    if args[:1] == ["--"]:
        return args[1:]
    return args


def _tui_env_pins() -> dict[str, str]:
    return {
        "COLORTERM": "truecolor",
        "TERM": "xterm-256color",
        "TEXTUAL_ANIMATIONS": "none",
    }


def _inspect_tmux_window(
    target: str,
    *,
    runner: CommandRunner,
    deadline: _Deadline,
) -> _InspectedTmuxWindow:
    result = _run_tmux(
        [
            "tmux",
            "display-message",
            "-p",
            "-t",
            target,
            "#{session_name}\t#{window_id}\t#{window_name}\t#{pane_pid}\t#{@sase_screenshot_dir}",
        ],
        runner=runner,
        deadline=deadline,
        action=f"inspect tmux window {target}",
    )
    fields = result.stdout.rstrip("\n").split("\t")
    if len(fields) != 5 or not fields[0] or not fields[2]:
        raise ScreenshotCaptureError(
            f"tmux did not report session, window, and pane pid for {target!r}"
        )
    try:
        pane_pid = int(fields[3])
    except ValueError as exc:
        raise ScreenshotCaptureError(
            f"tmux returned non-integer pane pid for {target!r}: {fields[3]!r}"
        ) from exc
    session = fields[0]
    window_id = fields[1]
    window_name = fields[2]
    request_dir = (
        Path(fields[4]).expanduser()
        if fields[4]
        else screenshot_request_dir(session, window_name)
    )
    return _InspectedTmuxWindow(
        session=session,
        window_name=window_name,
        target=window_id if window_id.startswith("@") else target,
        pane_pid=pane_pid,
        request_dir=request_dir,
    )


def _wait_for_startup_frame(
    target: str,
    *,
    runner: CommandRunner,
    deadline: _Deadline,
) -> str:
    last = ""
    last_nonblank = ""
    stable_frames = 0
    while True:
        try:
            text = _capture_pane(target, runner=runner, deadline=deadline)
        except ScreenshotCaptureError as exc:
            raise ScreenshotCaptureError(
                str(exc) + _debug_suffix(last_nonblank or last)
            ) from exc
        if text.strip():
            stable_frames = stable_frames + 1 if text == last else 1
            last = text
            last_nonblank = text
            if stable_frames >= _STARTUP_STABLE_FRAME_COUNT:
                return text
        else:
            stable_frames = 0
            last = text
        if deadline.expired:
            raise ScreenshotCaptureError(
                "timed out waiting for the TUI to paint a non-blank frame"
                + _debug_suffix(last_nonblank or last)
            )
        deadline.sleep(0.05)


def _wait_for_capture_match(
    target: str,
    pattern: str,
    *,
    runner: CommandRunner,
    deadline: _Deadline,
    last_capture: str,
) -> str:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ScreenshotCaptureError(
            f"invalid --wait-for regex {pattern!r}: {exc}"
        ) from exc

    capture = last_capture
    last_nonblank = capture if capture.strip() else ""
    while True:
        try:
            capture = _capture_pane(target, runner=runner, deadline=deadline)
        except ScreenshotCaptureError as exc:
            raise ScreenshotCaptureError(
                str(exc) + _debug_suffix(last_nonblank or capture)
            ) from exc
        if capture.strip():
            last_nonblank = capture
        if regex.search(capture):
            return capture
        if deadline.expired:
            raise ScreenshotCaptureError(
                f"timed out waiting for tmux screen to match {pattern!r}"
                + _debug_suffix(last_nonblank or capture)
            )
        deadline.sleep(0.05)


def _capture_pane(
    target: str,
    *,
    runner: CommandRunner,
    deadline: _Deadline,
) -> str:
    result = _run_tmux(
        ["tmux", "capture-pane", "-p", "-t", target],
        runner=runner,
        deadline=deadline,
        action=f"capture tmux pane {target}",
    )
    return result.stdout


def _request_export_with_retries(
    request_dir: Path,
    *,
    pane_pid: int,
    target: str,
    runner: CommandRunner,
    deadline: _Deadline,
    last_capture: str,
) -> Path:
    capture = last_capture
    last_attempt_error: _ExportMarkerError | None = None
    while True:
        if deadline.expired and last_attempt_error is not None:
            raise ScreenshotCaptureError(
                _overall_export_timeout_message(last_attempt_error, capture)
            ) from last_attempt_error
        before_sequence = _highest_sequence(request_dir)
        _run_tmux(
            ["kill", f"-{_signal_name()}", str(pane_pid)],
            runner=runner,
            deadline=deadline,
            action=f"signal TUI process {pane_pid}",
        )
        try:
            return _wait_for_export(
                request_dir,
                after_sequence=before_sequence,
                target=target,
                runner=runner,
                deadline=deadline,
                last_capture=capture,
            )
        except _ExportMarkerError as exc:
            if not _is_transient_export_error(exc.message):
                raise ScreenshotCaptureError(str(exc)) from exc
            last_attempt_error = exc
            capture = exc.capture
            if deadline.expired:
                raise ScreenshotCaptureError(
                    _overall_export_timeout_message(exc, capture)
                ) from exc
            deadline.sleep(_EXPORT_RETRY_DELAY_SECONDS)


def _wait_for_export(
    request_dir: Path,
    *,
    after_sequence: int,
    target: str,
    runner: CommandRunner,
    deadline: _Deadline,
    last_capture: str,
) -> Path:
    capture = last_capture
    while True:
        result = _next_export_result(request_dir, after_sequence=after_sequence)
        if result is not None:
            sequence, kind, marker = result
            if kind == "error":
                message = marker.read_text(encoding="utf-8").strip()
                capture = _capture_pane_for_debug(
                    target,
                    runner=runner,
                    deadline=deadline,
                    fallback=capture,
                )
                raise _ExportMarkerError(message or "unknown error", capture)
            svg = marker.with_suffix(".svg")
            if not svg.exists():
                raise ScreenshotCaptureError(
                    f"TUI screenshot export completed without screen_{sequence}.svg"
                )
            return svg
        if deadline.expired:
            capture = _capture_pane_for_debug(
                target,
                runner=runner,
                deadline=deadline,
                fallback=capture,
            )
            raise ScreenshotCaptureError(
                "timed out waiting for TUI screenshot export" + _debug_suffix(capture)
            )
        deadline.sleep(0.05)


def _capture_pane_for_debug(
    target: str,
    *,
    runner: CommandRunner,
    deadline: _Deadline,
    fallback: str,
) -> str:
    try:
        capture_deadline = (
            _Deadline(_DEBUG_CAPTURE_TIMEOUT_SECONDS) if deadline.expired else deadline
        )
        return _capture_pane(target, runner=runner, deadline=capture_deadline)
    except ScreenshotCaptureError:
        return fallback


def _next_export_result(
    request_dir: Path,
    *,
    after_sequence: int,
) -> tuple[int, str, Path] | None:
    if not request_dir.exists():
        return None
    matches: list[tuple[int, str, Path]] = []
    for child in request_dir.iterdir():
        match = _SCREEN_RESULT_RE.match(child.name)
        if match is None:
            continue
        sequence = int(match.group(1))
        if sequence > after_sequence:
            matches.append((sequence, match.group(2), child))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    return matches[0]


def _highest_sequence(request_dir: Path) -> int:
    if not request_dir.exists():
        return 0
    highest = 0
    for child in request_dir.iterdir():
        match = _SCREEN_RESULT_RE.match(child.name) or _SCREEN_SVG_RE.match(child.name)
        if match is not None:
            highest = max(highest, int(match.group(1)))
    return highest


def _is_transient_export_error(message: str) -> bool:
    return any(fragment in message for fragment in _TRANSIENT_EXPORT_ERRORS)


def _overall_export_timeout_message(
    error: _ExportMarkerError,
    capture: str,
) -> str:
    return (
        "timed out waiting for TUI screenshot readiness within the overall "
        "capture deadline; last export attempt failed with: "
        f"{error.message}" + _debug_suffix(capture)
    )


def _copy_svg_if_requested(svg_path: Path, options: ScreenshotOptions) -> Path:
    if not options.svg_only:
        return svg_path
    output = _output_path(options.output, suffix=".svg")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg_path.read_text(encoding="utf-8"), encoding="utf-8")
    return output


def render_png_from_svg_file(svg_path: Path, output: Path | None) -> Path:
    """Rasterize one SVG file into a PNG output path."""
    from sase.ace.tui.visual_render import render_svg_to_png

    png_path = _output_path(output, suffix=".png")
    svg = svg_path.read_text(encoding="utf-8")
    try:
        png = render_svg_to_png(svg)
    except RuntimeError as exc:
        raise ScreenshotCaptureError(str(exc)) from exc
    png_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.write_bytes(png)
    return png_path


def _output_path(output: Path | None, *, suffix: str) -> Path:
    if output is not None:
        return output.expanduser()
    directory = Path(get_sase_managed_tmpdir("screenshots"))
    return directory / f"sase_tui_{generate_timestamp()}{suffix}"


def _run_tmux(
    cmd: Sequence[str],
    *,
    runner: CommandRunner,
    deadline: _Deadline,
    action: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner.run(
            list(cmd),
            capture_output=True,
            text=True,
            check=False,
            timeout=deadline.remaining,
        )
    except subprocess.TimeoutExpired as exc:
        raise ScreenshotCaptureError(f"timed out while trying to {action}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ScreenshotCaptureError(
            f"failed to {action}" + (f": {detail}" if detail else "")
        )
    return result


def _kill_window_best_effort(target: str, *, runner: CommandRunner) -> None:
    try:
        runner.run(
            ["tmux", "kill-window", "-t", target],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return


def _signal_name() -> str:
    if not hasattr(signal, "SIGUSR2"):
        raise ScreenshotCaptureError("SIGUSR2 is not available on this platform")
    return "USR2"


def _debug_suffix(capture: str) -> str:
    text = capture.rstrip()
    if not text:
        return "\n\nLast tmux capture-pane output was blank."
    return "\n\nLast tmux capture-pane output:\n" + text


class _Deadline:
    """Small monotonic deadline helper shared across tmux polling loops."""

    def __init__(self, seconds: float) -> None:
        self._deadline = time.monotonic() + seconds

    @property
    def remaining(self) -> float:
        return max(0.001, self._deadline - time.monotonic())

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self._deadline

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        time.sleep(min(seconds, self.remaining))


class _ExportMarkerError(ScreenshotCaptureError):
    """Raised when the TUI wrote ``screen_N.error`` for a screenshot request."""

    def __init__(self, message: str, capture: str) -> None:
        self.message = message
        self.capture = capture
        super().__init__(
            f"TUI screenshot export failed: {message}" + _debug_suffix(capture)
        )


__all__ = [
    "DEFAULT_COLS",
    "DEFAULT_ROWS",
    "DEFAULT_SETTLE_MS",
    "DEFAULT_TIMEOUT_SECONDS",
    "SCREENSHOT_CONTRACT_SCHEMA_VERSION",
    "CommandRunner",
    "ScreenshotCaptureError",
    "ScreenshotOptions",
    "capture_local_screenshot",
    "render_png_from_svg_file",
]
