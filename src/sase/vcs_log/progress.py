"""Live remote-fetch status for ``sase stitch log``."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TextIO

from rich.console import Console
from rich.text import Text

from sase.vcs_log._style import INCOMING, make_console
from sase.vcs_log.collect import FetchProgress
from sase.vcs_log.models import LogRepo


def make_fetch_progress(
    color: str, *, out: TextIO | None = None, console: Console | None = None
) -> FetchProgress:
    """Return a remote-fetch indicator that writes exclusively to stderr.

    Interactive terminals get an animated, transient spinner. Redirected
    output gets one durable line per actual fetch so a quiet network wait is
    still understandable without contaminating stdout.
    """
    stream = out if out is not None else sys.stderr
    target = console or make_console(color, file=stream)

    @contextmanager
    def progress(repo: LogRepo, remote_ref: str) -> Iterator[None]:
        message = _fetch_message(repo.name, remote_ref)
        if target.is_terminal:
            with target.status(message, spinner="dots", spinner_style=INCOMING):
                yield
            return

        target.print(_static_fetch_message(message), soft_wrap=True)
        yield

    return progress


def _fetch_message(repo_name: str, remote_ref: str) -> Text:
    message = Text("Fetching remote", style="bold")
    message.append(" · ", style="dim")
    message.append(repo_name, style=f"bold {INCOMING}")
    message.append(" ← ", style=INCOMING)
    message.append(remote_ref, style="dim")
    return message


def _static_fetch_message(message: Text) -> Text:
    line = Text("↻ ", style=INCOMING)
    line.append_text(message)
    return line


__all__ = ["make_fetch_progress"]
