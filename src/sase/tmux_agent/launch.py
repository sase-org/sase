"""Create a tmux window running one catalog entry's agent CLI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import shlex
import uuid

from sase.config.tmux_agent import TmuxAgentConfig

from .models import TmuxAgentEntry
from .tmux import TmuxRunner, inside_tmux, tmux_agent_self_command, tmux_available
from .window import next_window_name

_CHANNEL_PREFIX = "sase-tmux-agent-"
_CHANNEL_HEX_LEN = 12


@dataclass(frozen=True)
class TmuxAgentLaunch:
    """Successful tmux Agent window launch."""

    window_name: str
    channel: str
    argv: tuple[str, ...]
    directory: str


@dataclass(frozen=True)
class TmuxAgentLaunchError:
    """A typed, non-raising failure from :func:`launch_agent_window`."""

    code: str
    message: str


def launch_agent_window(
    entry: TmuxAgentEntry,
    *,
    directory: str,
    config: TmuxAgentConfig,
    runner: TmuxRunner,
    self_command: str | None = None,
    channel: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> TmuxAgentLaunch | TmuxAgentLaunchError:
    """Open a new tmux window running *entry*'s resolved agent CLI.

    Registers the exit-cleanup waiter *before* creating the window, matching
    the shell script this feature replaces: ``run-shell -b`` hands the job
    to the tmux server so it survives the window closing.

    Failures return a :class:`TmuxAgentLaunchError` rather than raising.
    """
    if not tmux_available():
        return TmuxAgentLaunchError(
            "tmux_missing",
            "tmux is not installed or not on PATH; install tmux, then retry.",
        )
    if not inside_tmux(environ):
        return TmuxAgentLaunchError(
            "not_inside_tmux",
            "Not inside a tmux session; start tmux first, then retry.",
        )
    if not Path(directory).is_dir():
        return TmuxAgentLaunchError(
            "directory_missing",
            f"Directory {directory!r} does not exist; pass an existing path.",
        )
    if not entry.installed:
        hint = entry.install_hint.strip()
        message = (
            hint
            if hint
            else (
                f"{entry.display_name} is not installed; install its agent CLI, "
                "then retry."
            )
        )
        return TmuxAgentLaunchError("not_installed", message)

    window_name = next_window_name(
        config.window_name,
        tuple(name for _index, name in runner.list_windows()),
    )
    cleanup_channel = channel or _mint_channel()
    callback = self_command if self_command is not None else tmux_agent_self_command()
    waiter = _waiter_command(cleanup_channel, callback, config.after_close_command)
    runner.run_shell_background(waiter)

    shell_command = _window_shell_command(
        entry.argv,
        cleanup_channel,
        clear_screen=config.clear_screen,
    )
    created = runner.new_window(
        name=window_name,
        directory=directory,
        command=shell_command,
        env=entry.env,
    )
    if created.returncode != 0:
        detail = (created.stderr or created.stdout).strip() or "unknown tmux error"
        return TmuxAgentLaunchError(
            "new_window_failed",
            f"tmux new-window failed: {detail}. Check the tmux session and retry.",
        )
    return TmuxAgentLaunch(
        window_name=window_name,
        channel=cleanup_channel,
        argv=entry.argv,
        directory=directory,
    )


def _mint_channel() -> str:
    return f"{_CHANNEL_PREFIX}{uuid.uuid4().hex[:_CHANNEL_HEX_LEN]}"


def _waiter_command(channel: str, self_command: str, after_close_command: str) -> str:
    command = f"tmux wait-for {shlex.quote(channel)} && {self_command} --renumber"
    extra = after_close_command.strip()
    if extra:
        command = f"{command} && {extra}"
    return command


def _window_shell_command(
    argv: tuple[str, ...],
    channel: str,
    *,
    clear_screen: bool,
) -> str:
    parts: list[str] = []
    if clear_screen:
        parts.append("clear")
    parts.append(shlex.join(argv))
    parts.append(f"tmux wait-for -S {shlex.quote(channel)}")
    return "; ".join(parts)


__all__ = [
    "TmuxAgentLaunch",
    "TmuxAgentLaunchError",
    "launch_agent_window",
]
