"""Rewrite wait/resume references after a dismissal rename.

When a live agent name like ``foo`` becomes ``260428.foo`` on dismissal,
every dependent agent's wait/resume reference must follow or the
``wait_checks`` lumberjack chop will block forever and ``#resume:foo``
will fail to resolve. This module supplies one canonical mapping helper
plus the structured-data and prompt-text rewrites that consume it.

The prompt-text rewrites mirror the recognized directive forms parsed by
:mod:`sase.xprompt.directives` (``%wait``, ``%w``, ``#resume``) and skip
fenced code blocks plus ``%xprompts_enabled:false``-marked regions so
inline examples stay untouched. ``#resume_by_chat`` takes a path
argument, not an agent name, and is left alone.

The end state is canonical rewrites: every reference points at the
post-dismissal name. Phase 4 reverses the mapping when an agent is
revived (``YYmmdd.foo`` → ``foo``) and reuses the same helpers in
reverse.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
from sase.xprompt._disabled_regions import (
    protect_disabled_regions,
    unprotect_disabled_regions,
)
from sase.xprompt._fenced_blocks import (
    protect_fenced_blocks,
    unprotect_fenced_blocks,
)
from sase.xprompt._parsing import find_matching_paren_for_args, parse_args

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent


# ---------------------------------------------------------------------------
# Prompt-text rewrites
# ---------------------------------------------------------------------------

# ``#resume:`` and ``#resume(`` argument forms. Mirrors the matcher in
# ``sase.history.chat`` but is intentionally narrower — ``#resume_by_chat``
# names a chat file path and must not be rewritten by an agent-name map.
_RESUME_REF_RE = re.compile(
    r"#resume(?![A-Za-z0-9_])"
    r"(?:"
    r":(`[^`]+`|[^\s,)]+)"  # group 1: colon arg
    r"|"
    r"\((`[^`]+`|[^)]+)\)"  # group 2/3: paren arg
    r")"
)


def _rewrite_wait_directives(text: str, name_map: dict[str, str]) -> str:
    """Rewrite ``%wait``/``%w`` argument names according to *name_map*.

    Multiple comma-separated names in a single directive are supported;
    only names present in *name_map* are rewritten, the rest are kept
    verbatim. Backtick-quoted single names and parenthesized argument
    lists are both handled. Fenced code blocks and disabled regions are
    left untouched so prompt examples stay readable.
    """
    if not name_map or "%" not in text:
        return text

    fenced: list[str] = []
    protected = protect_fenced_blocks(text, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    spans = _find_wait_spans(protected)
    if not spans:
        return text

    rewritten = protected
    for span_start, span_end, prefix, args, paren, backtick in reversed(spans):
        new_args = [name_map.get(a, a) for a in args]
        if new_args == args:
            continue
        rewritten = (
            rewritten[:span_start]
            + _build_wait_directive(prefix, new_args, paren=paren, backtick=backtick)
            + rewritten[span_end:]
        )

    rewritten = unprotect_disabled_regions(rewritten, disabled)
    return unprotect_fenced_blocks(rewritten, fenced)


def _rewrite_resume_directives(text: str, name_map: dict[str, str]) -> str:
    """Rewrite ``#resume:`` / ``#resume(<name>)`` arguments via *name_map*.

    Backtick-quoted forms are preserved. ``#resume_by_chat`` references a
    chat-file path and is intentionally left alone.
    """
    if not name_map or "#resume" not in text:
        return text

    fenced: list[str] = []
    protected = protect_fenced_blocks(text, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    def _replace(match: re.Match[str]) -> str:
        colon_arg = match.group(1)
        paren_arg = match.group(2)
        if colon_arg is not None:
            new = _rewrite_single_arg(colon_arg, name_map)
            return f"#resume:{new}" if new != colon_arg else match.group(0)
        if paren_arg is not None:
            new = _rewrite_single_arg(paren_arg, name_map)
            return f"#resume({new})" if new != paren_arg else match.group(0)
        return match.group(0)

    rewritten = _RESUME_REF_RE.sub(_replace, protected)
    rewritten = unprotect_disabled_regions(rewritten, disabled)
    return unprotect_fenced_blocks(rewritten, fenced)


def _rewrite_directive_text(text: str, name_map: dict[str, str]) -> str:
    """Rewrite both ``%wait``/``%w`` and ``#resume`` references via *name_map*."""
    text = _rewrite_wait_directives(text, name_map)
    return _rewrite_resume_directives(text, name_map)


def _rewrite_single_arg(raw_arg: str, name_map: dict[str, str]) -> str:
    """Map a single directive argument, preserving backtick quoting."""
    if raw_arg.startswith("`") and raw_arg.endswith("`"):
        inner = raw_arg[1:-1]
        replacement = name_map.get(inner)
        return f"`{replacement}`" if replacement is not None else raw_arg
    return name_map.get(raw_arg, raw_arg)


