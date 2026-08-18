"""Prompt jump-to-definition token detection and resolution helpers."""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.ace.tui.widgets._prompt_preview_target import (
    PreviewToken,
    detect_preview_target_at_cursor,
    detect_shorthand_argument_owner_at_cursor,
)
from sase.ace.tui.widgets.prompt_panel._file_path_hints import (
    file_hint_match_span,
    iter_file_path_matches,
    resolve_file_path,
)
from sase.content_layout import skill_reference_name
from sase.xprompt.loader import get_xprompt_or_workflow
from sase.xprompt.models import XPrompt
from sase.xprompt.workflow_models import Workflow

JumpKind = Literal["xprompt", "file"]

_LINE_COL_SUFFIX_RE = re.compile(r":(?P<line>\d+)(?::(?P<col>\d+))?")
_VIM_FAMILY = frozenset({"vim", "nvim", "vi", "view", "gvim", "mvim", "nv"})
_YAML_SECTION_KEYS = frozenset({"xprompts", "workflows"})


@dataclass(frozen=True, slots=True)
class JumpToken:
    """A syntactically jumpable token under the prompt cursor."""

    kind: JumpKind
    raw: str
    target: str
    line: int | None
    col: int | None
    start: int
    end: int
    reference_prefix: Literal["#", "/"] | None = None


@dataclass(frozen=True, slots=True)
class JumpTarget:
    """Resolved target metadata for a jump-to-definition action."""

    kind_label: str
    icon: str
    title: str
    source_path: str
    line: int | None
    col: int | None
    loadable_markdown: str | None
    definition_name: str | None = None
    source_id: str | None = None
    is_editable: bool = False
    config_path: str | None = None
    config_line: int | None = None
    config_col: int | None = None


class JumpError(Exception):
    """User-facing jump-to-definition failure."""


def detect_jump_target_at_cursor(
    text: str,
    cursor_offset: int,
    *,
    known_skills: frozenset[str] = frozenset(),
) -> JumpToken | None:
    """Return the xprompt or file token under *cursor_offset*, if any."""

    preview_token = detect_preview_target_at_cursor(
        text,
        cursor_offset,
        known_skills=known_skills,
    )
    if preview_token is not None:
        return _jump_token_from_preview_token(text, preview_token)

    return _detect_file_token_suffix_at_cursor(text, cursor_offset)


def detect_shorthand_argument_owner_jump_target(
    text: str, cursor_offset: int
) -> JumpToken | None:
    """Return the jump token for the shorthand xprompt that owns the cursor."""
    preview_token = detect_shorthand_argument_owner_at_cursor(text, cursor_offset)
    if preview_token is None:
        return None
    return _jump_token_from_preview_token(text, preview_token)


def resolve_jump_target(
    token: JumpToken,
    *,
    project: str | None,
    base_dir: str,
) -> JumpTarget:
    """Resolve *token* to a definition file, raising :class:`JumpError`."""

    if token.kind == "xprompt":
        return _resolve_xprompt_jump(token, project=project)
    return _resolve_file_jump(token, base_dir=base_dir)


def build_jump_editor_argv(
    editor: str,
    file_path: str,
    line: int | None,
    col: int | None,
) -> list[str]:
    """Build argv for opening *file_path* in *editor* at an optional cursor."""

    editor_argv = _editor_argv(editor)
    if line is not None and _editor_command_name(editor) in _VIM_FAMILY:
        return [
            *editor_argv,
            "-c",
            f"call cursor({max(1, line)}, {max(1, col or 1)})",
            file_path,
        ]
    return [*editor_argv, file_path]


def _jump_token_from_preview_token(text: str, token: PreviewToken) -> JumpToken:
    line: int | None = None
    col: int | None = None
    raw = token.raw
    end = token.end
    if token.kind == "file":
        suffix = _LINE_COL_SUFFIX_RE.match(text[token.end :])
        if suffix is not None:
            line = int(suffix.group("line"))
            raw += suffix.group(0)
            end += len(suffix.group(0))
            col_group = suffix.group("col")
            if col_group is not None:
                col = int(col_group)

    return JumpToken(
        kind=token.kind,
        raw=raw,
        target=token.target,
        line=line,
        col=col,
        start=token.start,
        end=end,
        reference_prefix=token.reference_prefix,
    )


def _detect_file_token_suffix_at_cursor(
    text: str,
    cursor_offset: int,
) -> JumpToken | None:
    offset = max(0, min(cursor_offset, len(text)))
    for match in iter_file_path_matches(text):
        target = match.group(2)
        start, end = file_hint_match_span(match)
        suffix = _LINE_COL_SUFFIX_RE.match(text[end:])
        if suffix is None:
            continue
        suffix_end = end + len(suffix.group(0))
        if not (start <= offset < suffix_end):
            continue

        col_group = suffix.group("col")
        return JumpToken(
            kind="file",
            raw=text[start:suffix_end],
            target=target,
            line=int(suffix.group("line")),
            col=int(col_group) if col_group is not None else None,
            start=start,
            end=suffix_end,
        )
    return None


