"""File path detection and hint rendering for agent displays."""

import os
import re
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Protocol

from rich.style import StyleType
from rich.text import Text

from sase.ace.tui.util.artifact_ref_syntax import artifact_ref_candidate_ranges
from sase.ace.tui.util.lazy_syntax import PLAIN_RENDER_MAX_BYTES, PLAIN_RENDER_MAX_LINES
from sase.sdd.plan_refs import PLAN_REFERENCE_PREFIX as LOGICAL_PLAN_REFERENCE_PREFIX

_FILE_PATH_ALTERNATIVES = (
    # Absolute paths: /foo/bar or ~/foo/bar
    r"(?:~?/[\w.+\-][\w.+\-/]*)"
    r"|"
    # Relative paths with explicit prefix: ./foo or ../foo
    r"(?:\.{1,2}/[\w.+\-][\w.+\-/]*)"
    r"|"
    # Dot-directory paths: .sase/foo.ext
    r"(?:\.[\w\-]+/[\w.+\-][\w.+\-/]*)"
    r"|"
    # Bare relative paths with extension: dir/file.ext
    r"(?:[\w\-]+/[\w.+\-/]*\.[\w]+)"
)
_FILE_PATH_PATTERN = (
    r"(?<![/\w@.])"  # Not preceded by word char, /, @, or .
    r"(@?)"  # Group 1: optional @ prefix
    r"("  # Group 2: the file path
    f"{_FILE_PATH_ALTERNATIVES}"
    r")"
)
_CONTAINER_FILE_PATH_PATTERN = (
    r"(?<![/\w@.])"  # Not preceded by word char, /, @, or .
    r"(@?)"  # Group 1: optional @ prefix
    r"("  # Group 2: the file path, including an optional logical kind.
    rf"(?:{LOGICAL_PLAN_REFERENCE_PREFIX})?"
    f"(?:{_FILE_PATH_ALTERNATIVES})"
    r")"
)
# Regex to match file paths in text.
# Group 1: optional @ prefix (sase file reference convention)
# Group 2: the actual file path
FILE_PATH_RE = re.compile(_FILE_PATH_PATTERN)
_FILE_PATH_RE = FILE_PATH_RE
HTTP_URL_PATTERN = r"(?<!\w)(?i:https?)://[^\s<>()\[\]{}'\"`]+"
_FILE_PATH_OR_HTTP_URL_RE = re.compile(
    f"(?:{HTTP_URL_PATTERN})|(?:{_FILE_PATH_PATTERN})"
)
_CONTAINER_FILE_PATH_OR_HTTP_URL_RE = re.compile(
    f"(?:{HTTP_URL_PATTERN})|(?:{_CONTAINER_FILE_PATH_PATTERN})"
)


_annotated_char_scopes: list[list[int]] = []


@contextmanager
def annotated_char_scope() -> Generator[list[int], None, None]:
    """Count the characters scanned for hints inside the ``with`` block.

    Yields a one-element list holding the running total; read it after the
    block exits. The count is what a hint render actually paid the regex scan
    for, across every fragment and every family member, which is the size term
    the view-hints trace spans report. Scopes nest, and an inner scope's
    characters also count toward each enclosing scope. Costs nothing when no
    scope is open.
    """
    counter = [0]
    _annotated_char_scopes.append(counter)
    try:
        yield counter
    finally:
        _annotated_char_scopes.remove(counter)


class _AppendableText(Protocol):
    def append(
        self,
        text: str | Text,
        style: StyleType | None = None,
    ) -> object: ...


class FileHintPathResolver(Protocol):
    """Resolve one matched file token before the workspace fallback."""

    def __call__(self, path: str, workspace_dir: str | None) -> str: ...


FileHintMatcher = Callable[[str], Iterator[re.Match[str]]]


@lru_cache(maxsize=256)
def resolve_agent_workspace_dir(
    workspace_num: int | None,
    project_file: str,
    workspace_dir: str | None = None,
) -> str | None:
    """Get workspace directory for an agent.

    Delegates to workspace provider plugins to correctly resolve the
    workspace path for any VCS type (Git, Mercurial, etc.).

    Args:
        workspace_num: Agent's workspace number (None or 0 = no workspace).
        project_file: Path to the project spec file.
        workspace_dir: Explicit workspace directory fallback, primarily for
            directory-mode agents without a managed workspace number.

    Returns:
        Workspace directory path, or None if unavailable.
    """
    explicit_dir = None
    if workspace_dir:
        expanded = os.path.expanduser(workspace_dir)
        if os.path.isdir(expanded):
            explicit_dir = expanded.rstrip("/")

    if workspace_num is None or workspace_num <= 0:
        return explicit_dir

    from pathlib import Path

    from sase.workspace_provider import (
        detect_workflow_type,
        get_workspace_directory,
    )
    from sase.workspace_provider.utils import parse_workspace_dir

    try:
        workflow_type = detect_workflow_type(project_file)
        primary_dir = parse_workspace_dir(project_file) or ""
        project_name = Path(project_file).parent.name
        ws_dir = get_workspace_directory(
            workflow_type, workspace_num, project_name, primary_dir
        )
        ws_dir = ws_dir.rstrip("/")
        if os.path.isdir(ws_dir):
            return ws_dir
    except Exception:
        pass

    return explicit_dir


