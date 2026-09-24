"""Bounded off-thread size probe for Files spread decisions."""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass

from rich.cells import cell_len

from sase.ace.tui.graphics.images import is_supported_image_path
from sase.media_types import is_supported_video_path

_FILE_TEXT_CACHE_MAX_ENTRIES = 32
_file_text_cache: OrderedDict[tuple[str, float, int], str] = OrderedDict()


@dataclass(frozen=True, slots=True)
class FilesSpreadPage:
    """One Files page's probed text used for spread rendering."""

    slot: str
    label: str
    text: str
    lexer: str


@dataclass(frozen=True, slots=True)
class FilesSpreadProbe:
    """Result of probing Files pages for a spread decision."""

    pages: tuple[FilesSpreadPage, ...]
    total_rows: int | None
    has_solo: bool
    exceeded: bool
    bound: float


def _cached_file_text(path: str) -> str | None:
    try:
        expanded = os.path.expanduser(path)
        stat = os.stat(expanded)
        key = (os.path.abspath(expanded), stat.st_mtime, stat.st_size)
    except Exception:
        return None
    cached = _file_text_cache.get(key)
    if cached is not None:
        _file_text_cache.move_to_end(key)
        return cached
    return None


def _store_file_text(path: str, text: str) -> None:
    try:
        expanded = os.path.expanduser(path)
        stat = os.stat(expanded)
        key = (os.path.abspath(expanded), stat.st_mtime, stat.st_size)
    except Exception:
        return
    _file_text_cache[key] = text
    _file_text_cache.move_to_end(key)
    if len(_file_text_cache) > _FILE_TEXT_CACHE_MAX_ENTRIES:
        _file_text_cache.popitem(last=False)


