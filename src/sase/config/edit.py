"""Plan and execute a single config edit.

The *decision* logic — target file, dotted key path, set-vs-unset, the
candidate merged config, the effective-merge preview, and schema validation of
the candidate — is shared domain logic and lives in the Rust core
(``config_plan_edit``). This module wraps that and adds the two Python-only
pieces:

- the **target-file text diff** preview, produced by applying the edit in
  memory with ``ruamel.yaml`` (comment/order/quote preserving) and diffing the
  old vs. new text — no write happens during planning; and
- the **source-preserving write** itself (:func:`apply_config_edit`), which
  writes the exact text the diff previewed to the chezmoi-resolved target.

"Reset to default" is modeled as an ``unset`` of the key in the chosen mutable
scope (the key is deleted, not overwritten with the literal default), so the
lower-priority layer's value — ultimately the schema default — becomes
effective again.

No Textual imports: callable from a worker thread. :func:`apply_config_edit` is
side-effecting and must only run from a tracked background task.
"""

from __future__ import annotations

import copy
import difflib
import re
from collections.abc import MutableMapping
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.config.core import (
    DEPRECATED_TOP_LEVEL_KEYS,
    UNSUPPORTED_TOP_LEVEL_KEYS,
    get_use_chezmoi,
)
from sase.config.inventory import ConfigDiagnostic, ConfigInventory
from sase.config.targets import resolve_write_path
from sase.core.rust import require_rust_binding


if TYPE_CHECKING:
    from ruamel.yaml import YAML


class ConfigEditError(RuntimeError):
    """Raised when a config edit cannot be planned or applied."""


# --- Edit operation -------------------------------------------------------


@dataclass(frozen=True)
class ConfigEditOp:
    """A set/unset operation on a field.

    Use :meth:`set_value` to assign a value or :meth:`unset` to remove the key
    (the latter is also how "reset to default" is expressed).
    """

    kind: str
    value: Any = None

    @classmethod
    def set_value(cls, value: Any) -> ConfigEditOp:
        """An operation that sets the field to *value*."""
        return cls("set", value)

    @classmethod
    def unset(cls) -> ConfigEditOp:
        """An operation that removes the field from the target layer."""
        return cls("unset")

    def to_wire(self) -> dict[str, Any]:
        if self.kind == "unset":
            return {"kind": "unset"}
        return {"kind": "set", "value": self.value}


# --- Source-preserving YAML writer ----------------------------------------


def _yaml() -> YAML:
    """Build a round-trip YAML handler that preserves comments and quotes.

    ``ruamel.yaml`` is imported lazily so merely importing this module (and
    therefore ``sase.config``) stays cheap on every CLI/TUI startup; the cost is
    paid only when a config write is actually planned or executed.
    """
    from ruamel.yaml import YAML

    handler = YAML()
    handler.preserve_quotes = True
    # Match the house style for block sequences when the fallback has to dump
    # the full document.
    handler.indent(mapping=2, sequence=4, offset=2)
    # Avoid ruamel re-wrapping long scalars (e.g. descriptions / paths).
    handler.width = 4096
    return handler


def _dump(handler: YAML, data: Any) -> str:
    buffer = StringIO()
    handler.dump(data, buffer)
    return buffer.getvalue()


@dataclass(frozen=True)
class _MappingFrame:
    node: MutableMapping[Any, Any]
    owner: MutableMapping[Any, Any] | None
    owner_key: str | None


def _set_key_round_trip(text: str, key_path: tuple[str, ...], value: Any) -> str:
    from ruamel.yaml.comments import CommentedMap

    handler = _yaml()
    data = handler.load(text) if text.strip() else None
    if not isinstance(data, MutableMapping):
        data = CommentedMap()
    node: MutableMapping[Any, Any] = data
    for segment in key_path[:-1]:
        child = node.get(segment)
        if not isinstance(child, MutableMapping):
            child = CommentedMap()
            node[segment] = child
        node = child
    node[key_path[-1]] = value
    return _dump(handler, data)