@lru_cache(maxsize=4_096)
def resolve_file_path(path: str, workspace_dir: str | None) -> str:
    """Resolve a file path to absolute.

    For relative paths, prepends the workspace directory.
    For absolute/home paths, expands and returns directly.
    """
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return expanded
    if workspace_dir:
        return os.path.join(workspace_dir, expanded)
    return os.path.abspath(expanded)


def clear_file_hint_resolution_caches() -> None:
    """Start a fresh bounded memoization scope for one hint render."""
    resolve_agent_workspace_dir.cache_clear()
    resolve_file_path.cache_clear()


def iter_file_path_matches(content: str) -> Generator[re.Match[str], None, None]:
    """Yield file-path matches that are not contained in HTTP(S) URLs."""
    for match in _FILE_PATH_OR_HTTP_URL_RE.finditer(content):
        if match.group(2) is not None:
            yield match


def iter_container_file_path_matches(
    content: str,
) -> Generator[re.Match[str], None, None]:
    """Yield container-hint file matches, including logical ``plan:`` refs."""
    for match in _CONTAINER_FILE_PATH_OR_HTTP_URL_RE.finditer(content):
        if match.group(2) is not None:
            yield match


def iter_xprompt_file_path_matches(content: str) -> Iterator[re.Match[str]]:
    """Yield ordinary file hints, excluding complete typed artifact refs."""
    yield from matches_outside_artifact_refs(content, iter_file_path_matches(content))


def iter_xprompt_container_file_path_matches(content: str) -> Iterator[re.Match[str]]:
    """Yield container file hints, excluding complete typed artifact refs."""
    yield from matches_outside_artifact_refs(
        content,
        iter_container_file_path_matches(content),
    )


def file_hint_match_span(match: re.Match[str]) -> tuple[int, int]:
    """Return the visible token span for a file-hint regex match."""
    return (match.start(1) if match.group(1) else match.start(2), match.end(2))


def has_file_path(content: str) -> bool:
    """Return whether *content* has a file path outside HTTP(S) URLs."""
    return next(iter_file_path_matches(content), None) is not None


def matches_outside_artifact_refs(
    content: str,
    matches: Iterator[re.Match[str]],
) -> Iterator[re.Match[str]]:
    ref_ranges = artifact_ref_candidate_ranges(
        content,
        max_bytes=PLAIN_RENDER_MAX_BYTES,
        max_lines=PLAIN_RENDER_MAX_LINES,
    )
    if not ref_ranges:
        yield from matches
        return

    ref_index = 0
    for match in matches:
        match_start, match_end = file_hint_match_span(match)
        while ref_index < len(ref_ranges) and ref_ranges[ref_index].end <= match_start:
            ref_index += 1
        if ref_index < len(ref_ranges) and ref_ranges[ref_index].start < match_end:
            continue
        yield match


def append_text_with_file_hints(
    text: _AppendableText,
    content: str,
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
    style: str = "",
    *,
    path_resolver: FileHintPathResolver | None = None,
    matcher: FileHintMatcher = iter_file_path_matches,
) -> int:
    """Append text content with ``[N]`` hint markers before file paths.

    Scans *content* for file path patterns, inserts numbered hint markers,
    and populates *hint_mappings* with resolved absolute paths.

    Args:
        text: Rich Text object to append to.
        content: Raw text to scan for file paths.
        hint_counter: Current hint counter (1-based).
        hint_mappings: Dict to populate (hint number -> absolute path).
        workspace_dir: Workspace directory for resolving relative paths.
        style: Default style for non-hint text segments.

    Returns:
        Updated hint counter.
    """
    for counter in _annotated_char_scopes:
        counter[0] += len(content)

    last_end = 0
    for match in matcher(content):
        path = match.group(2)
        full_match_start, full_match_end = file_hint_match_span(match)

        # Append text before this match
        if full_match_start > last_end:
            text.append(content[last_end:full_match_start], style=style)

        # Resolve the path (using group 2, without @ prefix)
        resolved_path = (
            path_resolver(path, workspace_dir)
            if path_resolver is not None
            else resolve_file_path(path, workspace_dir)
        )

        # Add hint marker and styled file path
        text.append(f"[{hint_counter}] ", style="bold #FFFF00")
        text.append(content[full_match_start:full_match_end], style="#87AFFF")

        hint_mappings[hint_counter] = resolved_path
        hint_counter += 1
        last_end = full_match_end

    # Append remaining text after last match (or entire content if no matches)
    if last_end < len(content):
        text.append(content[last_end:], style=style)

    return hint_counter
