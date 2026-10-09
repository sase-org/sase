#!/usr/bin/env python3
"""Plan rendering for the ``sase_install`` engine (stdlib-only).

Panels follow the ``sase update`` visual language with hand-rolled ANSI
codes: rounded cyan panels, ``✓``/``⚠``/``✗``/``–`` glyphs, a dim detail
column, and a width clamped to 60\u2013100 columns. Progress goes to stderr;
plans, summaries, and JSON go to stdout.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import _sase_install_plan as install_plan


SCHEMA_VERSION = 1

PROMPT_TEXT = "Proceed? [y/N]"

#: Braille spinner frames for the live progress renderer (TTY only).
SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

#: Step glyphs for the live and plain progress renderers.
GLYPH_PENDING = "○"
GLYPH_OK = "✓"
GLYPH_WARN = "⚠"
GLYPH_FAIL = "✗"
GLYPH_SKIP = "–"

_RESET = "\x1b[0m"
_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_CYAN = "\x1b[36m"
_GREEN = "\x1b[32m"
_YELLOW = "\x1b[33m"
_RED = "\x1b[31m"

_TOP_LEFT = "\u256d"
_TOP_RIGHT = "\u256e"
_BOTTOM_LEFT = "\u2570"
_BOTTOM_RIGHT = "\u256f"
_VERTICAL = "\u2502"
_HORIZONTAL = "\u2500"


def paint(text: str, *codes: str, enabled: bool = False) -> str:
    """Wrap *text* in ANSI codes when *enabled*, else return it unchanged."""
    if not enabled or not codes:
        return text
    return f"{''.join(codes)}{text}{_RESET}"


def shorten_home(path: str, home: str | Path | None = None) -> str:
    """Replace a leading home directory with ``~`` for display."""
    root = str(home) if home is not None else str(Path.home())
    if path == root:
        return "~"
    if path.startswith(root + "/"):
        return "~" + path[len(root) :]
    return path


#: Glyphs this renderer emits that occupy two terminal cells.
_WIDE_CHARS = frozenset({"\u26a0"})


def _dwidth(text: str) -> int:
    """Return the terminal-cell width of *text* (wide glyphs count double)."""
    return sum(2 if char in _WIDE_CHARS else 1 for char in text)


def _fit(text: str, width: int) -> str:
    if _dwidth(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    out: list[str] = []
    used = 0
    for char in text:
        char_width = 2 if char in _WIDE_CHARS else 1
        if used + char_width > width - 1:
            break
        out.append(char)
        used += char_width
    return "".join(out) + "\u2026"


def _pad_to(text: str, width: int) -> str:
    return text + " " * max(0, width - _dwidth(text))


def _current_desc(
    row: install_plan.PlanRow,
    *,
    home: str | Path | None = None,
    compact: bool = False,
) -> str:
    current = row.current
    if current.kind == "editable" and current.path is not None:
        if compact:
            if current.version:
                return f"editable {current.version}"
            return "editable"
        desc = shorten_home(current.path, home)
        if current.version:
            desc = f"{desc} \u00b7 {current.version}"
        return desc
    if current.kind == "local":
        return f"{current.version} local build" if current.version else "local build"
    if current.kind == "pypi":
        return current.version if current.version else "PyPI"
    if current.kind == "missing":
        return "not installed"
    if current.path:
        return shorten_home(current.path, home)
    return current.kind or "unknown"


def _target_desc(row: install_plan.PlanRow, *, home: str | Path | None = None) -> str:
    target = row.target
    if target.kind == "editable" and target.path is not None:
        return shorten_home(target.path, home)
    if target.kind == "editable":
        return "editable"
    if target.version:
        return f"{target.version} PyPI"
    return "PyPI"


_BORING_KEEP_NOTES = frozenset({"editable checkout", "already current", "local build"})


def _row_content(
    row: install_plan.PlanRow,
    *,
    home: str | Path | None = None,
    content_width: int | None = None,
) -> str:
    kind = row.kind
    if kind == install_plan.CHANGE_REMOVE:
        content = f"{_current_desc(row, home=home)}  \u2192  removed"
        if row.note:
            content = f"{content}   {row.note}"
        return content
    if kind == install_plan.CHANGE_KEEP:
        content = _current_desc(row, home=home)
        if row.note and row.note not in _BORING_KEEP_NOTES:
            full = f"{content}  \u2192  {row.note}"
            compact = (
                f"{_current_desc(row, home=home, compact=True)}  \u2192  {row.note}"
            )
            if content_width is None or len(full) <= content_width:
                return full
            return compact
        return content
    content = (
        f"{_current_desc(row, home=home, compact=True)}  \u2192  "
        f"{_target_desc(row, home=home)}"
    )
    if kind == install_plan.CHANGE_DOWNGRADE:
        content = f"{content}   \u26a0 downgrade"
    elif "\u26a0" in row.note:
        tail = row.note.split("\u00b7")[-1].strip()
        content = f"{content}   {tail}"
    elif kind == install_plan.CHANGE_UPGRADE and row.note and row.note != "PyPI":
        # The core fast-forward row carries its <a> -> <b> action here.
        content = f"{content}   \u00b7 {row.note}"
    return content


def _panel_title(plan: install_plan.InstallPlan) -> str:
    if plan.mode == "dev":
        return "just install-dev \u00b7 your `sase` \u2192 this checkout (editable)"
    return "just install \u00b7 your `sase` \u2192 PyPI"


def render_plan_panel(
    plan: install_plan.InstallPlan,
    *,
    width: int = 80,
    color: bool = False,
    home: str | Path | None = None,
) -> str:
    """Render the plan as a rounded panel fixed to *width* columns."""
    width = max(60, min(100, width))
    inner = width - 2
    label_width = 12
    content_width = inner - 2 - label_width - 1 - 1

    def border(left: str, right: str, fill: str) -> str:
        return paint(f"{left}{fill * inner}{right}", _CYAN, enabled=color)

    title = _fit(_panel_title(plan), inner - 4)
    top = paint(
        f"{_TOP_LEFT}\u2500 {title} ",
        _CYAN,
        enabled=color,
    ) + paint(
        f"{_HORIZONTAL * (inner - _dwidth(title) - 3)}{_TOP_RIGHT}",
        _CYAN,
        enabled=color,
    )

    lines = [top]
    first_plugin = True
    for row in plan.rows:
        if row.role == "plugin":
            label = "plugins" if first_plugin else ""
            first_plugin = False
        elif row.role == "host":
            label = row.name
        elif row.role == "core":
            label = row.name
        else:
            label = row.name
        content = _fit(
            _row_content(row, home=home, content_width=content_width), content_width
        )
        if row.consequential:
            content = paint(content, _YELLOW, enabled=color)
        pad = " " * max(0, content_width - _dwidth(content))
        lines.append(
            paint(_VERTICAL, _CYAN, enabled=color)
            + f" {_fit(label, label_width):<{label_width}} {content}{pad} "
            + paint(_VERTICAL, _CYAN, enabled=color)
        )

    python = plan.python
    if python.current is not None or python.target is not None:
        if python.change:
            py_content = (
                f"{python.current} \u2192 {python.target}   \u26a0 python change"
            )
            py_content = paint(py_content, _YELLOW, enabled=color)
        elif python.current is not None:
            py_content = f"{python.current} (kept)"
        else:
            py_content = f"{python.target} (new)"
        py_content = _fit(py_content, content_width)
        pad = " " * max(0, content_width - _dwidth(py_content))
        lines.append(
            paint(_VERTICAL, _CYAN, enabled=color)
            + f" {'python':<{label_width}} {py_content}{pad} "
            + paint(_VERTICAL, _CYAN, enabled=color)
        )

    right = f"currently: {plan.current_mode}"
    left = _fit(shorten_home(plan.target_dir, home), content_width - len(right) - 2)
    target_content = f"{left}  {right}"
    target_content = _fit(target_content, content_width)
    pad = " " * max(0, content_width - _dwidth(target_content))
    lines.append(
        paint(_VERTICAL, _CYAN, enabled=color)
        + f" {'target':<{label_width}} {paint(target_content, _DIM, enabled=color)}{pad} "
        + paint(_VERTICAL, _CYAN, enabled=color)
    )

    host_rows = [row for row in plan.rows if row.role == "host"]
    if (
        host_rows
        and host_rows[0].kind == install_plan.CHANGE_TO_PYPI
        and host_rows[0].current.path is not None
    ):
        warn = _fit(
            "\u26a0 Replaces your editable install from "
            f"{shorten_home(host_rows[0].current.path, home)}.",
            content_width,
        )
        pad = " " * max(0, content_width - _dwidth(warn))
        lines.append(
            paint(_VERTICAL, _CYAN, enabled=color)
            + f" {'':<{label_width}} {paint(warn, _YELLOW, enabled=color)}{pad} "
            + paint(_VERTICAL, _CYAN, enabled=color)
        )

    lines.append(border(_BOTTOM_LEFT, _BOTTOM_RIGHT, _HORIZONTAL))
    return "\n".join(lines)


def render_noop_line(
    plan: install_plan.InstallPlan,
    *,
    checkout_short: str | None = None,
    core_short: str | None = None,
) -> str:
    """Render the repeat-run no-op summary line.

    Dev runs name the checkout and core SHAs when the caller resolved them;
    without SHAs the generic line is used (for example dry-run previews
    where git may be unavailable).
    """
    if plan.mode == "dev":
        if checkout_short is not None and core_short is not None:
            return (
                f"\u2713 sase already runs this checkout ({checkout_short}) "
                f"with sase-core {core_short} "
                "\u2014 nothing to do (--force reinstalls)"
            )
        return (
            "\u2713 sase already runs this checkout "
            "\u2014 nothing to do (--force reinstalls)"
        )
    host_rows = [row for row in plan.rows if row.role == "host"]
    version = host_rows[0].target.version if host_rows else None
    if version:
        return (
            f"\u2713 sase {version} from PyPI is already installed "
            "\u2014 nothing to do (--force reinstalls)"
        )
    return (
        "\u2713 sase from PyPI is already installed "
        "\u2014 nothing to do (--force reinstalls)"
    )


def render_summary_line(plan: install_plan.InstallPlan, *, dry_run: bool) -> str:
    """Render the one-line summary used by ``-q``."""
    if plan.noop:
        return render_noop_line(plan)
    changes = sum(1 for row in plan.rows if row.kind != install_plan.CHANGE_KEEP)
    noun = "change" if changes == 1 else "changes"
    suffix = " \u2014 dry run, nothing changed" if dry_run else ""
    flag = ", consequential" if plan.consequential else ""
    return f"{plan.command}: {changes} {noun}{flag}{suffix}"


def render_warning_lines(plan: install_plan.InstallPlan) -> list[str]:
    """Render plan warnings as ``⚠`` lines printed after the panel."""
    return [f"\u26a0 {warning}" for warning in plan.warnings]


def _shrink_path(path: str, width: int) -> str:
    """Shorten *path* to *width* cells, keeping the distinguishing tail."""
    if _dwidth(path) <= width:
        return path
    if width <= 1:
        return path[:width]
    out: list[str] = []
    used = 0
    for char in reversed(path):
        char_width = 2 if char in _WIDE_CHARS else 1
        if used + char_width > width - 1:
            break
        out.append(char)
        used += char_width
    return "\u2026" + "".join(reversed(out))


def render_sync_report(
    results: Sequence[Mapping[str, object]],
    *,
    width: int = 80,
    color: bool = False,
    home: str | Path | None = None,
) -> str:
    """Render the ``--sync`` fetch/merge report as a rounded box.

    *results* holds per-repo mappings with ``path``, ``ok``, ``skipped``,
    and ``detail`` keys (see ``sync_document`` for the JSON shape). Long
    paths shrink from the front so the per-repo outcome is never cut off.
    """
    width = max(60, min(100, width))
    inner = width - 2
    content_width = inner - 2

    title = _fit("just install-dev \u00b7 --sync", inner - 4)
    top = paint(
        f"{_TOP_LEFT}\u2500 {title} ",
        _CYAN,
        enabled=color,
    ) + paint(
        f"{_HORIZONTAL * (inner - _dwidth(title) - 3)}{_TOP_RIGHT}",
        _CYAN,
        enabled=color,
    )
    lines = [top]
    for result in results:
        path = shorten_home(str(result.get("path", "?")), home)
        detail = str(result.get("detail", ""))
        if result.get("skipped"):
            glyph = "\u2013"
        elif result.get("ok"):
            glyph = "\u2713"
        else:
            glyph = "\u2717"
        room = content_width - _dwidth(f"{glyph}   {detail}")
        if room >= 8:
            content = f"{glyph} {_shrink_path(path, room)}  {detail}"
        else:
            content = _fit(f"{glyph} {path}  {detail}", content_width)
        if not result.get("ok") and not result.get("skipped"):
            content = paint(content, _YELLOW, enabled=color)
        pad = " " * max(0, content_width - _dwidth(content))
        lines.append(
            paint(_VERTICAL, _CYAN, enabled=color)
            + f" {content}{pad} "
            + paint(_VERTICAL, _CYAN, enabled=color)
        )
    lines.append(
        paint(
            f"{_BOTTOM_LEFT}{_HORIZONTAL * inner}{_BOTTOM_RIGHT}",
            _CYAN,
            enabled=color,
        )
    )
    return "\n".join(lines)


def sync_document(results: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Return the ``-j`` ``sync`` entries for per-repo gate results."""
    documents: list[dict[str, object]] = []
    for result in results:
        documents.append(
            {
                "path": result.get("path"),
                "ok": bool(result.get("ok")),
                "skipped": bool(result.get("skipped", False)),
                "detail": result.get("detail"),
            }
        )
    return documents