def _unset_key_round_trip(text: str, key_path: tuple[str, ...]) -> str:
    handler = _yaml()
    data = handler.load(text)
    if not isinstance(data, MutableMapping):
        return text
    node: MutableMapping[Any, Any] = data
    for segment in key_path[:-1]:
        child = node.get(segment)
        if not isinstance(child, MutableMapping):
            return text
        node = child
    last = key_path[-1]
    if last not in node:
        return text
    del node[last]
    return _dump(handler, data)


def _is_flow_style(node: Any) -> bool:
    flow_attrib = getattr(node, "fa", None)
    flow_style = getattr(flow_attrib, "flow_style", None)
    return bool(callable(flow_style) and flow_style())


def _is_block_mapping(node: Any) -> bool:
    return isinstance(node, MutableMapping) and not _is_flow_style(node)


def _load_root_mapping(text: str) -> MutableMapping[Any, Any] | None:
    from ruamel.yaml.comments import CommentedMap

    handler = _yaml()
    try:
        data = handler.load(text) if text.strip() else CommentedMap()
    except Exception:
        return None
    if not _is_block_mapping(data):
        return None
    return data


def _key_location(
    node: MutableMapping[Any, Any],
    key: str,
) -> tuple[int, int, int, int] | None:
    data = getattr(getattr(node, "lc", None), "data", None)
    if not isinstance(data, dict):
        return None
    location = data.get(key)
    if not isinstance(location, list | tuple) or len(location) < 4:
        return None
    try:
        return (
            int(location[0]),
            int(location[1]),
            int(location[2]),
            int(location[3]),
        )
    except (TypeError, ValueError):
        return None


def _walk_to_deepest_mapping(
    data: MutableMapping[Any, Any],
    key_path: tuple[str, ...],
) -> tuple[_MappingFrame, int] | None:
    frame = _MappingFrame(data, None, None)
    depth = 0
    for segment in key_path[:-1]:
        if segment not in frame.node:
            return frame, depth
        child = frame.node[segment]
        if not _is_block_mapping(child):
            return None
        frame = _MappingFrame(child, frame.node, segment)
        depth += 1
    return frame, depth


def _preferred_newline(lines: list[str]) -> str:
    for line in lines:
        if line.endswith("\r\n"):
            return "\r\n"
    return "\n"


