"""Surgical source-preserving YAML edits for common scalar changes."""

from __future__ import annotations

import copy
import re
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

from sase.config._edit_yaml_io import make_yaml


@dataclass(frozen=True)
class _MappingFrame:
    node: MutableMapping[Any, Any]
    owner: MutableMapping[Any, Any] | None
    owner_key: str | None


def _is_flow_style(node: Any) -> bool:
    flow_attrib = getattr(node, "fa", None)
    flow_style = getattr(flow_attrib, "flow_style", None)
    return bool(callable(flow_style) and flow_style())


def _is_block_mapping(node: Any) -> bool:
    return isinstance(node, MutableMapping) and not _is_flow_style(node)


def _load_root_mapping(text: str) -> MutableMapping[Any, Any] | None:
    from ruamel.yaml.comments import CommentedMap

    handler = make_yaml()
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


def try_set_key_surgical(
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


def try_unset_key_surgical(text: str, key_path: tuple[str, ...]) -> str | None:
    data = _load_root_mapping(text)
    if data is None:
        return None
    return _delete_key_lines(text, data, key_path)


def _load_for_compare(text: str) -> Any:
    handler = make_yaml()
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