def _find_wait_spans(
    text: str,
) -> list[tuple[int, int, str, list[str], bool, bool]]:
    """Return wait-directive spans plus their decoded argument list.

    Each tuple is ``(start, end, prefix, args, paren, backtick)`` where
    ``prefix`` is the literal directive token (``%w`` or ``%wait``) so
    the rewriter can reuse the user's chosen alias, and ``backtick`` is
    true when the source used the backtick-quoted single-arg form.
    """
    spans: list[tuple[int, int, str, list[str], bool, bool]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, text, re.MULTILINE):
        raw_name = match.group(1)
        resolved = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
        if resolved != "wait":
            continue

        prefix = f"%{raw_name}"
        has_paren = match.group(2) is not None
        colon_arg = match.group(3)

        if has_paren:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(text, paren_start)
            if paren_end is None:
                continue
            paren_content = text[paren_start + 1 : paren_end]
            positional, _ = parse_args(paren_content)
            args = list(positional)
            spans.append((match.start(), paren_end + 1, prefix, args, True, False))
        elif colon_arg is not None:
            backtick = colon_arg.startswith("`") and colon_arg.endswith("`")
            if backtick:
                args = [colon_arg[1:-1]]
            else:
                args = [seg for seg in colon_arg.split(",") if seg]
            spans.append((match.start(), match.end(), prefix, args, False, backtick))
        # Bare ``%wait`` (no arg) carries no name to rewrite.
    return spans


def _build_wait_directive(
    prefix: str, args: list[str], *, paren: bool, backtick: bool
) -> str:
    """Render a wait directive with the rewritten args.

    Preserves the source quoting style: paren form re-emits as
    ``%w(a, b, c)``; backtick-quoted single-arg colons keep the
    backticks; otherwise we emit ``%w:a,b,c``.
    """
    if paren:
        return f"{prefix}({', '.join(args)})"
    if backtick and len(args) == 1:
        return f"{prefix}:`{args[0]}`"
    return f"{prefix}:{','.join(args)}"


# ---------------------------------------------------------------------------
# Structured-data rewrites
# ---------------------------------------------------------------------------


def _rewrite_artifact_json_files(artifact_dir: Path, name_map: dict[str, str]) -> bool:
    """Update wait references inside an artifact directory's JSON markers.

    Touches ``agent_meta.json`` (``wait_for``), ``waiting.json``
    (``waiting_for``), and ``ready.json`` (``resolved_deps``). Returns
    ``True`` when at least one file was rewritten so the caller can log
    or batch persistence.
    """
    if not name_map:
        return False
    changed = False
    for filename, key in (
        ("agent_meta.json", "wait_for"),
        ("waiting.json", "waiting_for"),
        ("ready.json", "resolved_deps"),
    ):
        if _rewrite_name_list_in_json(artifact_dir / filename, key, name_map):
            changed = True
    return changed


def _rewrite_artifact_prompt(artifact_dir: Path, name_map: dict[str, str]) -> bool:
    """Rewrite wait/resume directives inside ``raw_xprompt.md``."""
    if not name_map:
        return False
    path = artifact_dir / "raw_xprompt.md"
    try:
        original = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return False
    rewritten = _rewrite_directive_text(original, name_map)
    if rewritten == original:
        return False
    try:
        path.write_text(rewritten, encoding="utf-8")
    except OSError:
        return False
    return True


def _rewrite_name_list_in_json(path: Path, key: str, name_map: dict[str, str]) -> bool:
    """Apply *name_map* to a list of names stored under ``data[key]``."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    raw = data.get(key)
    if not isinstance(raw, list):
        return False
    new_list = [name_map.get(n, n) if isinstance(n, str) else n for n in raw]
    if new_list == raw:
        return False
    data[key] = new_list
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def rewrite_dismissed_references(
    name_map: dict[str, str],
    in_memory_agents: Iterable[Agent] | None = None,
) -> None:
    """Rewrite every persisted/in-memory wait+resume reference for *name_map*.

    Walks ``~/.sase/projects/*/artifacts/ace-run/<ts>/`` updating the
    structured wait markers and the agent's ``raw_xprompt.md`` directive
    references in place. Also mutates ``Agent.waiting_for`` for any
    in-memory agents passed in so the optimistic dismiss flow doesn't have
    to wait for the next disk reload before the new names take effect.
    Errors during a single artifact directory are swallowed — the
    next ``wait_checks`` chop will surface anything that didn't apply.
    """
    if not name_map:
        return

    projects_dir = Path.home() / ".sase" / "projects"
    if projects_dir.is_dir():
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            ace_run_dir = project_dir / "artifacts" / "ace-run"
            if not ace_run_dir.is_dir():
                continue
            for artifact_dir in ace_run_dir.iterdir():
                if not artifact_dir.is_dir():
                    continue
                _rewrite_artifact_json_files(artifact_dir, name_map)
                _rewrite_artifact_prompt(artifact_dir, name_map)

    if in_memory_agents:
        for agent in in_memory_agents:
            if not agent.waiting_for:
                continue
            new_waiting = [name_map.get(n, n) for n in agent.waiting_for]
            if new_waiting != agent.waiting_for:
                agent.waiting_for = new_waiting
