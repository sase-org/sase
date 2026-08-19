"""Deep terminal capability checks for ``sase doctor``."""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import TYPE_CHECKING

from sase.ace.tui.graphics.capability import image_render_context
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.tmux_agent.tmux import parse_tmux_version

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_VERSION_TIMEOUT_SECONDS = 2.0
_TMUX_PASSTHROUGH_MIN_VERSION = (3, 3)


def check_kitty_graphics(context: DoctorContext) -> DiagnosticCheck:
    """Infer kitty-graphics support for inline artifact rendering."""
    support = _kitty_graphics_support(context.env)
    kitten_path = shutil.which("kitten")
    missing_details: list[str] = []
    if not support["supported"]:
        missing_details.append(
            "Inline image/PDF/Markdown artifact rendering needs a terminal that supports the kitty graphics protocol."
        )
    if kitten_path is None:
        missing_details.append(
            "`kitten` is not installed or not on PATH; it is used for terminal image artifact display."
        )

    status: CheckStatus = "WARN" if missing_details else "OK"
    summary = (
        "kitty graphics protocol is advertised for inline artifacts"
        if status == "OK"
        else "kitty graphics inline artifact support is incomplete"
    )
    details = (f"Detection: {support['reason']}.", *missing_details)
    next_steps = tuple(
        step
        for step in (
            "Run ACE in kitty, WezTerm, Ghostty, or another terminal with kitty graphics support."
            if not support["supported"]
            else "",
            "Install `kitten` to enable terminal image artifact display."
            if kitten_path is None
            else "",
            "Inside tmux, also use tmux >= 3.3 with passthrough enabled."
            if context.env.get("TMUX")
            else "",
        )
        if step
    )

    return DiagnosticCheck(
        id="terminal.kitty_graphics",
        group="terminal",
        status=status,
        title="Kitty graphics protocol",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={
            "supported": support["supported"],
            "reason": support["reason"],
            "kitten_resolved_path": kitten_path,
            "term": context.env.get("TERM"),
            "term_program": context.env.get("TERM_PROGRAM"),
            "kitty_window_id_set": bool(context.env.get("KITTY_WINDOW_ID")),
            "wezterm_pane_set": bool(context.env.get("WEZTERM_PANE")),
            "ghostty_resources_dir_set": bool(context.env.get("GHOSTTY_RESOURCES_DIR")),
            "inside_tmux": bool(context.env.get("TMUX")),
        },
    )


def check_tmux_version(context: DoctorContext) -> DiagnosticCheck:
    """Check the tmux floor needed for kitty graphics passthrough."""
    tmux_path = shutil.which("tmux")
    if tmux_path is None:
        return DiagnosticCheck(
            id="tools.tmux_version",
            group="tools",
            status="SKIP",
            title="tmux passthrough version",
            summary="tmux command is unavailable; version check skipped",
            details=("`tools.tmux` reports missing tmux for ACE tmux workflows.",),
            data={
                "command": "tmux",
                "resolved_path": None,
                "version": None,
                "minimum_version": _format_tmux_version(_TMUX_PASSTHROUGH_MIN_VERSION),
                "inside_tmux": bool(context.env.get("TMUX")),
            },
        )

    probe = _run_tmux_version_probe(tmux_path)
    if probe["probe_status"] != "ok":
        return DiagnosticCheck(
            id="tools.tmux_version",
            group="tools",
            status="WARN",
            title="tmux passthrough version",
            summary="tmux version could not be probed",
            details=(str(probe["detail"]),),
            next_steps=("Run `tmux -V` and verify tmux is healthy on PATH.",),
            data={
                "command": "tmux",
                "resolved_path": tmux_path,
                "version": None,
                "minimum_version": _format_tmux_version(_TMUX_PASSTHROUGH_MIN_VERSION),
                "inside_tmux": bool(context.env.get("TMUX")),
                **probe,
            },
        )

    raw_version = str(probe["version"] or "")
    parsed = parse_tmux_version(raw_version)
    if parsed is None:
        return DiagnosticCheck(
            id="tools.tmux_version",
            group="tools",
            status="WARN",
            title="tmux passthrough version",
            summary="tmux version output could not be parsed",
            details=(f"Output: {raw_version or probe['detail']}",),
            next_steps=("Run `tmux -V` and confirm tmux is >= 3.3.",),
            data={
                "command": "tmux",
                "resolved_path": tmux_path,
                "version": raw_version,
                "parsed_version": None,
                "minimum_version": _format_tmux_version(_TMUX_PASSTHROUGH_MIN_VERSION),
                "inside_tmux": bool(context.env.get("TMUX")),
                **probe,
            },
        )

    version_ok = parsed >= _TMUX_PASSTHROUGH_MIN_VERSION
    status: CheckStatus = "OK" if version_ok else "WARN"
    display_version = _tmux_display_version(raw_version)
    summary = (
        f"tmux {display_version} supports kitty graphics passthrough"
        if version_ok
        else f"tmux {display_version} is older than the passthrough floor"
    )
    details = (
        (
            "Kitty graphics passthrough still requires `allow-passthrough` enabled in tmux configuration.",
        )
        if version_ok
        else (
            "Inline artifact rendering through tmux needs tmux >= 3.3 with passthrough enabled.",
        )
    )
    next_steps = (
        ()
        if version_ok
        else (
            "Upgrade tmux to 3.3 or newer and enable passthrough with `set -g allow-passthrough on`.",
        )
    )

    return DiagnosticCheck(
        id="tools.tmux_version",
        group="tools",
        status=status,
        title="tmux passthrough version",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={
            "command": "tmux",
            "resolved_path": tmux_path,
            "version": raw_version,
            "parsed_version": list(parsed),
            "minimum_version": _format_tmux_version(_TMUX_PASSTHROUGH_MIN_VERSION),
            "inside_tmux": bool(context.env.get("TMUX")),
            **probe,
        },
    )