def _resolve_xprompt_jump(
    token: JumpToken,
    *,
    project: str | None,
) -> JumpTarget:
    reference = _xprompt_reference(token)
    slash_skill = reference.startswith("/")
    # ``/foo`` is the provider skill name; its definition lives under the
    # canonical ``skill/foo`` xprompt reference.
    lookup = skill_reference_name(token.target) if slash_skill else token.target
    obj = get_xprompt_or_workflow(lookup, project=project)
    if obj is None:
        if slash_skill:
            raise JumpError(f"No skill named '{reference}' found")
        raise JumpError(f"No xprompt or skill named '{reference}' found")

    if slash_skill and (not isinstance(obj, XPrompt) or not obj.skill):
        raise JumpError(f"No skill named '{reference}' found")

    if isinstance(obj, XPrompt):
        kind_label = "skill" if obj.skill else "xprompt"
        source_id = obj.source_path
    elif isinstance(obj, Workflow):
        kind_label = "xprompt" if obj.is_simple_xprompt() else "workflow"
        source_id = obj.source_path
    else:
        raise JumpError(f"Could not jump to '{reference}'")

    source_path = _definition_file_for_source(source_id, reference)
    source_text = _read_text(source_path, reference)
    loadable_markdown = _loadable_markdown(
        source_id,
        source_path,
        source_text,
        name=token.target,
        is_simple=(isinstance(obj, XPrompt) or obj.is_simple_xprompt()),
    )
    if loadable_markdown is not None:
        line = _first_markdown_body_line(source_text)
        col = 1
    else:
        line, col = _definition_line_in_yaml(source_text, token.target)

    return JumpTarget(
        kind_label=kind_label,
        icon=reference[0],
        title=reference,
        source_path=str(source_path),
        line=line,
        col=col,
        loadable_markdown=loadable_markdown,
        definition_name=token.target,
        source_id=source_id,
        is_editable=_source_is_editable(source_id),
    )


def _xprompt_reference(token: JumpToken) -> str:
    prefix = token.reference_prefix
    if prefix is None:
        prefix = "/" if token.raw.startswith("/") else "#"
    return f"{prefix}{token.target}"


def _resolve_file_jump(
    token: JumpToken,
    *,
    base_dir: str,
) -> JumpTarget:
    resolved = Path(resolve_file_path(token.target, base_dir)).expanduser()
    if not resolved.exists():
        raise JumpError(f"File not found: {token.target}")
    if resolved.is_dir():
        raise JumpError(f"'{token.target}' is a directory, not a file")
    if not resolved.is_file():
        raise JumpError(f"Cannot open non-file path: {token.target}")

    return JumpTarget(
        kind_label="file",
        icon="@",
        title=token.raw,
        source_path=str(resolved),
        line=token.line,
        col=token.col,
        loadable_markdown=None,
    )


def _definition_file_for_source(source_path: str | None, reference: str) -> Path:
    if source_path is None:
        raise JumpError(f"No definition file found for {reference}")

    try:
        from sase.ace.tui.modals.xprompt_browser_helpers import (
            resolve_source_to_file_path,
        )

        resolved = resolve_source_to_file_path(source_path)
    except Exception:
        resolved = None

    if not resolved:
        raise JumpError(f"No definition file found for {reference}")

    path = Path(resolved).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    if not path.is_file():
        raise JumpError(f"No definition file found for {reference}")
    return path


def _read_text(path: Path, reference: str) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise JumpError(f"No definition file found for {reference}") from exc


def _loadable_markdown(
    source_id: str | None,
    source_path: Path,
    source_text: str,
    *,
    name: str,
    is_simple: bool,
) -> str | None:
    try:
        from sase.ace.tui.modals.xprompt_browser_helpers import is_yaml_backed_source

        is_yaml = is_yaml_backed_source(source_id)
    except Exception:
        is_yaml = source_path.suffix.lower() in {".yml", ".yaml"}

    if is_yaml and is_simple and _is_config_source(source_id):
        try:
            from sase.xprompt.save import load_config_xprompt_markdown

            return load_config_xprompt_markdown(source_path, name)
        except Exception:
            return None
    if is_yaml or source_path.suffix.lower() != ".md":
        return None
    return source_text


def _is_config_source(source_id: str | None) -> bool:
    if source_id in {"config", "local_config", "default_config"}:
        return True
    return bool(
        source_id
        and source_id.startswith(
            ("config_overlay:", "project_local_config:", "plugin_config:")
        )
    )


def _source_is_editable(source_id: str | None) -> bool:
    try:
        from sase.ace.tui.modals.xprompt_browser_helpers import classify_source

        return classify_source(source_id)[2]
    except Exception:
        return False


def _first_markdown_body_line(source_text: str) -> int:
    lines = source_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return 1
    for index, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            return min(index + 1, len(lines) + 1)
    return 1


def _definition_line_in_yaml(source_text: str, name: str) -> tuple[int, int]:
    active_section_indent: int | None = None
    for line_no, line in enumerate(source_text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))
        key = _yaml_key_name(stripped)
        if key is None:
            continue

        if indent == 0:
            active_section_indent = indent if key in _YAML_SECTION_KEYS else None
            if key == name:
                return (line_no, indent + 1)
            continue

        if (
            active_section_indent is not None
            and indent > active_section_indent
            and key == name
        ):
            return (line_no, indent + 1)

    return (1, 1)


def _yaml_key_name(stripped_line: str) -> str | None:
    if ":" not in stripped_line:
        return None
    raw_key = stripped_line.split(":", 1)[0].strip()
    if not raw_key:
        return None
    if len(raw_key) >= 2 and raw_key[0] == raw_key[-1] and raw_key[0] in {"'", '"'}:
        return raw_key[1:-1]
    return raw_key


def _editor_command_name(editor: str) -> str:
    try:
        command = shlex.split(editor)[0]
    except (ValueError, IndexError):
        command = editor
    return os.path.basename(command)


def _editor_argv(editor: str) -> list[str]:
    try:
        argv = shlex.split(editor)
    except ValueError:
        return [editor]
    return argv or [editor]


__all__ = [
    "JumpError",
    "JumpTarget",
    "JumpToken",
    "build_jump_editor_argv",
    "detect_jump_target_at_cursor",
    "detect_shorthand_argument_owner_jump_target",
    "resolve_jump_target",
]
