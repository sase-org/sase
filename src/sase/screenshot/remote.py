"""Remote ``sase screenshot`` orchestration over SSH."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import shlex
import subprocess
import time
from collections.abc import Mapping, Sequence
from typing import Any, cast
from uuid import uuid4

from sase.core.paths import get_sase_managed_tmpdir
from sase.core.time import generate_timestamp
from sase.dispatch.ssh_target import RemoteSshTarget, resolve_remote_ssh_target
from sase.screenshot.local import (
    SCREENSHOT_CONTRACT_SCHEMA_VERSION,
    CommandRunner,
    ScreenshotCaptureError,
    ScreenshotOptions,
    render_png_from_svg_file,
)

_REMOTE_BASE = "/tmp"
_SSH_CONNECT_TIMEOUT_SECONDS = 5
_SSH_OPERATION_TIMEOUT_SECONDS = 10.0
_REMOTE_CAPTURE_TIMEOUT_OVERHEAD_SECONDS = 10.0


@dataclass(frozen=True)
class _RemoteScreenshotResult:
    """Paths, target details, and remote version facts for a capture."""

    svg: Path
    png: Path | None
    host: str
    remote_sase_version: str
    screenshot_dir: str
    tmux_session: str
    tmux_window: str
    tmux_target: str
    tmux_pid: int
    kept_window: bool

    @property
    def send_keys_hint(self) -> str:
        """Return a shell command template for driving a kept remote window."""
        return _remote_send_keys_hint(self.host, self.tmux_target)


@dataclass(frozen=True)
class _RemoteScreenshotMetadata:
    """Parsed key/value contract from the remote screenshot command."""

    screenshot_dir: str
    tmux_session: str
    tmux_window: str
    tmux_target: str
    tmux_pid: int


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


def capture_remote_screenshot(
    host: str,
    options: ScreenshotOptions,
    *,
    runner: CommandRunner | None = None,
) -> _RemoteScreenshotResult:
    """Capture a screenshot on ``host`` over SSH and rasterize it locally."""
    active_runner = runner or _SubprocessRunner()
    deadline = _Deadline(options.timeout + _REMOTE_CAPTURE_TIMEOUT_OVERHEAD_SECONDS)
    try:
        target = resolve_remote_ssh_target(host)
    except ValueError as exc:
        raise ScreenshotCaptureError(str(exc)) from exc

    _probe_contract(target, runner=active_runner, deadline=deadline)
    remote_svg = _remote_svg_path()
    local_svg = _output_path(
        options.output if options.svg_only else None, suffix=".svg"
    )
    metadata: _RemoteScreenshotMetadata | None = None
    try:
        metadata = _run_remote_svg_capture(
            target,
            remote_svg,
            options,
            runner=active_runner,
            deadline=deadline,
        )
        svg = _fetch_remote_svg(
            target,
            remote_svg,
            runner=active_runner,
            deadline=deadline,
        )
        local_svg.parent.mkdir(parents=True, exist_ok=True)
        local_svg.write_text(svg, encoding="utf-8")
        remote_version = _remote_sase_version(
            target,
            runner=active_runner,
            deadline=deadline,
        )
        png_path = (
            None
            if options.svg_only
            else render_png_from_svg_file(local_svg, options.output)
        )
        return _RemoteScreenshotResult(
            svg=local_svg,
            png=png_path,
            host=target.host,
            remote_sase_version=remote_version,
            screenshot_dir=metadata.screenshot_dir,
            tmux_session=metadata.tmux_session,
            tmux_window=metadata.tmux_window,
            tmux_target=metadata.tmux_target,
            tmux_pid=metadata.tmux_pid,
            kept_window=options.keep or bool(options.window),
        )
    finally:
        _cleanup_remote_svg(target, remote_svg, runner=active_runner)


def _probe_contract(
    target: RemoteSshTarget,
    *,
    runner: CommandRunner,
    deadline: _Deadline,
) -> None:
    completed = _run_ssh(
        target,
        ["sase", "screenshot", "--contract"],
        runner=runner,
        deadline=deadline,
        action="probe remote screenshot contract",
    )
    if completed.returncode != 0:
        raise ScreenshotCaptureError(_upgrade_message(target.host))
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ScreenshotCaptureError(_upgrade_message(target.host)) from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != (
        SCREENSHOT_CONTRACT_SCHEMA_VERSION
    ):
        raise ScreenshotCaptureError(_upgrade_message(target.host))


def _run_remote_svg_capture(
    target: RemoteSshTarget,
    remote_svg: str,
    options: ScreenshotOptions,
    *,
    runner: CommandRunner,
    deadline: _Deadline,
) -> _RemoteScreenshotMetadata:
    argv = _remote_screenshot_argv(remote_svg, options)
    completed = _run_ssh(
        target,
        argv,
        runner=runner,
        deadline=deadline,
        operation_timeout=None,
        action="run remote screenshot capture",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ScreenshotCaptureError(
            f"remote screenshot capture on {target.host!r} failed"
            + (f": {detail}" if detail else "")
        )
    return _parse_remote_metadata(completed.stdout, host=target.host)


def _remote_screenshot_argv(remote_svg: str, options: ScreenshotOptions) -> list[str]:
    cols, rows = options.size
    argv = [
        "sase",
        "screenshot",
        "--svg",
        "-o",
        remote_svg,
        "-s",
        f"{cols}x{rows}",
        "-t",
        f"{options.timeout:g}",
    ]
    if options.settle_ms:
        argv.extend(("-d", str(options.settle_ms)))
    if options.keep:
        argv.append("-k")
    if options.window:
        argv.extend(("-W", options.window))
    for key in options.presses:
        argv.extend(("-p", key))
    for pattern in options.wait_for:
        argv.extend(("-w", pattern))
    argv.extend(options.tui_args)
    return argv


def _parse_remote_metadata(stdout: str, *, host: str) -> _RemoteScreenshotMetadata:
    values: dict[str, str] = {}
    for line in stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    missing = [
        key
        for key in (
            "sase_screenshot_dir",
            "sase_tmux_session",
            "sase_tmux_window",
            "sase_tmux_target",
            "sase_tmux_pid",
        )
        if not values.get(key)
    ]
    if missing:
        hint = (
            "; remote sase is missing retained tmux target support; upgrade it"
            if "sase_tmux_target" in missing
            else ""
        )
        raise ScreenshotCaptureError(
            f"remote screenshot capture on {host!r} returned an incomplete contract: "
            + ", ".join(missing)
            + hint
        )
    try:
        pid = int(values["sase_tmux_pid"])
    except ValueError as exc:
        raise ScreenshotCaptureError(
            f"remote screenshot capture on {host!r} returned non-integer "
            f"sase_tmux_pid={values['sase_tmux_pid']!r}"
        ) from exc
    return _RemoteScreenshotMetadata(
        screenshot_dir=values["sase_screenshot_dir"],
        tmux_session=values["sase_tmux_session"],
        tmux_window=values["sase_tmux_window"],
        tmux_target=values["sase_tmux_target"],
        tmux_pid=pid,
    )


def _remote_send_keys_hint(host: str, tmux_target: str) -> str:
    remote_command = (
        f'IFS= read -r key && tmux send-keys -t {shlex.quote(tmux_target)} "$key"'
    )
    return f"printf '%s\\n' <KEY> | {shlex.join(['ssh', host, remote_command])}"


def _fetch_remote_svg(
    target: RemoteSshTarget,
    remote_svg: str,
    *,
    runner: CommandRunner,
    deadline: _Deadline,
) -> str:
    completed = _run_ssh(
        target,
        ["cat", remote_svg],
        runner=runner,
        deadline=deadline,
        action="fetch remote SVG",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ScreenshotCaptureError(
            f"failed to fetch remote SVG from {target.host!r}"
            + (f": {detail}" if detail else "")
        )
    return completed.stdout


def _remote_sase_version(
    target: RemoteSshTarget,
    *,
    runner: CommandRunner,
    deadline: _Deadline,
) -> str:
    completed = _run_ssh(
        target,
        ["sase", "--version"],
        runner=runner,
        deadline=deadline,
        action="read remote sase version",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ScreenshotCaptureError(
            f"failed to read remote sase version from {target.host!r}"
            + (f": {detail}" if detail else "")
        )
    version = completed.stdout.strip()
    if not version:
        raise ScreenshotCaptureError(
            f"remote sase version from {target.host!r} was empty"
        )
    return version


def _cleanup_remote_svg(
    target: RemoteSshTarget,
    remote_svg: str,
    *,
    runner: CommandRunner,
) -> None:
    try:
        runner.run(
            _ssh_argv(target.host, ["sh", "-c", f"rm -f {shlex.quote(remote_svg)}"]),
            capture_output=True,
            text=True,
            check=False,
            timeout=_SSH_OPERATION_TIMEOUT_SECONDS,
        )
    except Exception:
        return


def _run_ssh(
    target: RemoteSshTarget,
    remote_argv: Sequence[str],
    *,
    runner: CommandRunner,
    deadline: _Deadline,
    action: str,
    operation_timeout: float | None = _SSH_OPERATION_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    try:
        timeout = deadline.remaining
        if operation_timeout is not None:
            timeout = min(timeout, operation_timeout)
        completed = runner.run(
            _ssh_argv(target.host, remote_argv),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        _raise_for_ssh_transport_failure(completed, target=target, action=action)
        return completed
    except FileNotFoundError as exc:
        raise ScreenshotCaptureError("ssh is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ScreenshotCaptureError(
            f"timed out while trying to {action} on {target.host!r}; "
            "the host may be offline"
        ) from exc
    except OSError as exc:
        raise ScreenshotCaptureError(
            f"SSH failed while trying to {action} on {target.host!r}: {exc}"
        ) from exc


def _raise_for_ssh_transport_failure(
    completed: subprocess.CompletedProcess[str],
    *,
    target: RemoteSshTarget,
    action: str,
) -> None:
    if completed.returncode != 255:
        return
    detail = completed.stderr.strip() or completed.stdout.strip()
    raise ScreenshotCaptureError(
        f"SSH failed while trying to {action} on {target.host!r}"
        + (f": {detail}" if detail else "")
    )


def _ssh_argv(host: str, remote_argv: Sequence[str]) -> list[str]:
    return [
        "ssh",
        "-o",
        f"ConnectTimeout={_SSH_CONNECT_TIMEOUT_SECONDS}",
        "--",
        host,
        shlex.join(remote_argv),
    ]


def _remote_svg_path() -> str:
    return f"{_REMOTE_BASE}/sase-screenshot-{uuid4().hex}.svg"


def _output_path(output: Path | None, *, suffix: str) -> Path:
    if output is not None:
        return output.expanduser()
    directory = Path(get_sase_managed_tmpdir("screenshots"))
    return directory / f"sase_tui_{generate_timestamp()}{suffix}"


def _upgrade_message(host: str) -> str:
    return f"sase on {host!r} is missing or too old for `sase screenshot`; upgrade it"


class _Deadline:
    """Small monotonic deadline helper for one remote screenshot attempt."""

    def __init__(self, seconds: float) -> None:
        self._deadline = time.monotonic() + seconds

    @property
    def remaining(self) -> float:
        return max(0.001, self._deadline - time.monotonic())


__all__ = ["capture_remote_screenshot"]
