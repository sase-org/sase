"""Prompt-preview token detection, resolution, and properties helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.ace.tui.widgets.file_panel._messages import _EXTENSION_TO_LEXER
from sase.ace.tui.widgets.prompt_panel._file_path_hints import (
    file_hint_match_span,
    iter_file_path_matches,
    resolve_file_path,
)
from sase.xprompt import xprompt_inspect
from sase.xprompt._parsing_references import XPromptReference, iter_xprompt_references
from sase.content_layout import skill_reference_name
from sase.xprompt.loader import get_xprompt_or_workflow
from sase.xprompt.models import UNSET, InputArg, XPrompt
from sase.xprompt.properties import XPromptProperties, xprompt_properties
from sase.xprompt.workflow_models import Workflow, WorkflowStep

PreviewKind = Literal["xprompt", "file"]
PreviewDefaultView = Literal["source", "rendered"]

_MAX_PREVIEW_READ_BYTES = 512_000
_BINARY_SNIFF_BYTES = 8192
_SYNTHETIC_CONFIG_SOURCE_IDS = frozenset(
    {
        "config",
        "local_config",
        "default_config",
    }
)
_SYNTHETIC_CONFIG_SOURCE_PREFIXES = (
    "config_overlay:",
    "project_local_config:",
    "plugin_config:",
)


@dataclass(frozen=True, slots=True)
class PreviewToken:
    """A syntactically previewable token under the prompt cursor."""

    kind: PreviewKind
    raw: str
    target: str
    start: int
    end: int
    reference_prefix: Literal["#", "/"] | None = None


@dataclass(frozen=True, slots=True)
class PreviewPayload:
    """Resolved content and metadata for the preview modal."""

    kind_label: str
    icon: str
    title: str
    source_path: str | None
    content: str
    lexer: str
    reference: str | None = None
    default_view: PreviewDefaultView = "source"
    properties: XPromptProperties | None = None


class PreviewError(Exception):
    """User-facing preview failure."""


def _cursor_in_shorthand_argument_text(ref: XPromptReference, offset: int) -> bool:
    start = ref.shorthand_text_start
    return start is not None and start <= offset < ref.end


def _preview_token_from_xprompt_reference(ref: XPromptReference) -> PreviewToken:
    return PreviewToken(
        kind="xprompt",
        raw=ref.raw,
        target=ref.name,
        start=ref.start,
        end=ref.end,
    )


def detect_preview_target_at_cursor(
    text: str,
    cursor_offset: int,
    *,
    known_skills: frozenset[str] = frozenset(),
) -> PreviewToken | None:
    """Return the xprompt or file token under *cursor_offset*, if any."""
    offset = max(0, min(cursor_offset, len(text)))

    if known_skills and "/" in text:
        for span in xprompt_inspect.tokenize(text, known_skills=known_skills):
            if span.kind == "skill" and span.start <= offset < span.end:
                raw = text[span.start : span.end]
                return PreviewToken(
                    kind="xprompt",
                    raw=raw,
                    target=raw[1:],
                    start=span.start,
                    end=span.end,
                    reference_prefix="/",
                )

    for ref in iter_xprompt_references(text):
        if ref.start <= offset < ref.end:
            if _cursor_in_shorthand_argument_text(ref, offset):
                continue
            return _preview_token_from_xprompt_reference(ref)

    for match in iter_file_path_matches(text):
        at_prefix = match.group(1)
        target = match.group(2)
        start, end = file_hint_match_span(match)
        if start <= offset < end:
            if (
                not at_prefix
                and target.startswith("/")
                and "/" not in target[1:]
                and target[1:] in known_skills
            ):
                # A known skill in a protected region is intentionally not
                # actionable; do not reinterpret it as an absolute file.
                continue
            return PreviewToken(
                kind="file",
                raw=text[start:end],
                target=target,
                start=start,
                end=end,
            )

    return None


def detect_shorthand_argument_owner_at_cursor(
    text: str, cursor_offset: int
) -> PreviewToken | None:
    """Return the xprompt whose ``: ``/``:: `` argument text holds the cursor."""
    offset = max(0, min(cursor_offset, len(text)))
    owner: XPromptReference | None = None
    for ref in iter_xprompt_references(text):
        if not _cursor_in_shorthand_argument_text(ref, offset):
            continue
        if owner is None or ref.start > owner.start:
            owner = ref
    if owner is None:
        return None
    return _preview_token_from_xprompt_reference(owner)


def is_slash_skill_candidate_at_cursor(text: str, cursor_offset: int) -> bool:
    """Return whether a cold catalog could hide a slash skill at the cursor.

    The file matcher identifies the only ambiguous spelling (an absolute,
    single-component path), then the shared syntax inspector rechecks the
    slash-skill boundaries and protected-region rules.  This stays purely
    lexical so callers can defer for a catalog warm without touching disk.
    """
    offset = max(0, min(cursor_offset, len(text)))
    for match in iter_file_path_matches(text):
        if match.group(1):
            continue
        target = match.group(2)
        if not target.startswith("/") or "/" in target[1:]:
            continue
        start = match.start(2)
        end = match.end(2)
        if not (start <= offset < end):
            continue
        name = target[1:]
        return any(
            span.kind == "skill"
            and span.start == start
            and span.end == end
            and span.start <= offset < span.end
            for span in xprompt_inspect.tokenize(
                text,
                known_skills=frozenset({name}),
            )
        )
    return False


def resolve_preview_target(
    token: PreviewToken,
    *,
    project: str | None,
    base_dir: str,
) -> PreviewPayload:
    """Resolve *token* to preview content, raising :class:`PreviewError`."""
    if token.kind == "xprompt":
        return _resolve_xprompt_preview(token, project=project)
    return _resolve_file_preview(token, base_dir=base_dir)


def _resolve_xprompt_preview(
    token: PreviewToken,
    *,
    project: str | None,
) -> PreviewPayload:
    reference = _xprompt_reference(token)
    slash_skill = reference.startswith("/")
    # ``/foo`` is the provider skill name; its definition lives under the
    # canonical ``skill/foo`` xprompt reference.
    lookup = skill_reference_name(token.target) if slash_skill else token.target
    obj = get_xprompt_or_workflow(lookup, project=project)
    if obj is None:
        if slash_skill:
            raise PreviewError(f"No skill named '{reference}' found")
        raise PreviewError(f"No xprompt or skill named '{reference}' found")

    if slash_skill and (not isinstance(obj, XPrompt) or not obj.skill):
        raise PreviewError(f"No skill named '{reference}' found")

    if isinstance(obj, XPrompt):
        kind_label = "skill" if obj.skill else "xprompt"
        fallback_content = _xprompt_fallback_preview(obj)
        fallback_lexer = "markdown"
        source_id = obj.source_path
    elif isinstance(obj, Workflow):
        kind_label = "workflow"
        fallback_content = _workflow_fallback_preview(obj)
        fallback_lexer = "markdown"
        source_id = obj.source_path
    else:
        raise PreviewError(f"Could not preview '{reference}'")

    source_path = _source_display_path(source_id)
    source_preview = _read_source_preview(source_id)
    if source_preview is not None:
        content, source_path, lexer = source_preview
    else:
        content = fallback_content
        lexer = fallback_lexer

    return PreviewPayload(
        kind_label=kind_label,
        icon=reference[0],
        title=reference,
        source_path=source_path,
        content=content,
        lexer=lexer,
        properties=_resolve_xprompt_properties(
            obj,
            reference=reference,
            kind=kind_label,
            project=project,
            source_id=source_id,
            definition_path=source_path,
        ),
    )


def _resolve_xprompt_properties(
    obj: XPrompt | Workflow,
    *,
    reference: str,
    kind: str,
    project: str | None,
    source_id: str | None,
    definition_path: str | None,
) -> XPromptProperties | None:
    source_bucket: str | None = None
    if source_id is not None:
        try:
            from sase.ace.tui.modals.xprompt_browser_helpers import classify_source

            source_bucket = classify_source(source_id)[0]
        except Exception:
            source_bucket = None
    try:
        return xprompt_properties(
            obj,
            reference=reference,
            kind=kind,
            project=project,
            source_bucket=source_bucket,
            definition_path=definition_path,
        )
    except Exception:
        return None


def _xprompt_reference(token: PreviewToken) -> str:
    prefix = token.reference_prefix
    if prefix is None:
        prefix = "/" if token.raw.startswith("/") else "#"
    return f"{prefix}{token.target}"


def _resolve_file_preview(
    token: PreviewToken,
    *,
    base_dir: str,
) -> PreviewPayload:
    resolved = Path(resolve_file_path(token.target, base_dir)).expanduser()
    if not resolved.exists():
        raise PreviewError(f"File not found: {token.target}")
    if resolved.is_dir():
        raise PreviewError(f"'{token.target}' is a directory, not a file")
    if not resolved.is_file():
        raise PreviewError(f"Cannot preview non-file path: {token.target}")

    content = _read_text_file(resolved, display_path=token.target)
    return PreviewPayload(
        kind_label="file",
        icon="@",
        title=token.raw,
        source_path=str(resolved),
        content=content,
        lexer=_lexer_for_path(resolved),
    )


def _read_source_preview(source_path: str | None) -> tuple[str, str, str] | None:
    path = _source_file_for_preview(source_path)
    if path is None:
        return None
    try:
        content = _read_text_file(path, display_path=str(path))
    except PreviewError:
        return None
    return (content, str(path), _lexer_for_path(path))


def _source_file_for_preview(source_path: str | None) -> Path | None:
    if source_path is None:
        return None
    if source_path in _SYNTHETIC_CONFIG_SOURCE_IDS:
        return None
    if source_path.startswith(_SYNTHETIC_CONFIG_SOURCE_PREFIXES):
        return None

    try:
        from sase.ace.tui.modals.xprompt_browser_helpers import (
            resolve_source_to_file_path,
        )

        resolved = resolve_source_to_file_path(source_path)
    except Exception:
        resolved = None
    candidate = resolved or source_path
    path = Path(candidate).expanduser()
    if path.is_file():
        return path
    return None


def _source_display_path(source_path: str | None) -> str | None:
    if source_path is None:
        return None
    try:
        from sase.ace.tui.modals.xprompt_browser_helpers import (
            resolve_source_to_file_path,
        )

        resolved = resolve_source_to_file_path(source_path)
    except Exception:
        resolved = None
    if resolved:
        return str(Path(resolved).expanduser())
    try:
        from sase.ace.tui.modals.xprompt_browser_helpers import classify_source

        _category, display_path, _editable = classify_source(source_path)
    except Exception:
        display_path = ""
    return display_path or source_path


def _read_text_file(path: Path, *, display_path: str) -> str:
    try:
        with path.open("rb") as fh:
            data = fh.read(_MAX_PREVIEW_READ_BYTES + 1)
    except OSError as exc:
        raise PreviewError(f"Could not read file: {display_path}") from exc

    if b"\x00" in data[:_BINARY_SNIFF_BYTES]:
        raise PreviewError(f"Cannot preview binary file: {display_path}")

    truncated = len(data) > _MAX_PREVIEW_READ_BYTES
    if truncated:
        data = data[:_MAX_PREVIEW_READ_BYTES]
    content = data.decode("utf-8", errors="replace")
    if truncated:
        content += f"\n\n[Preview truncated at {_MAX_PREVIEW_READ_BYTES:,} bytes]\n"
    return content


def _lexer_for_path(path: Path) -> str:
    return _EXTENSION_TO_LEXER.get(path.suffix.lower(), "text")


def _xprompt_fallback_preview(xprompt: XPrompt) -> str:
    inputs = [inp for inp in xprompt.inputs if not inp.is_step_input]
    has_input_descriptions = any(inp.description for inp in inputs)
    if not xprompt.description and not has_input_descriptions:
        return xprompt.content

    lines: list[str] = [f"# XPrompt: {xprompt.name}", ""]
    if xprompt.description:
        lines.extend([xprompt.description, ""])
    if inputs:
        lines.append("## Inputs")
        lines.extend(_input_preview_lines(inputs))
        lines.append("")
    lines.extend(["## Content", xprompt.content])
    return "\n".join(lines)


def _workflow_fallback_preview(workflow: Workflow) -> str:
    if workflow.is_simple_xprompt():
        content = workflow.get_prompt_part_content()
        inputs = [inp for inp in workflow.inputs if not inp.is_step_input]
        has_input_descriptions = any(inp.description for inp in inputs)
        if not workflow.description and not has_input_descriptions:
            return content

        lines: list[str] = [f"# XPrompt: {workflow.name}", ""]
        if workflow.description:
            lines.extend([workflow.description, ""])
        if inputs:
            lines.append("## Inputs")
            lines.extend(_input_preview_lines(inputs))
            lines.append("")
        lines.extend(["## Content", content])
        return "\n".join(lines)

    workflow_lines: list[str] = [f"# Workflow: {workflow.name}", ""]
    if workflow.description:
        workflow_lines.extend([workflow.description, ""])

    inputs = [inp for inp in workflow.inputs if not inp.is_step_input]
    if inputs:
        workflow_lines.append("## Inputs")
        workflow_lines.extend(_input_preview_lines(inputs))
        workflow_lines.append("")

    workflow_lines.append("## Steps")
    for index, step in enumerate(workflow.steps, 1):
        step_type, step_label = _workflow_step_preview(step)
        workflow_lines.append(f"{index}. [{step_type}] {step.name}: {step_label}")
    return "\n".join(workflow_lines)


def _workflow_step_preview(step: WorkflowStep) -> tuple[str, str]:
    if step.agent is not None:
        return ("agent", _first_line(step.agent))
    if step.bash is not None:
        return ("bash", _first_line(step.bash))
    if step.python is not None:
        return ("python", _first_line(step.python))
    if step.prompt_part is not None:
        return ("prompt_part", _first_line(step.prompt_part))
    if step.parallel_config is not None:
        return ("parallel", f"{len(step.parallel_config.steps)} nested step(s)")
    return ("unknown", "?")


def _first_line(value: str) -> str:
    line = value.splitlines()[0] if value.splitlines() else value
    return line[:50]


def _input_preview_lines(inputs: list[InputArg]) -> list[str]:
    return [
        f"- **{inp.name}**: {inp.type.value}{_default_suffix(inp)}"
        f"{_description_suffix(inp)}"
        for inp in inputs
    ]


def _default_suffix(inp: InputArg) -> str:
    if inp.default is UNSET:
        return ""
    if inp.default is None:
        return " (default: null)"
    return f" (default: {inp.default})"


def _description_suffix(inp: InputArg) -> str:
    return f" - {inp.description}" if inp.description else ""


__all__ = [
    "PreviewError",
    "PreviewPayload",
    "PreviewToken",
    "detect_preview_target_at_cursor",
    "detect_shorthand_argument_owner_at_cursor",
    "is_slash_skill_candidate_at_cursor",
    "resolve_preview_target",
]
