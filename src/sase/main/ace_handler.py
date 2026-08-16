"""Handler for the 'sase ace' command."""

import argparse
import asyncio
import logging
import os
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NoReturn, cast

from sase.ace.query import QueryParseError
from sase.core.clipboard import copy_to_system_clipboard
from sase.core.paths import get_sase_managed_tmpdir, shorten_path
from sase.core.time import local_now

if TYPE_CHECKING:
    from sase.ace.tui.exit_action import AceExitAction

log = logging.getLogger(__name__)

_RESTART_FILTER_FLAGS = frozenset(("-R", "--restart-axe", "-T", "--tmux"))


def _profile_output_path(profile_arg: str) -> str:
    """Return the profile output path for an enabled ``--profile`` argument."""
    if profile_arg:
        output_path = os.path.expanduser(profile_arg)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        return output_path

    timestamp = local_now().strftime("%Y%m%d_%H%M%S")
    filename = f"ace_profile_{timestamp}.txt"
    return os.path.join(get_sase_managed_tmpdir("ace-profiles"), filename)


def _write_profile_output(profiler: Any, profile_arg: str) -> str:
    """Write profiler output and report a short, clipboard-friendly path."""
    output_path = _profile_output_path(profile_arg)
    Path(output_path).write_text(
        profiler.output_text(unicode=True, color=False, show_all=True)
    )

    display_path = shorten_path(output_path)
    print(f"Profile written to: {display_path}", file=sys.stderr)
    if copy_to_system_clipboard(display_path):
        print("Profile path copied to clipboard.", file=sys.stderr)
    else:
        print(
            "Profile path not copied: clipboard command not available.",
            file=sys.stderr,
        )
    return output_path


def _build_ace_restart_argv(*, restart_axe: bool, argv: list[str]) -> list[str]:
    """Build ``sase ace`` argv for a TUI restart."""
    forwarded: list[str] = []
    after_separator = False
    for arg in argv:
        if arg == "--":
            after_separator = True
            forwarded.append(arg)
            continue
        if not after_separator and arg in _RESTART_FILTER_FLAGS:
            continue
        forwarded.append(arg)

    if not forwarded or forwarded[0] != "ace":
        forwarded = ["ace", *forwarded]

    if restart_axe:
        try:
            insert_idx = forwarded.index("--")
        except ValueError:
            insert_idx = len(forwarded)
        forwarded.insert(insert_idx, "--restart-axe")

    return forwarded


def _exec_ace_restart_if_requested(exit_action: "AceExitAction | None") -> None:
    """Re-exec ``sase ace`` for restart exit actions."""
    from sase.ace.tui.exit_action import AceExitAction

    if exit_action is None or exit_action == AceExitAction.QUIT:
        return

    argv = _build_ace_restart_argv(
        restart_axe=exit_action == AceExitAction.RESTART_TUI_AND_AXE,
        argv=sys.argv[1:],
    )
    exec_args = [sys.executable, "-m", "sase", *argv]
    try:
        os.execv(sys.executable, exec_args)
    except OSError as exc:
        print(f"sase ace restart failed: {exc}", file=sys.stderr)
        sys.exit(1)


def _run_ace_app(app: Any) -> None:
    """Run ACE without waiting for asyncio's default executor at teardown.

    Textual's ``run_async`` restores the terminal before returning. Owning the
    loop here lets the command bypass ``asyncio.run``'s mandatory executor
    join, which can otherwise trap the process behind a blocking worker after
    the TUI has already disappeared.
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(app.run_async())
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _log_live_exit_threads() -> None:
    """Warn when ACE must abandon known non-daemon worker threads."""
    worker_names = sorted(
        thread.name
        for thread in threading.enumerate()
        if not thread.daemon
        and (
            thread.name.startswith("asyncio_") or thread.name.startswith("sase-loader")
        )
    )
    if worker_names:
        log.warning(
            "ACE exiting with live worker threads: %s",
            ", ".join(worker_names),
        )


def _hard_exit_ace(exit_code: int) -> NoReturn:
    """Flush durable state, then exit without interpreter thread joins."""
    from sase.telemetry import flush_metrics

    _log_live_exit_threads()
    for flush in (flush_metrics, sys.stdout.flush, sys.stderr.flush):
        try:
            flush()
        except Exception:
            log.debug("ACE exit flush failed", exc_info=True)
    os._exit(exit_code)


def handle_ace_command(args: argparse.Namespace) -> None:
    """Handle the 'sase ace' command."""
    if getattr(args, "tmux", False):
        from sase.main.ace_tmux import launch_ace_in_tmux

        launch_ace_in_tmux(args)
        sys.exit(0)

    from sase.ace.tui import AceApp
    from sase.ace.tui.log_setup import install_tui_file_logging
    from sase.config.core import set_include_local_config
    from sase.feature_flags import install_process_feature_flags

    # Don't load repo-level sase.yml for the TUI — local config should
    # only apply to agent runs (which are separate processes).
    set_include_local_config(False)
    # Pin flags only after local config is disabled; otherwise ACE would
    # inherit project-local feature_flags that are meant for agent runs.
    install_process_feature_flags()

    # Route every ``sase`` logger record (including un-instrumented
    # ``log.exception(...)`` calls) to a durable, findable ~/.sase/logs/tui.log
    # so "see the log" failure toasts always have something to point at.
    install_tui_file_logging()

    # Wire --vcs-provider to env var for downstream resolution
    vcs_provider = getattr(args, "vcs_provider", None)
    if vcs_provider is not None:
        os.environ["SASE_VCS_PROVIDER"] = vcs_provider

    profiler = None
    if args.profile is not None:
        try:
            import pyinstrument
        except ImportError:
            print(
                "Error: pyinstrument is not installed. "
                "Install it with: pip install sase[dev]",
                file=sys.stderr,
            )
            sys.exit(1)

        profiler = pyinstrument.Profiler(async_mode="enabled")
        profiler.start()

    try:
        # Resolve model tier: prefer --model-tier, fall back to --model-size
        model_tier_override = getattr(args, "model_tier", None)
        if model_tier_override is None:
            old_size = getattr(args, "model_size", None)
            if old_size is not None:
                model_tier_override = {"big": "large", "little": "small"}[old_size]

        from sase.ace.tui.tab_order import normalize_tab_name

        initial_tab = normalize_tab_name(args.tab)
        app = AceApp(
            query=args.query,
            model_tier_override=cast(
                Literal["large", "small"] | None, model_tier_override
            ),
            refresh_interval=args.refresh_interval,
            auto_start_axe=not getattr(args, "no_axe", False),
            restart_axe=getattr(args, "restart_axe", False),
            initial_tab=initial_tab,
        )
    except QueryParseError as e:
        print(f"Error: Invalid query: {e}")
        sys.exit(1)

    if profiler is not None:
        _run_ace_app(app)
        profiler.stop()
        _write_profile_output(profiler, args.profile)
    else:
        _run_ace_app(app)

    _exec_ace_restart_if_requested(
        getattr(app, "exit_action", None),
    )
    _hard_exit_ace(0)
