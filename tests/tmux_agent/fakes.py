"""Shared fake tmux runner for tmux Agent launcher tests."""

from __future__ import annotations

from collections.abc import Sequence
import subprocess

from sase.tmux_agent.models import TmuxAgentCatalog, TmuxAgentEntry
from sase.tmux_agent.tmux import TmuxRunner


def completed(
    argv: Sequence[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(argv), returncode, stdout, stderr)


class FakeTmuxRunner(TmuxRunner):
    """Record every tmux argv and script list/new/rename/version calls."""

    def __init__(
        self,
        *,
        windows: Sequence[tuple[int, str]] = (),
        pane_dir: str = "/tmp",
        version_output: str = "tmux 3.5a",
        version_returncode: int = 0,
        new_window_error: str | None = None,
        display_menu_error: str | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self.windows = list(windows)
        self.pane_dir = pane_dir
        self.version_output = version_output
        self.version_returncode = version_returncode
        self.new_window_error = new_window_error
        self.display_menu_error = display_menu_error
        super().__init__(run=self._run_fake)

    def _run_fake(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        argv = [str(item) for item in args]
        self.calls.append(argv)
        assert argv and argv[0] == "tmux"
        sub = argv[1]
        if sub == "-V":
            return completed(
                argv,
                returncode=self.version_returncode,
                stdout=self.version_output + "\n",
            )
        if sub == "display-message":
            return completed(argv, stdout=self.pane_dir + "\n")
        if sub == "list-windows":
            stdout = "".join(f"{index}:{name}\n" for index, name in self.windows)
            return completed(argv, stdout=stdout)
        if sub == "run-shell":
            return completed(argv)
        if sub == "new-window":
            if self.new_window_error is not None:
                return completed(
                    argv, returncode=1, stderr=self.new_window_error + "\n"
                )
            return completed(argv)
        if sub == "rename-window":
            return completed(argv)
        if sub == "display-menu":
            if self.display_menu_error is not None:
                return completed(
                    argv, returncode=1, stderr=self.display_menu_error + "\n"
                )
            return completed(argv)
        raise AssertionError(f"unexpected tmux subcommand: {argv}")

    def calls_for(self, subcommand: str) -> list[list[str]]:
        return [call for call in self.calls if len(call) > 1 and call[1] == subcommand]


def make_entry(
    provider: str,
    *,
    installed: bool = True,
    key: str = "",
    display_name: str = "",
    vendor: str = "",
    color: str = "#7aa2f7",
    argv: tuple[str, ...] = (),
    env: tuple[tuple[str, str], ...] = (),
    install_hint: str = "",
) -> TmuxAgentEntry:
    return TmuxAgentEntry(
        provider=provider,
        display_name=display_name or provider,
        vendor=vendor,
        color=color,
        key=key or provider[:1],
        binary=provider,
        executable=f"/usr/bin/{provider}" if installed else None,
        installed=installed,
        install_hint=install_hint or f"install {provider} first",
        routing_disabled=None,
        argv=argv or (provider,),
        env=env,
        effort=None,
        effort_skipped=None,
        bypass=True,
    )


def make_catalog(
    entries: Sequence[TmuxAgentEntry],
    *,
    directory: str = "/tmp/project",
    default_provider: str | None = None,
) -> TmuxAgentCatalog:
    resolved_default = default_provider
    if resolved_default is None:
        for entry in entries:
            if entry.installed:
                resolved_default = entry.provider
                break
    return TmuxAgentCatalog(
        entries=tuple(entries),
        default_provider=resolved_default,
        directory=directory,
    )
