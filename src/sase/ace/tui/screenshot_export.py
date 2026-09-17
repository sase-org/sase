"""Request-directory protocol for externally triggered TUI screenshots."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from hashlib import sha256

from sase.core.paths import managed_tmpdir_root

SASE_TUI_SCREENSHOT_DIR_ENV = "SASE_TUI_SCREENSHOT_DIR"

_TMP_SUBDIR = "tui-screenshots"
_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_SCREEN_FILE_RE = re.compile(r"^screen_(\d+)\.(?:svg|done|error|pending)$")


@dataclass(frozen=True)
class ScreenshotExportPaths:
    """File paths for one sequence-numbered screenshot export request."""

    request_dir: Path
    sequence: int
    svg: Path
    done: Path
    error: Path
    pending: Path


def screenshot_request_dir(
    session: str,
    window_name: str,
    *,
    root: Path | str | None = None,
) -> Path:
    """Return the deterministic request directory for a tmux session/window."""
    base = Path(root).expanduser() if root is not None else _screenshot_request_root()
    return base / _safe_component(session) / _safe_component(window_name)


def reserve_export_paths(request_dir: Path | str) -> ScreenshotExportPaths:
    """Atomically reserve the next export sequence in *request_dir*."""
    directory = Path(request_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    start = _next_sequence(directory)
    for sequence in range(start, start + 10000):
        paths = _paths_for_sequence(directory, sequence)
        try:
            fd = os.open(paths.pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()}\n")
        return paths
    raise RuntimeError(f"could not reserve screenshot export sequence in {directory}")


def complete_export(paths: ScreenshotExportPaths, svg: str) -> None:
    """Write *svg* and the completion marker for a reserved export."""
    _atomic_write_text(paths.svg, svg)
    _atomic_write_text(paths.done, f"svg={paths.svg.name}\n")
    _remove_pending(paths)


def fail_export(paths: ScreenshotExportPaths, message: object) -> None:
    """Write an error marker for a reserved export."""
    text = " ".join(str(message).split()) or "unknown screenshot export error"
    _atomic_write_text(paths.error, text + "\n")
    _remove_pending(paths)


def _screenshot_request_root() -> Path:
    return managed_tmpdir_root() / _TMP_SUBDIR


def _safe_component(value: str) -> str:
    raw = value or "unnamed"
    stem = _SAFE_COMPONENT_RE.sub("_", raw.strip()).strip("._-") or "tmux"
    digest = sha256(raw.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
    return f"{stem[:80]}-{digest}"


def _next_sequence(directory: Path) -> int:
    highest = 0
    for child in directory.iterdir():
        match = _SCREEN_FILE_RE.match(child.name)
        if match is not None:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _paths_for_sequence(directory: Path, sequence: int) -> ScreenshotExportPaths:
    stem = f"screen_{sequence}"
    return ScreenshotExportPaths(
        request_dir=directory,
        sequence=sequence,
        svg=directory / f"{stem}.svg",
        done=directory / f"{stem}.done",
        error=directory / f"{stem}.error",
        pending=directory / f"{stem}.pending",
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _remove_pending(paths: ScreenshotExportPaths) -> None:
    try:
        paths.pending.unlink()
    except FileNotFoundError:
        pass
