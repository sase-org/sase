"""On-disk state checks, diffs, and writes for platform units."""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from pathlib import Path

from sase.service.env import (
    ServiceEnvironmentError,
    environment_files_match,
    parse_service_environment_text,
    render_service_environment,
)
from sase.service.platform_models import NativeServiceDefinition


def content_current(path: Path, desired: str) -> tuple[bool, bool]:
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False, False
    except OSError:
        return True, False
    return True, current == desired


def environment_current(path: Path, desired: Mapping[str, str]) -> tuple[bool, bool]:
    try:
        current_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False, False
    except OSError:
        return True, False
    try:
        current = parse_service_environment_text(current_text)
    except ValueError:
        return True, False
    return True, environment_files_match(current, desired)


def combined_diff(
    definition_path: Path,
    definition_content: str,
    env_path: Path,
    env_content: str,
) -> str:
    chunks: list[str] = []
    definition_current = _read_text_or_empty(definition_path)
    chunks.extend(
        difflib.unified_diff(
            definition_current.splitlines(keepends=True),
            definition_content.splitlines(keepends=True),
            fromfile=str(definition_path),
            tofile=str(definition_path),
        )
    )
    env_current = _redact_env_file_text(_read_text_or_empty(env_path))
    env_desired = _redact_env_file_text(env_content)
    chunks.extend(
        difflib.unified_diff(
            env_current.splitlines(keepends=True),
            env_desired.splitlines(keepends=True),
            fromfile=str(env_path),
            tofile=str(env_path),
        )
    )
    return "".join(chunks)


def _read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _redact_env_file_text(text: str) -> str:
    if not text:
        return ""
    try:
        values = parse_service_environment_text(text)
    except (ServiceEnvironmentError, ValueError):
        return _blind_redact_env_text(text)
    return render_service_environment(dict.fromkeys(values, "[captured]"))


def _blind_redact_env_text(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines(keepends=True):
        newline = "\n" if raw_line.endswith("\n") else ""
        line = raw_line.rstrip("\n")
        if "=" not in line:
            lines.append(raw_line)
            continue
        name, _value = line.split("=", 1)
        lines.append(f'{name}="[captured]"{newline}')
    return "".join(lines)


def write_definition(definition: NativeServiceDefinition) -> None:
    definition.definition_path.parent.mkdir(parents=True, exist_ok=True)
    definition.definition_path.write_text(definition.content, encoding="utf-8")
    if definition.platform == "linux":
        definition.definition_path.chmod(0o644)


def unlink_owned_definition(definition: NativeServiceDefinition) -> None:
    try:
        definition.definition_path.unlink()
    except FileNotFoundError:
        pass
