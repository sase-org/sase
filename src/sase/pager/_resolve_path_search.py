"""Filesystem and git probing for pager file-path links."""

from __future__ import annotations

import os
import re
import select
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from sase.pager.link_context import LinkResolutionContext

_LINE_COL_SUFFIX_RE = re.compile(r"(.+):(\d+):(\d+)$")
_LINE_SUFFIX_RE = re.compile(r"(.+):(\d+)$")
_TRAILING_LINE_DIGITS_RE = re.compile(r":\d+$")
_NUMBERED_CHECKOUT_RE = re.compile(r"^.+_\d+$")
_DIFF_PREFIXES = ("a/", "b/")
_GIT_LS_FILES_TIMEOUT_SECONDS = 2.0
_GIT_LS_FILES_MAX_BYTES = 1_048_576

_GitLsFilesCache = dict[Path, tuple[str, ...] | None]
_PathConsider = Callable[[Path], Path | None]


def search_existing_path(
    text: str,
    *,
    context: LinkResolutionContext,
    cache: _GitLsFilesCache | None = None,
) -> tuple[Path | None, int | None, int | None, str | None, int]:
    """Return ``(path, line, column, fragment, locations_probed)`` for the first hit."""
    git_cache: _GitLsFilesCache = {} if cache is None else cache
    probed: list[Path] = []
    seen: set[Path] = set()

    def consider(path: Path) -> Path | None:
        resolved = _resolved_path(path)
        if resolved not in seen:
            seen.add(resolved)
            probed.append(resolved)
        if resolved.exists():
            return resolved
        return None

    candidates = path_candidates(text)
    for path_text, line, column, fragment in candidates:
        found = _probe_direct(path_text, context, consider)
        if found is not None:
            return found, line, column, fragment, len(probed)
    for path_text, line, column, fragment in candidates:
        needle = _suffix_needle(path_text, context)
        if needle is None:
            continue
        found = _unique_suffix_hit(needle, context, git_cache, consider)
        if found is not None:
            return found, line, column, fragment, len(probed)
    return None, None, None, None, len(probed)


def _probe_direct(
    path_text: str,
    context: LinkResolutionContext,
    consider: _PathConsider,
) -> Path | None:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        found = consider(path)
        if found is not None:
            return found
        remainder = _stale_absolute_remainder(path, context)
        if remainder is None:
            return None
        for base in context.base_dirs:
            found = consider(base / remainder)
            if found is not None:
                return found
        return None
    for base in context.base_dirs:
        found = consider(base / path)
        if found is not None:
            return found
    return None


def _unique_suffix_hit(
    needle: str,
    context: LinkResolutionContext,
    cache: _GitLsFilesCache,
    consider: _PathConsider,
) -> Path | None:
    hits: list[Path] = []
    seen: set[Path] = set()
    for anchor in context.anchors:
        for tracked in _cached_git_ls_files(anchor.directory, cache):
            if not _is_suffix_match(tracked, needle):
                continue
            resolved = _resolved_path(anchor.directory / tracked)
            if resolved in seen:
                continue
            seen.add(resolved)
            hits.append(resolved)
    if len(hits) != 1:
        return None
    return consider(hits[0])


def path_candidates(
    text: str,
) -> tuple[tuple[str, int | None, int | None, str | None], ...]:
    seen: set[str] = set()
    candidates: list[tuple[str, int | None, int | None, str | None]] = []
    for variant in _candidate_texts(text):
        path_text, line, column, fragment = _split_target_suffix(variant)
        key = f"{path_text}#{fragment}" if fragment is not None else path_text
        if not path_text or key in seen:
            continue
        seen.add(key)
        candidates.append((path_text, line, column, fragment))
    return tuple(candidates)


def _candidate_texts(text: str) -> tuple[str, ...]:
    variants: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            variants.append(value)

    add(text)
    add(text.rstrip("."))
    for variant in tuple(variants):
        for prefix in _DIFF_PREFIXES:
            if variant.startswith(prefix) and len(variant) > len(prefix):
                add(variant[len(prefix) :])
                break
    return tuple(variants)


def _split_target_suffix(
    text: str,
) -> tuple[str, int | None, int | None, str | None]:
    path_text, fragment = _split_hash_fragment(text)
    path_text, line, column = _split_line_suffix(path_text)
    return path_text, line, column, fragment


def _split_hash_fragment(text: str) -> tuple[str, str | None]:
    if "#" not in text:
        return text, None
    path_text, fragment = text.split("#", 1)
    return path_text, fragment