def _line_without_newline(line: str) -> str:
    return line.rstrip("\r\n")


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _block_end(lines: list[str], start_line: int, indent: int) -> int:
    """Return the first line after a block, excluding trailing blank padding."""
    last_content_end = start_line + 1
    for index in range(start_line + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if stripped and _line_indent(line) <= indent:
            break
        if stripped:
            last_content_end = index + 1
    return last_content_end


def _find_plain_comment(line: str, start: int) -> int | None:
    for index in range(start, len(line)):
        if line[index] == "#" and (index == 0 or line[index - 1].isspace()):
            return index
    return None


def _quoted_scalar_end(line: str, start: int, quote: str) -> int | None:
    index = start + 1
    while index < len(line):
        char = line[index]
        if quote == '"' and char == "\\":
            index += 2
            continue
        if quote == "'" and char == "'" and index + 1 < len(line):
            if line[index + 1] == "'":
                index += 2
                continue
        if char == quote:
            return index + 1
        index += 1
    return None


def _value_span(line: str, value_col: int) -> tuple[int, int, str | None] | None:
    body = _line_without_newline(line)
    if value_col >= len(body):
        return None

    quote_style: str | None = None
    first = body[value_col]
    if first in {"'", '"'}:
        end = _quoted_scalar_end(body, value_col, first)
        if end is None:
            return None
        quote_style = "single" if first == "'" else "double"
        return value_col, end, quote_style

    comment_at = _find_plain_comment(body, value_col)
    end = len(body) if comment_at is None else comment_at
    while end > value_col and body[end - 1].isspace():
        end -= 1
    if end <= value_col:
        return None
    return value_col, end, quote_style


def _is_supported_scalar(value: Any) -> bool:
    from ruamel.yaml.scalarstring import FoldedScalarString, LiteralScalarString

    if isinstance(value, FoldedScalarString | LiteralScalarString):
        return False
    return value is None or isinstance(value, str | int | float | bool)


def _dump_single_line_scalar(value: Any) -> str | None:
    import yaml  # type: ignore[import-untyped]

    dumped = yaml.safe_dump(
        value,
        allow_unicode=True,
        default_flow_style=True,
        sort_keys=False,
    )
    lines = [line for line in dumped.splitlines() if line != "..."]
    if len(lines) != 1:
        return None
    return lines[0]


def _serialize_scalar(value: Any, quote_style: str | None = None) -> str | None:
    if not _is_supported_scalar(value):
        return None
    if isinstance(value, str):
        if "\n" in value or "\r" in value:
            return None
        if quote_style == "single":
            escaped = value.replace("'", "''")
            return f"'{escaped}'"
        if quote_style == "double":
            import json

            return json.dumps(value, ensure_ascii=False)
        return _dump_single_line_scalar(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return _dump_single_line_scalar(value)


_PLAIN_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _serialize_key(key: str) -> str | None:
    if _PLAIN_KEY_RE.match(key):
        return key
    return _serialize_scalar(key)


def _replace_existing_scalar(
    text: str,
    data: MutableMapping[Any, Any],
    key_path: tuple[str, ...],
    value: Any,
) -> str | None:
    walked = _walk_to_deepest_mapping(data, key_path)
    if walked is None:
        return None
    frame, depth = walked
    if depth != len(key_path) - 1:
        return None

    leaf = key_path[-1]
    if leaf not in frame.node:
        return None
    current = frame.node[leaf]
    if not _is_supported_scalar(current):
        return None
    location = _key_location(frame.node, leaf)
    if location is None:
        return None
    key_line, _key_col, value_line, value_col = location
    if key_line != value_line:
        return None

    lines = text.splitlines(keepends=True)
    if value_line >= len(lines):
        return None
    span = _value_span(lines[value_line], value_col)
    if span is None:
        return None
    start, end, quote_style = span
    serialized = _serialize_scalar(value, quote_style)
    if serialized is None:
        return None

    lines[value_line] = (
        f"{lines[value_line][:start]}{serialized}{lines[value_line][end:]}"
    )
    candidate = "".join(lines)
    return candidate if _parsed_edit_matches(text, candidate, key_path, value) else None


def _insert_lines(lines: list[str], insert_at: int, new_lines: list[str]) -> list[str]:
    if not new_lines:
        return lines
    newline = _preferred_newline(lines)
    updated = list(lines)
    if insert_at > 0 and not updated[insert_at - 1].endswith(("\n", "\r")):
        updated[insert_at - 1] = f"{updated[insert_at - 1]}{newline}"
    return updated[:insert_at] + new_lines + updated[insert_at:]


def _child_insert_location(
    lines: list[str],
    frame: _MappingFrame,
) -> tuple[int, int] | None:
    locations = [
        location
        for key in frame.node
        if isinstance(key, str)
        if (location := _key_location(frame.node, key)) is not None
    ]
    if locations:
        last_key_line, child_indent, _value_line, _value_col = max(
            locations, key=lambda item: item[0]
        )
        return _block_end(lines, last_key_line, child_indent), child_indent

    if frame.owner is None:
        return len(lines), 0
    if frame.owner_key is None:
        return None
    owner_location = _key_location(frame.owner, frame.owner_key)
    if owner_location is None:
        return None
    key_line, key_col, _value_line, _value_col = owner_location
    if key_line >= len(lines):
        return None
    return key_line + 1, key_col + 2


def _insert_missing_key(
    text: str,
    data: MutableMapping[Any, Any],
    key_path: tuple[str, ...],
    value: Any,
) -> str | None:
    serialized_value = _serialize_scalar(value)
    if serialized_value is None:
        return None
    walked = _walk_to_deepest_mapping(data, key_path)
    if walked is None:
        return None
    frame, depth = walked
    if depth == len(key_path) - 1 and key_path[-1] in frame.node:
        return None

    lines = text.splitlines(keepends=True)
    location = _child_insert_location(lines, frame)
    if location is None:
        return None
    insert_at, base_indent = location
    newline = _preferred_newline(lines)
    missing_segments = key_path[depth:]
    rendered: list[str] = []
    for index, segment in enumerate(missing_segments):
        key = _serialize_key(segment)
        if key is None:
            return None
        indent = " " * (base_indent + index * 2)
        if index == len(missing_segments) - 1:
            rendered.append(f"{indent}{key}: {serialized_value}{newline}")
        else:
            rendered.append(f"{indent}{key}:{newline}")

    candidate = "".join(_insert_lines(lines, insert_at, rendered))
    return candidate if _parsed_edit_matches(text, candidate, key_path, value) else None


def _try_set_key_surgical(
    text: str, key_path: tuple[str, ...], value: Any
) -> str | None:
    data = _load_root_mapping(text)
    if data is None:
        return None
    replaced = _replace_existing_scalar(text, data, key_path, value)
    if replaced is not None:
        return replaced
    return _insert_missing_key(text, data, key_path, value)


def _delete_key_lines(
    text: str,
    data: MutableMapping[Any, Any],
    key_path: tuple[str, ...],
) -> str | None:
    walked = _walk_to_deepest_mapping(data, key_path)
    if walked is None:
        return None
    frame, depth = walked
    if depth != len(key_path) - 1:
        return text

    leaf = key_path[-1]
    if leaf not in frame.node:
        return text
    location = _key_location(frame.node, leaf)
    if location is None:
        return None
    key_line, key_col, _value_line, _value_col = location
    lines = text.splitlines(keepends=True)
    if key_line >= len(lines):
        return None
    delete_end = _block_end(lines, key_line, key_col)
    candidate = "".join(lines[:key_line] + lines[delete_end:])
    return candidate if _parsed_unset_matches(text, candidate, key_path) else None


def _try_unset_key_surgical(text: str, key_path: tuple[str, ...]) -> str | None:
    data = _load_root_mapping(text)
    if data is None:
        return None
    return _delete_key_lines(text, data, key_path)


def _load_for_compare(text: str) -> Any:
    handler = _yaml()
    if not text.strip():
        return {}
    data = handler.load(text)
    return {} if data is None else data


def _set_path_for_compare(data: Any, key_path: tuple[str, ...], value: Any) -> Any:
    from ruamel.yaml.comments import CommentedMap

    if not isinstance(data, MutableMapping):
        return None
    node = data
    for segment in key_path[:-1]:
        child = node.get(segment)
        if child is None:
            child = CommentedMap()
            node[segment] = child
        elif not isinstance(child, MutableMapping):
            return None
        node = child
    node[key_path[-1]] = value
    return data


def _unset_path_for_compare(data: Any, key_path: tuple[str, ...]) -> Any:
    if not isinstance(data, MutableMapping):
        return None
    node = data
    for segment in key_path[:-1]:
        child = node.get(segment)
        if not isinstance(child, MutableMapping):
            return data
        node = child
    node.pop(key_path[-1], None)
    return data


def _path_exists(data: Any, key_path: tuple[str, ...]) -> bool:
    node = data
    for segment in key_path[:-1]:
        if not isinstance(node, MutableMapping) or segment not in node:
            return False
        node = node[segment]
    return isinstance(node, MutableMapping) and key_path[-1] in node


def _path_value(data: Any, key_path: tuple[str, ...]) -> Any:
    node = data
    for segment in key_path:
        if not isinstance(node, MutableMapping) or segment not in node:
            return None
        node = node[segment]
    return node


def _parsed_edit_matches(
    original_text: str,
    candidate_text: str,
    key_path: tuple[str, ...],
    value: Any,
) -> bool:
    try:
        original = _load_for_compare(original_text)
        candidate = _load_for_compare(candidate_text)
    except Exception:
        return False
    expected = _set_path_for_compare(copy.deepcopy(original), key_path, value)
    if expected is None:
        return False
    return candidate == expected and _path_value(candidate, key_path) == value


def _parsed_unset_matches(
    original_text: str,
    candidate_text: str,
    key_path: tuple[str, ...],
) -> bool:
    try:
        original = _load_for_compare(original_text)
        candidate = _load_for_compare(candidate_text)
    except Exception:
        return False
    expected = _unset_path_for_compare(copy.deepcopy(original), key_path)
    if expected is None:
        return False
    return candidate == expected and not _path_exists(candidate, key_path)


def set_key(text: str, key_path: tuple[str, ...], value: Any) -> str:
    """Return *text* with *value* set at *key_path*, preserving formatting.

    Intermediate mappings are created as needed. Common block-style scalar
    edits are applied as surgical text splices so unrelated bytes stay
    unchanged; ambiguous shapes fall back to the round-trip loader.
    """
    if not key_path:
        raise ConfigEditError("cannot set an empty key path")
    result = _try_set_key_surgical(text, key_path, value)
    return result if result is not None else _set_key_round_trip(text, key_path, value)


def unset_key(text: str, key_path: tuple[str, ...]) -> str:
    """Return *text* with the key at *key_path* removed, preserving formatting.

    A no-op (returns *text* unchanged) when the document is empty or the path
    does not resolve to an existing key.
    """
    if not key_path or not text.strip():
        return text
    result = _try_unset_key_surgical(text, key_path)
    return result if result is not None else _unset_key_round_trip(text, key_path)


# --- Edit plan ------------------------------------------------------------


@dataclass(frozen=True)
class ConfigWritePlan:
    """The logical, frontend-agnostic write plan from the Rust core."""

    file: str | None
    layer: str
    key_path: tuple[str, ...]
    op: str
    has_value: bool
    new_value: Any

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ConfigWritePlan:
        return cls(
            file=payload.get("file"),
            layer=payload["layer"],
            key_path=tuple(payload["key_path"]),
            op=payload["op"],
            has_value=payload["has_value"],
            new_value=payload["new_value"],
        )


@dataclass(frozen=True)
class ConfigEffectivePreview:
    """The before/after effective value for the edited field."""

    path: str
    has_before: bool
    before: Any
    has_after: bool
    after: Any
    changed: bool

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ConfigEffectivePreview:
        return cls(
            path=payload["path"],
            has_before=payload["has_before"],
            before=payload["before"],
            has_after=payload["has_after"],
            after=payload["after"],
            changed=payload["changed"],
        )


@dataclass(frozen=True)
class EditPlanResult:
    """The full result of planning a config edit (no write performed).

    Combines the Rust write-plan/preview/validation with the Python-computed
    target-file text diff. ``new_text`` is exactly what :func:`apply_config_edit`
    writes, so the previewed diff and the written bytes can never disagree.
    """

    schema_version: int
    write_plan: ConfigWritePlan
    candidate_config: dict[str, Any]
    effective_preview: ConfigEffectivePreview
    validation: tuple[ConfigDiagnostic, ...]
    diagnostics: tuple[ConfigDiagnostic, ...]
    target_path: str | None
    used_chezmoi: bool
    current_text: str
    new_text: str
    text_diff: str

    @property
    def is_valid(self) -> bool:
        """Return ``True`` when the candidate config has no validation errors."""
        return not any(d.severity == "error" for d in self.validation)


def _apply_to_text(text: str, write_plan: ConfigWritePlan) -> str:
    if write_plan.op == "set":
        return set_key(text, write_plan.key_path, write_plan.new_value)
    return unset_key(text, write_plan.key_path)


def _unified_diff(old: str, new: str, target: Path | None) -> str:
    label = str(target) if target is not None else "config"
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
        )
    )