def _read_bounded_lines(path: str, *, stop_after_rows: float, width: int) -> str | None:
    expanded = os.path.expanduser(path)
    try:
        stat = os.stat(expanded)
        cache_key = (os.path.abspath(expanded), stat.st_mtime, stat.st_size)
        cached = _file_text_cache.get(cache_key)
        if cached is not None:
            _file_text_cache.move_to_end(cache_key)
            # Still bound the returned text so huge cached files stay bounded.
            lines = cached.split("\n")
            kept: list[str] = []
            rows = 0
            for line in lines:
                rows += max(1, (cell_len(line) + max(1, width) - 1) // max(1, width))
                kept.append(line)
                if rows > stop_after_rows + 10:
                    break
            return "\n".join(kept)
    except Exception:
        return None
    try:
        kept_lines: list[str] = []
        rows = 0
        with open(expanded, encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.rstrip("\n")
                kept_lines.append(line)
                rows += max(1, (cell_len(line) + max(1, width) - 1) // max(1, width))
                if rows > stop_after_rows + 10:
                    break
        text = "\n".join(kept_lines)
        try:
            _store_file_text(path, text)
        except Exception:
            pass
        return text
    except Exception:
        return None


def _read_commit_slot_text(
    agent: object, slot: str, *, bound: float, width: int
) -> str | None:
    """Return bounded commit-diff text for ``slot``, or None when unknown."""
    try:
        from sase.ace.tui.widgets.file_panel._messages import commit_slot_index
        from sase.ace.tui.widgets.prompt_panel._agent_commits import agent_commit_diffs

        index = commit_slot_index(slot)
        diffs = agent_commit_diffs(agent)  # type: ignore[arg-type]
        if index < 0 or index >= len(diffs):
            return ""
        diff_path = diffs[index].diff_path
        return _read_bounded_lines(diff_path, stop_after_rows=bound, width=width)
    except Exception:
        return ""


def _commit_slot_label(agent: object, slot: str) -> str:
    try:
        from sase.ace.tui.widgets.file_panel._messages import commit_slot_index
        from sase.ace.tui.widgets.prompt_panel._agent_commits import agent_commit_diffs

        index = commit_slot_index(slot)
        diffs = agent_commit_diffs(agent)  # type: ignore[arg-type]
        if 0 <= index < len(diffs):
            info = diffs[index]
            label = " ".join(part for part in (info.repo_name, info.short_sha) if part)
            if label:
                return label
    except Exception:
        pass
    return "commit diff"


def _read_linked_slot_text(agent: object, slot: str) -> str | None:
    try:
        from sase.ace.tui.widgets.file_panel._linked_deltas import (
            get_cached_linked_delta_groups,
        )
        from sase.ace.tui.widgets.file_panel._messages import linked_slot_repo_name

        repo_name = linked_slot_repo_name(slot)
        for group in get_cached_linked_delta_groups(agent):  # type: ignore[arg-type]
            if group.repo_name == repo_name:
                return group.diff_text or ""
    except Exception:
        pass
    return ""


def _linked_slot_label(agent: object, slot: str) -> str:
    try:
        from sase.ace.tui.widgets.file_panel._linked_deltas import (
            get_cached_linked_delta_groups,
        )
        from sase.ace.tui.widgets.file_panel._messages import linked_slot_repo_name

        repo_name = linked_slot_repo_name(slot)
        for group in get_cached_linked_delta_groups(agent):  # type: ignore[arg-type]
            if group.repo_name == repo_name:
                kind = getattr(group, "kind", "linked")
                glyph = "◆" if kind == "external" else "▣"
                return f"{glyph} {repo_name}"
        return f"▣ {repo_name}"
    except Exception:
        return slot


def estimate_wrapped_rows(text: str, *, width: int, gutter: int = 0) -> int:
    """Estimate rendered rows for ``text`` at ``width`` with a gutter."""
    content_width = max(1, int(width) - int(gutter))
    if not text:
        return 0
    total = 0
    for line in text.split("\n"):
        total += max(1, (cell_len(line) + content_width - 1) // content_width)
    return total


def probe_files_spread(
    agent: object,
    slots: tuple[str, ...],
    *,
    width: int,
    stop_after_rows: float,
    text_cache: dict[str, str] | None = None,
    slot_text: dict[str, str] | None = None,
    slot_kind: dict[str, str] | None = None,
) -> FilesSpreadProbe:
    """Probe Files pages without rendering, stopping once past the bound."""
    from sase.ace.tui.widgets.file_panel._messages import (
        _LIVE_DIFF_SENTINEL,
        file_cache,
        get_cache_key,
        is_commit_slot,
        is_linked_slot,
    )

    bound = float(stop_after_rows)
    pages: list[FilesSpreadPage] = []
    total = 0
    # Separator overhead is accounted per page after the first (2 rows).
    for index, slot in enumerate(slots):
        # Solo cards force paged: image/video anywhere in the deck.
        expanded: str | None = None
        if slot == _LIVE_DIFF_SENTINEL:
            pass
        elif is_commit_slot(slot):
            pass
        elif is_linked_slot(slot):
            pass
        else:
            expanded = os.path.expanduser(slot)
            try:
                if is_supported_image_path(expanded) or is_supported_video_path(
                    expanded
                ):
                    return FilesSpreadProbe(
                        pages=tuple(pages),
                        total_rows=None,
                        has_solo=True,
                        exceeded=False,
                        bound=bound,
                    )
            except Exception:
                pass
        text: str | None = None
        lexer = "diff"
        label = slot
        if slot_text is not None and slot in slot_text:
            text = slot_text[slot]
            kind = (slot_kind or {}).get(slot, "diff")
            lexer = kind
            label = slot
        elif slot == _LIVE_DIFF_SENTINEL:
            try:
                entry = file_cache.get(get_cache_key(agent))  # type: ignore[arg-type]
                text = entry.diff_output if entry is not None else None
            except Exception:
                text = None
            lexer = "diff"
            label = "diff"
            if not text:
                text = ""
        elif is_commit_slot(slot):
            # Commit diffs: read the persisted diff file when resolvable.
            if text_cache is not None and slot in text_cache:
                text = text_cache[slot]
            else:
                text = _read_commit_slot_text(agent, slot, bound=bound, width=width)
                if text is None:
                    text = ""
            lexer = "diff"
            label = _commit_slot_label(agent, slot)
        elif is_linked_slot(slot):
            if text_cache is not None and slot in text_cache:
                text = text_cache[slot]
            else:
                text = _read_linked_slot_text(agent, slot)
                if text is None:
                    text = ""
            lexer = "diff"
            label = _linked_slot_label(agent, slot)
        else:
            # Plain path: bounded read cached by (path, mtime, size).
            cached_text = _cached_file_text(slot)
            if cached_text is not None:
                text = cached_text
            else:
                text = _read_bounded_lines(
                    slot, stop_after_rows=bound, width=max(1, width)
                )
                if text is None:
                    text = ""
            # Lexer from extension.
            _, ext = os.path.splitext(expanded or slot)
            from sase.ace.tui.widgets.file_panel._messages import (
                _EXTENSION_TO_LEXER,
            )

            lexer = _EXTENSION_TO_LEXER.get(ext.lower(), "text")
            label = os.path.basename(os.path.expanduser(slot)) or slot
        body = text or ""
        # Header rows: header + blank line; linked banner may be two lines.
        header_rows = 2
        if is_linked_slot(slot):
            header_rows = 3 if "\n" in body[:200] else 2
        body_rows = estimate_wrapped_rows(body, width=max(1, width), gutter=0)
        page_rows = header_rows + body_rows
        if index > 0:
            page_rows += 2
        total += page_rows
        pages.append(FilesSpreadPage(slot=slot, label=label, text=body, lexer=lexer))
        if total > bound:
            return FilesSpreadProbe(
                pages=tuple(pages),
                total_rows=total,
                has_solo=False,
                exceeded=True,
                bound=bound,
            )
    return FilesSpreadProbe(
        pages=tuple(pages),
        total_rows=total,
        has_solo=False,
        exceeded=False,
        bound=bound,
    )


__all__ = [
    "FilesSpreadPage",
    "FilesSpreadProbe",
    "estimate_wrapped_rows",
    "probe_files_spread",
]
