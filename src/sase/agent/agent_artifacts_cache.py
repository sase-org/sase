"""Per-process cache for agent artifact reads (Phase 6 of the TUI perf plan).

The agent prompt panel re-globs and re-reads several artifact files (prompt
selection, raw xprompt, response, chat response, timestamped reply chunks,
live reply) every time the user navigates between agents — even when the
underlying files haven't changed. This module memoizes those reads keyed by
``(path, mtime_ns, size)`` so re-selecting the same agent reuses parsed
content. Live-reply reads use ``TailCache`` to read only newly-appended
bytes when the file grows.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from threading import Lock


def _stat_signature(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


@dataclass
class TailCache:
    """Tracks an append-only file so each refresh reads only new bytes."""

    path: str
    size: int = 0
    offset: int = 0
    text: str = ""

    def read(self) -> str | None:
        """Return the current file content using cached tail data when possible.

        Returns None when the file does not exist. Re-reads from scratch
        when the file shrinks (e.g. truncated/rotated).
        """
        try:
            current_size = os.path.getsize(self.path)
        except OSError:
            return None

        if current_size < self.size:
            self.size = 0
            self.offset = 0
            self.text = ""

        if current_size == self.size:
            return self.text

        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                appended = f.read()
        except OSError:
            return None

        try:
            decoded = appended.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            decoded = appended.decode("utf-8", errors="replace")

        self.text = self.text + decoded
        self.size = current_size
        self.offset = current_size
        return self.text


@dataclass(frozen=True)
class _PromptSelectionKey:
    artifacts_dir: str
    is_workflow_child: bool
    step_name: str | None


@dataclass
class _PromptSelectionEntry:
    dir_signature: tuple[tuple[str, int], ...]
    selected_path: str | None


@dataclass
class AgentArtifactCache:
    """Memoizes per-file artifact reads across re-selects.

    Each cached value is keyed by file ``(path, mtime_ns, size)`` so when a
    file changes only its slot misses; unrelated artifacts stay cached.
    """

    _prompt_selection: dict[_PromptSelectionKey, _PromptSelectionEntry] = field(
        default_factory=dict
    )
    _file_text: dict[str, tuple[tuple[int, int], str]] = field(default_factory=dict)
    _json_data: dict[str, tuple[tuple[int, int], object]] = field(default_factory=dict)
    _reply_chunks: dict[
        str, tuple[tuple[tuple[int, int], tuple[int, int]], list[tuple[str, str]]]
    ] = field(default_factory=dict)
    _tail_caches: dict[str, TailCache] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def select_prompt_file(
        self,
        artifacts_dir: str,
        *,
        is_workflow_child: bool,
        step_name: str | None,
    ) -> str | None:
        """Pick the prompt file path for an agent, cached by directory listing.

        Mirrors the logic in ``get_prompt_content``: glob ``*_prompt.md``,
        narrow workflow-children to ``-{step_name}_prompt.md`` matches, then
        select the most-recently-modified entry. Cache invalidates when the
        ``(path, mtime_ns)`` of any candidate changes.
        """
        try:
            entries = os.listdir(artifacts_dir)
        except OSError:
            return None

        candidates: list[tuple[str, int]] = []
        for entry in entries:
            if not entry.endswith("_prompt.md"):
                continue
            full = os.path.join(artifacts_dir, entry)
            try:
                st = os.stat(full)
            except OSError:
                continue
            candidates.append((full, st.st_mtime_ns))

        if not candidates:
            return None

        sig = tuple(sorted(candidates))
        key = _PromptSelectionKey(
            artifacts_dir=artifacts_dir,
            is_workflow_child=is_workflow_child,
            step_name=step_name,
        )
        with self._lock:
            cached = self._prompt_selection.get(key)
            if cached is not None and cached.dir_signature == sig:
                return cached.selected_path

        if is_workflow_child and step_name:
            suffix = f"-{step_name}_prompt.md"
            filtered = [c for c in candidates if c[0].endswith(suffix)]
            if filtered:
                candidates = filtered

        candidates.sort(key=lambda item: item[1], reverse=True)
        selected = candidates[0][0]

        with self._lock:
            self._prompt_selection[key] = _PromptSelectionEntry(
                dir_signature=sig, selected_path=selected
            )
        return selected

    def read_text(self, path: str) -> str | None:
        """Return file content cached by ``(path, mtime_ns, size)``."""
        sig = _stat_signature(path)
        if sig is None:
            with self._lock:
                self._file_text.pop(path, None)
            return None

        with self._lock:
            cached = self._file_text.get(path)
            if cached is not None and cached[0] == sig:
                return cached[1]

        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return None

        with self._lock:
            self._file_text[path] = (sig, content)
        return content

    def read_json(self, path: str) -> object | None:
        """Return parsed JSON content cached by ``(path, mtime_ns, size)``."""
        sig = _stat_signature(path)
        if sig is None:
            with self._lock:
                self._json_data.pop(path, None)
            return None

        with self._lock:
            cached = self._json_data.get(path)
            if cached is not None and cached[0] == sig:
                return cached[1]

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

        with self._lock:
            self._json_data[path] = (sig, data)
        return data

    def read_reply_chunks(
        self, timestamps_path: str, reply_path: str
    ) -> list[tuple[str, str]] | None:
        """Return ``(timestamp, content)`` chunks cached jointly by both files.

        Recomputes only when either file's signature changes.
        """
        ts_sig = _stat_signature(timestamps_path)
        if ts_sig is None:
            return None
        reply_sig = _stat_signature(reply_path)
        if reply_sig is None:
            return None

        joint = (ts_sig, reply_sig)
        with self._lock:
            cached = self._reply_chunks.get(timestamps_path)
            if cached is not None and cached[0] == joint:
                return list(cached[1])

        try:
            with open(timestamps_path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return None

        entries: list[tuple[int, str]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                entries.append((data["byte_offset"], data["timestamp"]))
            except (json.JSONDecodeError, KeyError):
                continue
        if not entries:
            return None

        try:
            with open(reply_path, "rb") as f:
                content_bytes = f.read()
        except OSError:
            return None

        chunks: list[tuple[str, str]] = []
        for i, (offset, timestamp) in enumerate(entries):
            end = entries[i + 1][0] if i + 1 < len(entries) else len(content_bytes)
            chunk_text = content_bytes[offset:end].decode("utf-8", errors="replace")
            chunks.append((timestamp, chunk_text))

        if not chunks:
            return None

        with self._lock:
            self._reply_chunks[timestamps_path] = (joint, chunks)
        return list(chunks)

    def read_live_reply(self, reply_path: str) -> str | None:
        """Return the live-reply content using a per-path ``TailCache``."""
        with self._lock:
            tail = self._tail_caches.get(reply_path)
            if tail is None:
                tail = TailCache(path=reply_path)
                self._tail_caches[reply_path] = tail
        return tail.read()

    def tail_cache_for(self, reply_path: str) -> TailCache:
        """Expose the underlying TailCache for tests and tail-based callers."""
        with self._lock:
            tail = self._tail_caches.get(reply_path)
            if tail is None:
                tail = TailCache(path=reply_path)
                self._tail_caches[reply_path] = tail
        return tail

    def invalidate_path(self, path: str) -> None:
        """Drop any cached state tied to ``path``."""
        with self._lock:
            self._file_text.pop(path, None)
            self._json_data.pop(path, None)
            self._reply_chunks.pop(path, None)
            self._tail_caches.pop(path, None)

    def clear(self) -> None:
        with self._lock:
            self._prompt_selection.clear()
            self._file_text.clear()
            self._json_data.clear()
            self._reply_chunks.clear()
            self._tail_caches.clear()


_GLOBAL_CACHE = AgentArtifactCache()


def get_global_cache() -> AgentArtifactCache:
    """Return the process-wide artifact cache used by the TUI."""
    return _GLOBAL_CACHE
