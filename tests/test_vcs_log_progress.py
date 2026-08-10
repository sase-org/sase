"""Tests for the ``sase stitch log`` remote-fetch indicator."""

from __future__ import annotations

import io

from rich.ansi import AnsiDecoder
from rich.console import Console

from sase.vcs_log.models import LogRepo
from sase.vcs_log.progress import make_fetch_progress


def test_noninteractive_fetch_progress_is_a_durable_stderr_line() -> None:
    out = io.StringIO()
    progress = make_fetch_progress("never", out=out)

    with progress(LogRepo("sase", "/p/sase", "primary"), "origin/main"):
        assert out.getvalue() == "↻ Fetching remote · sase ← origin/main\n"

    assert out.getvalue() == "↻ Fetching remote · sase ← origin/main\n"


def test_interactive_fetch_progress_uses_transient_spinner() -> None:
    out = io.StringIO()
    console = Console(file=out, force_terminal=True, no_color=True)
    progress = make_fetch_progress("never", console=console)

    with progress(LogRepo("sase-core", "/p/core", "linked"), "origin/main"):
        pass

    output = out.getvalue()
    plain = "".join(text.plain for text in AnsiDecoder().decode(output))
    assert "Fetching remote · sase-core ← origin/main" in plain
    assert "↻" not in plain
    assert "\r" in output