def check_truecolor(context: DoctorContext) -> DiagnosticCheck:
    """Check whether image previews can use 24-bit terminal colors."""
    term = context.env.get("TERM", "")
    colorterm = context.env.get("COLORTERM", "")
    if not term and not colorterm:
        return DiagnosticCheck(
            id="terminal.truecolor",
            group="terminal",
            status="SKIP",
            title="Terminal truecolor",
            summary="terminal color environment is unavailable",
            details=(
                "ACE image-preview fidelity only matters inside an interactive terminal.",
            ),
            data={
                "term": None,
                "colorterm": None,
                "truecolor": False,
                "reason": "no TERM or COLORTERM value was set",
            },
        )
    if term.lower() == "dumb" and not colorterm:
        return DiagnosticCheck(
            id="terminal.truecolor",
            group="terminal",
            status="SKIP",
            title="Terminal truecolor",
            summary="terminal is marked dumb; image-preview fidelity check skipped",
            data={
                "term": term,
                "colorterm": None,
                "truecolor": False,
                "reason": "TERM=dumb",
            },
        )

    render_context = image_render_context(context.env)
    if render_context.truecolor:
        return DiagnosticCheck(
            id="terminal.truecolor",
            group="terminal",
            status="OK",
            title="Terminal truecolor",
            summary="terminal advertises truecolor for image previews",
            details=(render_context.reason,),
            data={
                "term": term or None,
                "colorterm": colorterm or None,
                "truecolor": True,
                "reason": render_context.reason,
            },
        )

    return DiagnosticCheck(
        id="terminal.truecolor",
        group="terminal",
        status="WARN",
        title="Terminal truecolor",
        summary="terminal does not advertise truecolor for image previews",
        details=(
            render_context.reason,
            "ACE falls back to 256-color cell image previews, which are lower fidelity.",
        ),
        next_steps=(
            "Use a terminal that advertises 24-bit color, or set `COLORTERM=truecolor` if your terminal supports it.",
        ),
        data={
            "term": term or None,
            "colorterm": colorterm or None,
            "truecolor": False,
            "reason": render_context.reason,
        },
    )


def _kitty_graphics_support(env: dict[str, str]) -> dict[str, str | bool]:
    term = env.get("TERM", "").lower()
    term_program = env.get("TERM_PROGRAM", "").lower()
    if env.get("KITTY_WINDOW_ID") or term == "xterm-kitty":
        return {"supported": True, "reason": "kitty terminal markers are set"}
    if env.get("WEZTERM_PANE") or term_program == "wezterm" or "wezterm" in term:
        return {"supported": True, "reason": "WezTerm terminal markers are set"}
    if (
        env.get("GHOSTTY_RESOURCES_DIR")
        or term_program == "ghostty"
        or "ghostty" in term
    ):
        return {"supported": True, "reason": "Ghostty terminal markers are set"}
    return {
        "supported": False,
        "reason": "no known kitty-graphics terminal marker was found",
    }


def _run_tmux_version_probe(tmux_path: str) -> dict[str, str | int | None]:
    try:
        result = subprocess.run(
            [tmux_path, "-V"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "probe_status": "timeout",
            "detail": f"`tmux -V` timed out after {_VERSION_TIMEOUT_SECONDS:g}s",
            "version": None,
            "returncode": None,
        }
    except OSError as exc:
        return {
            "probe_status": "error",
            "detail": f"{type(exc).__name__}: {exc}",
            "version": None,
            "returncode": None,
        }

    output = (result.stdout or result.stderr).strip().splitlines()
    version = output[0].strip() if output else ""
    if result.returncode == 0:
        return {
            "probe_status": "ok",
            "detail": version or "version command succeeded",
            "version": version,
            "returncode": result.returncode,
        }
    return {
        "probe_status": "failed",
        "detail": version or f"exited {result.returncode}",
        "version": version,
        "returncode": result.returncode,
    }


def _format_tmux_version(version: tuple[int, int]) -> str:
    return f"{version[0]}.{version[1]}"


def _tmux_display_version(raw_version: str) -> str:
    """Return the tmux version without the leading ``tmux`` program token.

    ``tmux -V`` prints ``tmux 3.5a``; summaries already prepend ``tmux``, so the
    raw output must be stripped to avoid a doubled ``tmux tmux 3.5a``.
    """
    stripped = re.sub(r"(?i)^tmux\s+", "", raw_version.strip())
    return stripped or raw_version.strip()