def render_prereq_line(probes: Sequence[Mapping[str, str | None]]) -> str:
    """Render the dim prerequisite-versions line shown before the panel."""
    parts = []
    for probe in probes:
        name = probe.get("name") or "?"
        version = probe.get("version")
        parts.append(f"{name} {version}" if version else str(name))
    return "prerequisites: " + " \u00b7 ".join(parts)


def pipeline_steps(mode: str) -> list[str]:
    """Return the full pipeline step names for *mode* (execution is later work)."""
    if mode == "dev":
        return [
            "preflight",
            "plan",
            "confirm",
            "prepare",
            "lock",
            "swap",
            "re-apply",
            "verify",
            "restart",
            "summary",
        ]
    return [
        "preflight",
        "plan",
        "confirm",
        "lock",
        "swap",
        "verify",
        "restart",
        "summary",
    ]


def plan_document(
    plan: install_plan.InstallPlan,
    *,
    dry_run: bool,
    outcome: str,
    error: str | None = None,
    log_path: str | None = None,
    sync: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Build the ``-j`` JSON document body (``schema_version: 1``)."""
    packages: list[dict[str, object]] = []
    for row in plan.rows:
        packages.append(
            {
                "name": row.name,
                "role": row.role,
                "current": {
                    "source": row.current.kind,
                    "version": row.current.version,
                    "path": row.current.path,
                },
                "target": {
                    "source": row.target.kind,
                    "version": row.target.version,
                    "path": row.target.path,
                },
                "change": row.kind,
                "consequential": row.consequential,
                "note": row.note,
            }
        )
    commands: list[dict[str, object]] = [
        {"purpose": "swap", "argv": list(plan.swap_argv)}
    ]
    if plan.overrides_path is not None:
        commands.append(
            {
                "purpose": "write-overrides",
                "path": plan.overrides_path,
                "lines": list(plan.overrides_lines),
            }
        )
    if plan.mode == "dev":
        commands.append(
            {
                "purpose": "re-apply",
                # Mirrors the pipeline's re-apply argv (dev-update Cargo
                # profile); the literal is duplicated here because this
                # module must not import the run module.
                "argv": [
                    "just",
                    "-f",
                    f"{plan.checkout_root}/Justfile",
                    "rust-dev-install-uv-tool",
                ],
                "env": {"SASE_RUST_DEV_PROFILE": "dev-update"},
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "command": plan.command,
        "mode": plan.mode,
        "dry_run": dry_run,
        "outcome": outcome,
        "packages": packages,
        "python": {
            "current": plan.python.current,
            "target": plan.python.target,
            "requested": plan.python.requested,
            "change": plan.python.change,
        },
        "target": {"path": plan.target_dir, "current_mode": plan.current_mode},
        "warnings": list(plan.warnings),
        "consequential": plan.consequential,
        "noop": plan.noop,
        "commands": commands,
        "steps": pipeline_steps(plan.mode),
        "error": error,
        "log_path": log_path,
        "sync": sync_document(sync) if sync is not None else None,
    }


def render_json(
    plan: install_plan.InstallPlan,
    *,
    dry_run: bool,
    outcome: str,
    error: str | None = None,
    log_path: str | None = None,
    sync: Sequence[Mapping[str, object]] | None = None,
) -> str:
    """Render the ``-j`` JSON document to stdout (nothing decorative)."""
    return (
        json.dumps(
            plan_document(
                plan,
                dry_run=dry_run,
                outcome=outcome,
                error=error,
                log_path=log_path,
                sync=sync,
            ),
            indent=2,
            sort_keys=False,
        )
        + "\n"
    )


def read_confirmation(stdin: object) -> bool:
    """Read one ``[y/N]`` answer line; anything but ``y``/``yes`` declines."""
    readline = getattr(stdin, "readline", None)
    if not callable(readline):
        return False
    try:
        answer = readline()
    except (OSError, ValueError):
        return False
    if not isinstance(answer, str):
        return False
    return answer.strip().lower() in ("y", "yes")


def format_duration(seconds: float) -> str:
    """Format a step duration as ``0.4s`` or ``1:02``."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def format_elapsed(seconds: float) -> str:
    """Format an elapsed clock as ``mm:ss`` for plain progress lines."""
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def format_plain_step(
    elapsed: float,
    glyph: str,
    title: str,
    detail: str = "",
    duration: float | None = None,
) -> str:
    """Format one append-only plain progress line (non-TTY output)."""
    line = f"[{format_elapsed(elapsed)}] {glyph} {title}"
    if detail:
        line = f"{line} — {detail}"
    if duration is not None:
        line = f"{line} ({format_duration(duration)})"
    return line


def tail_lines(text: str, count: int = 20) -> list[str]:
    """Return the last *count* lines of *text* (the failure tail)."""
    return text.splitlines()[-count:]


def render_pypi_success(plan: install_plan.InstallPlan) -> str:
    """Render the two-line PyPI success summary (stdout)."""
    host_version = next(
        (row.target.version for row in plan.rows if row.role == "host"), None
    )
    core_version = next(
        (row.target.version for row in plan.rows if row.role == "core"), None
    )
    plugins = [
        row
        for row in plan.rows
        if row.role == "plugin" and row.kind != install_plan.CHANGE_REMOVE
    ]
    noun = "plugin" if len(plugins) == 1 else "plugins"
    host = f"sase {host_version}" if host_version else "sase"
    core = f"sase-core-rs {core_version}" if core_version else "sase-core-rs"
    return (
        f"✓ {host} from PyPI is installed ({core} · {len(plugins)} {noun})\n"
        "  update later: sase update · develop on this checkout: just install-dev"
    )


def render_dev_success(
    plan: install_plan.InstallPlan,
    *,
    checkout_short: str,
    core_short: str,
    pin_short: str,
    commits_past_pin: int | None,
) -> str:
    """Render the two-line dev success summary (stdout).

    *commits_past_pin* is the core HEAD's distance past the pin (``None``
    when git could not answer); a positive distance renders as ``+ N``.
    """
    del plan
    pin = f"pin {pin_short}"
    if commits_past_pin:
        pin += f" + {commits_past_pin}"
    return (
        f"✓ sase now runs this checkout ({checkout_short}) "
        f"with sase-core {core_short} ({pin})\n"
        "  Python edits are live · after Rust edits: just install-dev "
        "· back to the release: just install"
    )


def render_failure_block(
    *,
    step_title: str,
    log_path: str,
    tail: Sequence[str],
    restore_command: str | None = None,
) -> str:
    """Render the stderr failure block: log path, step tail, restore command.

    The block names the hand-restore command but never claims a rollback
    happened: the previous install is only restored when a human runs it.
    """
    lines = [f"✗ {step_title} failed", f"  log: {log_path}"]
    lines.extend(f"  {line}" for line in tail)
    if restore_command:
        lines.append("  to restore the previous install, run:")
        lines.append(f"    {restore_command}")
    return "\n".join(lines)


class Progress:
    """Step progress for the execution pipeline (writes to stderr).

    Three modes: ``live`` (a TTY spinner that rewrites the current line),
    ``plain`` (append-only ``[mm:ss]`` lines for pipes and ``-v``), and
    ``quiet`` (nothing until the caller prints its summary). Step glyphs and
    durations follow the ``sase update`` visual language; ``NO_COLOR`` and
    non-TTY output are honored by the caller selecting plain or quiet.
    """

    def __init__(
        self,
        stream: object,
        *,
        mode: str = "plain",
        color: bool = False,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._stream = stream
        self._mode = mode
        self._color = color
        self._clock = clock or time.monotonic
        self._title = ""
        self._start = 0.0
        self._frame = 0
        self._active = False
        self._last_len = 0

    def _write(self, text: str) -> None:
        write = getattr(self._stream, "write", None)
        if callable(write):
            write(text)
        flush = getattr(self._stream, "flush", None)
        if callable(flush):
            try:
                flush()
            except (OSError, ValueError):
                pass

    def _clear_live_line(self) -> None:
        if self._last_len:
            self._write("\r" + " " * self._last_len + "\r")
            self._last_len = 0

    def start(self, step: str, title: str) -> None:
        """Announce a pipeline step (``step`` is the machine name)."""
        del step
        self._title = title
        self._start = self._clock()
        self._frame = 0
        self._active = True
        if self._mode == "live":
            line = f"{paint(GLYPH_PENDING, _CYAN, enabled=self._color)} {title} …"
            self._write(line)
            self._last_len = _dwidth(line)

    def tick(self, detail: str = "") -> None:
        """Advance the live spinner (a no-op outside live mode)."""
        if self._mode != "live" or not self._active:
            return
        frame = SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)]
        self._frame += 1
        suffix = f" — {detail}" if detail else ""
        line = f"{paint(frame, _CYAN, enabled=self._color)} {self._title}{suffix}"
        self._clear_live_line()
        self._write(line)
        self._last_len = _dwidth(line)

    def finish(self, status: str, detail: str = "") -> None:
        """Close the current step with ``ok``/``warn``/``fail``/``skip``."""
        glyphs = {
            "ok": (GLYPH_OK, _GREEN),
            "warn": (GLYPH_WARN, _YELLOW),
            "fail": (GLYPH_FAIL, _RED),
            "skip": (GLYPH_SKIP, _DIM),
        }
        glyph, code = glyphs.get(status, (GLYPH_OK, _GREEN))
        duration = self._clock() - self._start if self._active else 0.0
        self._active = False
        if self._mode == "quiet":
            return
        if self._mode == "live":
            self._clear_live_line()
            line = f"{paint(glyph, code, enabled=self._color)} {self._title}"
            if detail:
                line = f"{line} — {detail}"
            line = f"{line} ({format_duration(duration)})"
            self._write(line + "\n")
            return
        self._write(
            format_plain_step(duration, glyph, self._title, detail, duration) + "\n"
        )

    def warn(self, text: str) -> None:
        """Emit an immediate ``⚠`` line (a no-op in quiet mode)."""
        if self._mode == "quiet":
            return
        if self._mode == "live":
            self._clear_live_line()
            self._write(f"{paint(GLYPH_WARN, _YELLOW, enabled=self._color)} {text}\n")
            self._last_len = 0
            return
        self._write(f"{GLYPH_WARN} {text}\n")

    def note(self, text: str) -> None:
        """Emit a verbatim detail line (used for ``-v`` subprocess output)."""
        if self._mode == "quiet":
            return
        if self._mode == "live":
            self._clear_live_line()
            self._write(text + "\n")
            self._last_len = 0
            return
        self._write(text + "\n")


__all__ = [
    "GLYPH_FAIL",
    "GLYPH_OK",
    "GLYPH_PENDING",
    "GLYPH_SKIP",
    "GLYPH_WARN",
    "PROMPT_TEXT",
    "SCHEMA_VERSION",
    "SPINNER_FRAMES",
    "Progress",
    "format_duration",
    "format_elapsed",
    "format_plain_step",
    "paint",
    "pipeline_steps",
    "plan_document",
    "read_confirmation",
    "render_dev_success",
    "render_failure_block",
    "render_json",
    "render_noop_line",
    "render_plan_panel",
    "render_prereq_line",
    "render_pypi_success",
    "render_summary_line",
    "render_sync_report",
    "render_warning_lines",
    "shorten_home",
    "sync_document",
    "tail_lines",
]