def plan_config_edit(
    inventory: ConfigInventory,
    path: str,
    target: str,
    op: ConfigEditOp,
    *,
    use_chezmoi: bool | None = None,
) -> EditPlanResult:
    """Plan a single set/unset edit against *target* layer for field *path*.

    Calls the Rust core for the write-plan, candidate merged config, effective
    preview, and validation, then computes the target-file text diff in memory
    (chezmoi source remapping is applied to the write target). No file is
    written.

    Args:
        inventory: The inventory built by
            :func:`sase.config.inventory.build_config_inventory` (carries the
            schema + layer stack needed to re-plan).
        path: Dotted field path to edit.
        target: Name of the writable target layer.
        op: The set/unset operation.
        use_chezmoi: Override chezmoi remapping; defaults to the effective
            ``use_chezmoi`` config value.

    Raises:
        ConfigEditError: when the Rust core rejects the request (e.g. an
            unknown target layer).
    """
    request = {
        "schema": inventory.schema,
        "layers": list(inventory.layer_inputs),
        "target_layer": target,
        "path": path,
        "op": op.to_wire(),
        "deprecations": dict(DEPRECATED_TOP_LEVEL_KEYS),
        "unsupported": sorted(UNSUPPORTED_TOP_LEVEL_KEYS),
    }
    binding = require_rust_binding("config_plan_edit")
    try:
        payload = binding(request)
    except ValueError as exc:
        raise ConfigEditError(str(exc)) from exc

    write_plan = ConfigWritePlan.from_wire(payload["write_plan"])

    chezmoi = get_use_chezmoi() if use_chezmoi is None else use_chezmoi
    write_path = resolve_write_path(write_plan.file, use_chezmoi=chezmoi)
    current_text = (
        write_path.read_text(encoding="utf-8")
        if write_path is not None and write_path.is_file()
        else ""
    )
    new_text = _apply_to_text(current_text, write_plan)
    text_diff = _unified_diff(current_text, new_text, write_path)

    return EditPlanResult(
        schema_version=payload["schema_version"],
        write_plan=write_plan,
        candidate_config=payload["candidate_config"],
        effective_preview=ConfigEffectivePreview.from_wire(
            payload["effective_preview"]
        ),
        validation=tuple(
            ConfigDiagnostic.from_wire(item) for item in payload["validation"]
        ),
        diagnostics=tuple(
            ConfigDiagnostic.from_wire(item) for item in payload["diagnostics"]
        ),
        target_path=str(write_path) if write_path is not None else None,
        used_chezmoi=chezmoi,
        current_text=current_text,
        new_text=new_text,
        text_diff=text_diff,
    )


# --- Write execution ------------------------------------------------------


@dataclass(frozen=True)
class AppliedResult:
    """The outcome of a source-preserving config write."""

    path: str
    op: str
    key_path: tuple[str, ...]
    created: bool
    used_chezmoi: bool


def apply_config_edit(plan: EditPlanResult) -> AppliedResult:
    """Write the planned edit to disk (source-preserving).

    Writes exactly ``plan.new_text`` to the chezmoi-resolved ``plan.target_path``
    that the diff previewed, creating parent directories as needed. Side
    effecting; only ever call from a tracked background task.

    Raises:
        ConfigEditError: when the plan has no writable target file.
    """
    if plan.target_path is None:
        raise ConfigEditError("edit plan has no writable target file")
    path = Path(plan.target_path)
    created = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.new_text, encoding="utf-8")
    return AppliedResult(
        path=str(path),
        op=plan.write_plan.op,
        key_path=plan.write_plan.key_path,
        created=created,
        used_chezmoi=plan.used_chezmoi,
    )