def _split_line_suffix(text: str) -> tuple[str, int | None, int | None]:
    match = _LINE_COL_SUFFIX_RE.fullmatch(text)
    if match is not None:
        path_text = match.group(1)
        if not _TRAILING_LINE_DIGITS_RE.search(path_text):
            return path_text, int(match.group(2)), int(match.group(3))
    match = _LINE_SUFFIX_RE.fullmatch(text)
    if match is not None:
        path_text = match.group(1)
        if not _TRAILING_LINE_DIGITS_RE.search(path_text):
            return path_text, int(match.group(2)), None
    return text, None, None


def _stale_absolute_remainder(
    path: Path, context: LinkResolutionContext
) -> Path | None:
    resolved = _resolved_path(path)
    anchor_dirs = {_resolved_path(base) for base in context.base_dirs}
    for prefix in (resolved, *resolved.parents):
        numbered = _NUMBERED_CHECKOUT_RE.fullmatch(prefix.name) is not None
        if prefix not in anchor_dirs and not numbered:
            continue
        try:
            return resolved.relative_to(prefix)
        except ValueError:
            continue
    return None


def _suffix_needle(path_text: str, context: LinkResolutionContext) -> str | None:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        remainder = _stale_absolute_remainder(path, context)
        if remainder is None:
            return None
        posix = remainder.as_posix()
    else:
        posix = path.as_posix().lstrip("./")
    if posix in {"", "."} or len(Path(posix).parts) < 2:
        return None
    return posix


def _is_suffix_match(tracked: str, needle: str) -> bool:
    tracked_posix = tracked.replace("\\", "/").lstrip("./")
    needle_posix = needle.replace("\\", "/").lstrip("./")
    if not needle_posix:
        return False
    return tracked_posix == needle_posix or tracked_posix.endswith("/" + needle_posix)


def _cached_git_ls_files(directory: Path, cache: _GitLsFilesCache) -> tuple[str, ...]:
    key = _resolved_path(directory)
    if key not in cache:
        cache[key] = _git_ls_files(key)
    files = cache[key]
    return files if files else ()


def _git_ls_files(directory: Path) -> tuple[str, ...] | None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    proc: subprocess.Popen[bytes] | None = None
    try:
        proc = subprocess.Popen(
            ["git", "-C", str(directory), "ls-files", "-z"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        captured = _capture_bounded_process_output(
            proc,
            max_bytes=_GIT_LS_FILES_MAX_BYTES,
            timeout_seconds=_GIT_LS_FILES_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        if proc is not None:
            _kill_and_reap_process(proc)
        return None
    if captured is None:
        return None
    return tuple(
        chunk.decode("utf-8", "replace") for chunk in captured.split(b"\0") if chunk
    )


def _capture_bounded_process_output(
    proc: subprocess.Popen[bytes],
    *,
    max_bytes: int,
    timeout_seconds: float,
) -> bytes | None:
    """Read *proc* stdout up to *max_bytes*, then wait or kill.

    Output at the limit is kept. One extra byte is a miss: the child is
    killed and the buffer is discarded rather than returned as a partial
    candidate list. Timeout and overflow always reap the child.
    """
    stdout = proc.stdout
    if stdout is None:
        _kill_and_reap_process(proc)
        return None
    deadline = time.monotonic() + timeout_seconds
    chunks: list[bytes] = []
    total = 0
    overflow = False
    timed_out = False
    fd = stdout.fileno()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                timed_out = True
                break
            try:
                chunk = os.read(fd, min(65536, max_bytes - total + 1))
            except OSError:
                break
            if not chunk:
                break
            if total + len(chunk) > max_bytes:
                overflow = True
                break
            chunks.append(chunk)
            total += len(chunk)
    except (OSError, ValueError):
        _kill_and_reap_process(proc)
        return None
    if overflow or timed_out:
        _kill_and_reap_process(proc)
        return None
    returncode = proc.poll()
    if returncode is None:
        remaining = deadline - time.monotonic()
        try:
            returncode = proc.wait(timeout=max(remaining, 0.0))
        except subprocess.TimeoutExpired:
            _kill_and_reap_process(proc)
            return None
    if returncode != 0:
        return None
    return b"".join(chunks)


def _kill_and_reap_process(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.kill()
    stdout = proc.stdout
    if stdout is not None:
        try:
            fd = stdout.fileno()
        except (OSError, ValueError):
            fd = None
        if fd is not None:
            try:
                while True:
                    ready, _, _ = select.select([fd], [], [], 0)
                    if not ready:
                        break
                    if not os.read(fd, 65536):
                        break
            except (OSError, ValueError):
                pass
        try:
            stdout.close()
        except OSError:
            pass
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _resolved_path(path: Path) -> Path:
    expanded = path.expanduser()
    try:
        return expanded.resolve(strict=False)
    except OSError:
        return expanded


__all__ = [
    "_capture_bounded_process_output",
    "_git_ls_files",
    "path_candidates",
    "search_existing_path",
]
