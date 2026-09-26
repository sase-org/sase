"""Tag-aware helpers over the core ``project_tag`` bindings (D3/D4)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.xprompt.vcs_project_completion import VcsProjectTrigger


class ProjectTagError(RuntimeError):
    """Raised when a prompt's project tags fail launch validation (D3)."""


def _scan_binding() -> Any:
    from sase.core.rust import require_rust_binding

    return require_rust_binding("project_tag_scan")


def _expand_binding() -> Any:
    from sase.core.rust import require_rust_binding

    return require_rust_binding("project_tag_expand")


def _trigger_binding() -> Any:
    from sase.core.rust import require_rust_binding

    return require_rust_binding("project_tag_trigger")


def _apply_selection_binding() -> Any:
    from sase.core.rust import require_rust_binding

    return require_rust_binding("project_tag_apply_selection")


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def find_project_tags(text: str) -> list[dict[str, object]]:
    """Return core scan spans for ``+<project>`` tags in *text* (D1).

    Short-circuits to ``[]`` when ``"+"`` is not in the text. Offsets are
    Python code-point offsets.
    """

    if "+" not in text:
        return []
    spans = _scan_binding()(text)
    return [dict(span) for span in spans]


def _catalog_wire_targets(
    projects_dir: Path | str | None,
) -> tuple[Any, list[dict[str, object]]]:
    from sase.project_tags.catalog import load_project_tag_catalog

    catalog = load_project_tag_catalog(projects_dir)
    return catalog, catalog.wire_targets()


def expand_project_tags(
    text: str,
    projects_dir: Path | str | None = None,
) -> str:
    """Rewrite resolved ``+<project>`` tags to ``#<workflow>:<key>`` (D4).

    Only resolved tags whose target has a workflow type are rewritten, to
    ``#<workflow_type>:<key>``. Never raises for unknown tags; policy (D3)
    belongs to :func:`validate_project_tags_for_launch`. Short-circuits
    when ``"+"`` is not in the text.
    """

    if "+" not in text:
        return text
    _, wire_targets = _catalog_wire_targets(projects_dir)
    expansion = _expand_binding()(text, wire_targets)
    return str(expansion["text"])


def expand_project_tags_with_catalog(text: str, catalog: Any) -> str:
    """Rewrite resolved ``+<project>`` tags using a loaded snapshot (D4).

    Same policy as :func:`expand_project_tags` but takes a previously
    loaded snapshot, so render and keystroke paths can expand with
    :func:`~sase.project_tags.catalog.peek_project_tag_catalog` and fall
    back to the unexpanded text (never build) when the catalog is cold.
    """

    if "+" not in text:
        return text
    wire_targets = catalog.wire_targets()
    expansion = _expand_binding()(text, wire_targets)
    return str(expansion["text"])


def expand_project_tags_report(
    text: str,
    projects_dir: Path | str | None = None,
) -> dict[str, object]:
    """Return the core expansion ``{text, tags}`` report for *text*."""

    if "+" not in text:
        return {"text": text, "tags": []}
    _, wire_targets = _catalog_wire_targets(projects_dir)
    expansion = _expand_binding()(text, wire_targets)
    return {"text": str(expansion["text"]), "tags": list(expansion["tags"])}


def _vcs_ref_span_ranges(text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` ranges of VCS workflow refs in *text*."""

    from sase.xprompt import find_vcs_workflow_tag_span

    ranges: list[tuple[int, int]] = []
    masked = text
    while True:
        span = find_vcs_workflow_tag_span(masked)
        if span is None:
            return ranges
        start, end = span
        ranges.append((start, end))
        masked = masked[:start] + (" " * (end - start)) + masked[end:]


def _alt_group_spans(text: str) -> list[tuple[int, int, list[str]]]:
    """Return ``(start, end, branches)`` for each top-level ``%{...}`` group."""

    groups: list[tuple[int, int, list[str]]] = []
    index = 0
    while True:
        open_at = text.find("%{", index)
        if open_at == -1:
            return groups
        depth = 0
        cursor = open_at
        while cursor < len(text):
            if text.startswith("%{", cursor):
                depth += 1
                cursor += 2
            elif text[cursor] == "}":
                depth -= 1
                cursor += 1
                if depth == 0:
                    break
            else:
                cursor += 1
        if depth != 0:
            return groups
        inner = text[open_at + 2 : cursor - 1]
        groups.append((open_at, cursor, inner.split("|")))
        index = cursor


def _mask_ranges(text: str, ranges: list[tuple[int, int]]) -> str:
    """Blank *ranges* in *text* with spaces, preserving offsets."""

    chars = list(text)
    for start, end in ranges:
        for offset in range(start, min(end, len(chars))):
            chars[offset] = " "
    return "".join(chars)


def _unit_ranges(text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` ranges of top-level ``---`` launch units."""

    try:
        from sase.xprompt._parsing_vcs_tags import split_frontmatter_block
        from sase.xprompt._prompt_segments import split_prompt_segments
    except ImportError:
        return [(0, len(text))]
    try:
        frontmatter, body = split_frontmatter_block(text)
        pieces, separators = split_prompt_segments(body)
    except Exception:  # noqa: BLE001 - validation degrades to whole-text.
        return [(0, len(text))]
    base = len(frontmatter)
    ranges: list[tuple[int, int]] = []
    cursor = base
    for position, piece in enumerate(pieces):
        start = cursor
        end = start + len(piece)
        ranges.append((start, end))
        cursor = end
        if position < len(separators):
            cursor += len(separators[position])
    return ranges


def _unknown_tag_message(
    text: str, name: str, start: int, suggestions: list[str], known: list[str]
) -> str:
    line = _line_of(text, start)
    message = f"Unknown project tag +{name} (line {line})."
    if suggestions:
        if len(suggestions) == 1:
            message += f" Did you mean {suggestions[0]}?"
        else:
            *rest, last = suggestions
            message += f" Did you mean {', '.join(rest)}, or {last}?"
    if known:
        message += f" Known: {' '.join(known)}"
    return message


def validate_project_tags_for_launch(
    text: str,
    projects_dir: Path | str | None = None,
    *,
    _alt_depth: int = 0,
) -> None:
    """Validate ``+<project>`` tags in *text* for launch (D3).

    Raises :class:`ProjectTagError` with the D3 launch-behavior messages.
    Unknown, unanchored tags are plain text and never raise. Alt fan-out
    branches (``%{a | b}``) and ``---`` segments are future launch units, so
    the one-target rule applies within each of them, not across the whole
    text. Short-circuits when ``"+"`` is not in the text.
    """

    if "+" not in text:
        return
    from sase.project_tags.catalog import load_project_tag_catalog

    catalog = load_project_tag_catalog(projects_dir)
    validate_project_tags_with_catalog(text, catalog, _alt_depth=_alt_depth)


def validate_project_tags_with_catalog(
    text: str,
    catalog: Any,
    *,
    _alt_depth: int = 0,
) -> None:
    """Validate ``+<project>`` tags in *text* against a catalog (D3).

    Same policy as :func:`validate_project_tags_for_launch` but takes a
    previously loaded snapshot, so render and keystroke paths can validate
    with :func:`~sase.project_tags.catalog.peek_project_tag_catalog` and
    skip validation (never build) when the catalog is cold.
    """

    if "+" not in text:
        return
    wire_targets = catalog.wire_targets()
    expansion = _expand_binding()(text, wire_targets)
    tags = list(expansion["tags"])
    known = catalog.known_tags()

    for tag in tags:
        name = str(tag["name"])
        anchored = bool(tag["anchored"])
        resolution = dict(tag["resolution"])
        kind = str(resolution.get("kind"))
        if kind == "resolved":
            target = catalog.target(int(resolution["target_index"]))
            if target.state == "disabled":
                raise ProjectTagError(
                    f"`+{name}` is disabled — `sase project enable {target.name}`"
                )
            if target.workflow_type is None:
                workspace = target.workspace_dir or target.key
                raise ProjectTagError(
                    f"`+{name}` has no VCS provider — workspace "
                    f"'{workspace}' is not claimed by any provider plugin"
                )
        elif kind == "ambiguous":
            candidates = [catalog.target(i) for i in resolution["candidates"]]
            names = ", ".join(f"`+{c.name}`" for c in candidates)
            raise ProjectTagError(
                f"Project tag `+{name}` is ambiguous: {names}. "
                "Run `sase doctor` to resolve the collision"
            )
        else:  # unknown
            if not anchored:
                continue
            suggestions = [str(s) for s in resolution.get("suggestions", [])]
            raise ProjectTagError(
                _unknown_tag_message(text, name, int(tag["start"]), suggestions, known)
            )

    # One-target rule (D3): tags and VCS refs count together within each
    # future launch unit. Alt groups fan out to separate units, so their
    # contents are masked here and each branch is validated on its own.
    alt_groups = _alt_group_spans(text) if _alt_depth == 0 else []
    alt_ranges = [(start, end) for start, end, _ in alt_groups]
    masked = _mask_ranges(text, alt_ranges)
    try:
        ref_ranges = _vcs_ref_span_ranges(masked) if "#" in masked else []
    except (ImportError, ValueError):
        ref_ranges = []
    except Exception:  # noqa: BLE001 - validation degrades to tag-only.
        ref_ranges = []
    in_alt = {
        offset
        for start, end in alt_ranges
        for offset in range(start, min(end, len(text)))
    }

    def _in_range(offset: int, start: int, end: int) -> bool:
        return start <= offset < end

    for unit_start, unit_end in _unit_ranges(masked):
        unit_targets: list[str] = []
        for tag in tags:
            if dict(tag["resolution"]).get("kind") != "resolved":
                continue
            start = int(tag["start"])
            if start in in_alt or not _in_range(start, unit_start, unit_end):
                continue
            unit_targets.append(f"`+{tag['name']}`")
            if len(unit_targets) > 1:
                raise ProjectTagError(
                    "Only one workspace target is allowed per launch unit, "
                    f"found {unit_targets[0]} and {unit_targets[1]}"
                )
        for start, end in ref_ranges:
            if not _in_range(start, unit_start, unit_end):
                continue
            ref = masked[start:end]
            if unit_targets:
                raise ProjectTagError(
                    "Only one workspace target is allowed per launch unit, "
                    f"found {unit_targets[0]} and `{ref}`"
                )
            unit_targets.append(f"`{ref}`")
            if len(unit_targets) > 1:
                raise ProjectTagError(
                    "Only one workspace target is allowed per launch unit, "
                    f"found {unit_targets[0]} and {unit_targets[1]}"
                )

    for _, _, branches in alt_groups:
        for branch in branches:
            if "+" in branch:
                validate_project_tags_with_catalog(
                    branch, catalog, _alt_depth=_alt_depth + 1
                )


def project_tag_for(key_or_ref: str) -> str:
    """Return the ``+<project>`` spelling for *key_or_ref*.

    Falls back to the ``#<workflow>:<name>`` form when the project's name
    is not in the tag grammar, and to the input unchanged when the project
    is unknown. Accepts one leading ``+`` on the input.
    """

    from sase.project_tags.catalog import load_project_tag_catalog

    needle = key_or_ref.strip()
    if needle.startswith("+"):
        needle = needle[1:]
    if not needle:
        return key_or_ref
    try:
        catalog = load_project_tag_catalog()
    except Exception:  # noqa: BLE001 - generators degrade to the input.
        return key_or_ref
    folded = needle.casefold()
    for target in catalog.targets:
        candidates = [target.key, target.name, *target.aliases]
        if any(c.casefold() == folded for c in candidates):
            if target.tag is not None:
                return target.tag
            if target.vcs_ref is not None:
                return target.vcs_ref
            return key_or_ref
    return key_or_ref


def known_project_tag_for(catalog: Any, key_or_ref: str) -> str | None:
    """Return the tag/``#<workflow>:`` spelling for a known catalog target.

    Matches *key_or_ref* (one leading ``+`` tolerated) against the catalog's
    directory keys, display names, and aliases, case-insensitively. Returns
    the ``+<project>`` tag, or the ``#<workflow>:<name>`` ref when the name
    is not in the tag grammar, or ``None`` when no target matches. Unlike
    :func:`project_tag_for`, unknown names never gain a ``+`` spelling, so
    Patch names and typos fall through to the caller's ``#`` fallback.
    """

    needle = key_or_ref.strip()
    if needle.startswith("+"):
        needle = needle[1:]
    if not needle:
        return None
    folded = needle.casefold()
    for target in catalog.targets:
        candidates = [target.key, target.name, *target.aliases]
        if any(c.casefold() == folded for c in candidates):
            if target.tag is not None:
                return target.tag
            if target.vcs_ref is not None:
                return target.vcs_ref
            return None
    return None


def find_project_tag_trigger(text: str, cursor: int) -> VcsProjectTrigger | None:
    """Detect a live ``+query`` completion trigger at *cursor* (D1/D7).

    Delegates to the core ``project_tag_trigger`` binding, which owns the
    left-boundary rule (start of text, whitespace, ``{``, or ``|``). Offsets
    are Python code-point offsets. Returns the shared
    :class:`~sase.xprompt.vcs_project_completion.VcsProjectTrigger`, or
    ``None`` when no trigger applies.
    """

    if cursor < 0 or cursor > len(text):
        return None
    result = _trigger_binding()(text, cursor)
    if result is None:
        return None
    from sase.xprompt.vcs_project_completion import VcsProjectTrigger

    return VcsProjectTrigger(
        start=int(result["start"]),
        end=int(result["end"]),
        query=str(result["query"]),
    )


def apply_project_tag_selection(
    text: str,
    trigger_span: tuple[int, int],
    insertion: str,
    projects_dir: Path | str | None = None,
) -> tuple[str, int]:
    """Apply an accepted completion row to *text* via the core binding (D7).

    *insertion* is the row's text verbatim — a project row passes
    ``+<name> `` (or ``#<workflow>:<name> `` when the name is not in the
    tag grammar) and a PR row passes ``#<workflow>:<patch> ``. The typed
    trigger is removed and the row lands at the earliest existing
    workspace target in the trigger's ``---`` segment, or at that
    segment's leading project-tag position when it has no target; every
    other workspace target in the segment is removed, so picking a
    project always leaves exactly one. Returns ``(new_text, cursor)``
    with a Python code-point cursor just past the insertion.
    """

    from sase.project_tags.catalog import load_project_tag_catalog
    from sase.workspace_provider import get_workflow_names

    catalog = load_project_tag_catalog(projects_dir)
    applied = _apply_selection_binding()(
        text,
        trigger_span,
        insertion,
        sorted(get_workflow_names()),
        catalog.wire_targets(),
    )
    return str(applied["text"]), int(applied["cursor"])


def effective_vcs_workflow_tag(prompt: str) -> str | None:
    """Return the leading VCS tag for *prompt*, resolving tags first."""

    if "+" in prompt:
        try:
            prompt = expand_project_tags(prompt)
        except Exception:  # noqa: BLE001 - fall back to the raw prompt.
            pass
    from sase.xprompt import extract_vcs_workflow_tag

    return extract_vcs_workflow_tag(prompt)


def effective_find_vcs_workflow_tag(prompt: str) -> str | None:
    """Return the first VCS tag in *prompt*, resolving tags first."""

    if "+" in prompt:
        try:
            prompt = expand_project_tags(prompt)
        except Exception:  # noqa: BLE001 - fall back to the raw prompt.
            pass
    from sase.xprompt import find_vcs_workflow_tag

    return find_vcs_workflow_tag(prompt)


def effective_vcs_workflow_tag_with_catalog(
    prompt: str, catalog: Any | None
) -> str | None:
    """Snapshot-only :func:`effective_vcs_workflow_tag` for UI-thread paths.

    Never loads or revalidates the catalog: a ``None`` (cold) catalog skips
    tag expansion and falls back to the raw ``#`` extraction.
    """

    if catalog is not None and "+" in prompt:
        try:
            prompt = expand_project_tags_with_catalog(prompt, catalog)
        except Exception:  # noqa: BLE001 - fall back to the raw prompt.
            pass
    from sase.xprompt import extract_vcs_workflow_tag

    return extract_vcs_workflow_tag(prompt)


def effective_find_vcs_workflow_tag_with_catalog(
    prompt: str, catalog: Any | None
) -> str | None:
    """Snapshot-only :func:`effective_find_vcs_workflow_tag` (never loads)."""

    if catalog is not None and "+" in prompt:
        try:
            prompt = expand_project_tags_with_catalog(prompt, catalog)
        except Exception:  # noqa: BLE001 - fall back to the raw prompt.
            pass
    from sase.xprompt import find_vcs_workflow_tag

    return find_vcs_workflow_tag(prompt)


__all__ = [
    "ProjectTagError",
    "apply_project_tag_selection",
    "effective_find_vcs_workflow_tag",
    "effective_find_vcs_workflow_tag_with_catalog",
    "effective_vcs_workflow_tag",
    "effective_vcs_workflow_tag_with_catalog",
    "expand_project_tags",
    "expand_project_tags_report",
    "expand_project_tags_with_catalog",
    "find_project_tag_trigger",
    "find_project_tags",
    "known_project_tag_for",
    "project_tag_for",
    "validate_project_tags_for_launch",
    "validate_project_tags_with_catalog",
]
