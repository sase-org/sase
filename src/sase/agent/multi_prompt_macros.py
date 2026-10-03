"""Local macro handling for multi-prompt launches."""

import json
import os
import re
import tempfile
from collections.abc import Mapping, MutableMapping
from typing import Any

from sase.macro._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
from sase.macro.models import UNSET as _UNSET
from sase.macro.models import Macro

LOCAL_XPROMPTS_ENV = "SASE_AGENT_LOCAL_XPROMPTS"
LOCAL_MACROS_ENV = "SASE_AGENT_LOCAL_MACROS"


def read_local_macros_path(environ: Mapping[str, str]) -> str | None:
    """Return the local-macros file path, preferring the macro spelling."""
    path = environ.get(LOCAL_MACROS_ENV)
    if path is None:
        path = environ.get(LOCAL_XPROMPTS_ENV)
    return path


def take_local_macros_path(environ: MutableMapping[str, str]) -> str | None:
    """Pop the local-macros file path under either spelling."""
    path = environ.pop(LOCAL_MACROS_ENV, None)
    legacy = environ.pop(LOCAL_XPROMPTS_ENV, None)
    return path if path is not None else legacy


def set_local_macros_path(environ: MutableMapping[str, str], path: str) -> None:
    """Publish the local-macros file path under both spellings."""
    environ[LOCAL_MACROS_ENV] = path
    environ[LOCAL_XPROMPTS_ENV] = path


def restore_local_macros_path(
    environ: MutableMapping[str, str], path: str | None
) -> None:
    """Restore a previously saved local-macros file path, or clear both keys."""
    if path is None:
        environ.pop(LOCAL_MACROS_ENV, None)
        environ.pop(LOCAL_XPROMPTS_ENV, None)
    else:
        set_local_macros_path(environ, path)


def extract_called_macro_names(text: str, available_macros: set[str]) -> set[str]:
    """Extract macro names called in *text*.

    Supports shorthand syntaxes by preprocessing before extraction.
    """
    from sase.macro._parsing import preprocess_shorthand_syntax
    from sase.macro.workflow_validator_extract import extract_macro_calls

    preprocessed = preprocess_shorthand_syntax(text, available_macros)
    return {
        call.name
        for call in extract_macro_calls(preprocessed)
        if call.name in available_macros
    } | _model_directive_macro_names(preprocessed, available_macros)


def _model_directive_macro_names(
    text: str,
    available_macros: set[str],
) -> set[str]:
    """Return local macro names referenced as ``%model:#name`` values."""
    names: set[str] = set()
    for match in re.finditer(_DIRECTIVE_PATTERN, text, re.MULTILINE):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name != "model":
            continue
        colon_arg = match.group(3)
        if colon_arg is None:
            continue
        if colon_arg.startswith("`") and colon_arg.endswith("`"):
            colon_arg = colon_arg[1:-1]
        if not colon_arg.startswith("#"):
            continue
        candidate = colon_arg[1:]
        if candidate in available_macros:
            names.add(candidate)
    return names


def local_macros_for_segment(
    segment: str, local_macros: dict[str, Macro]
) -> dict[str, Macro]:
    """Return only local macros referenced by this segment.

    Includes transitive references between local macros so a called macro
    can depend on other local macros.
    """
    if not local_macros:
        return {}

    available = set(local_macros.keys())
    needed = extract_called_macro_names(segment, available)
    queue = list(needed)

    while queue:
        name = queue.pop()
        xp = local_macros.get(name)
        if xp is None:
            continue
        for called in extract_called_macro_names(xp.content, available):
            if called not in needed:
                needed.add(called)
                queue.append(called)

    # Preserve original definition order for deterministic serialization.
    return {name: xp for name, xp in local_macros.items() if name in needed}


def serialize_local_macros(macros: dict[str, Macro]) -> str:
    """Serialize local macros to a temp JSON file.

    Returns the path to the temp file.
    """
    from sase.core.paths import get_sase_managed_tmpdir

    def serialize_macro(xp: Macro) -> dict[str, object]:
        return {
            "name": xp.name,
            "content": xp.content,
            "inputs": [
                {
                    "name": inp.name,
                    "type": inp.type.value,
                    "default": None if inp.default is _UNSET else inp.default,
                    "is_step_input": inp.is_step_input,
                }
                for inp in xp.inputs
            ],
            "source_path": xp.source_path,
            "tags": [t.value for t in xp.tags],
            "local_xprompts": {
                name: serialize_macro(local) for name, local in xp.local_macros.items()
            },
        }

    data: dict[str, object] = {name: serialize_macro(xp) for name, xp in macros.items()}

    fd, path = tempfile.mkstemp(
        suffix=".json",
        prefix="sase_local_xprompts_",
        dir=get_sase_managed_tmpdir("handoff"),
    )
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def deserialize_local_macros(path: str) -> dict[str, Macro]:
    """Read a local-macros JSON file and reconstruct Macro objects."""
    from sase.macro.models import InputArg, InputType
    from sase.macro.tags import parse_tags

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    def deserialize_macro(entry: dict[str, Any]) -> Macro:
        inputs = []
        for inp in entry.get("inputs", []):
            if not isinstance(inp, dict):
                continue
            default = inp.get("default")
            if default is None:
                default = _UNSET
            inputs.append(
                InputArg(
                    name=inp["name"],
                    type=InputType(inp.get("type", "line")),
                    default=default,
                    is_step_input=inp.get("is_step_input", False),
                )
            )
        nested_data = entry.get("local_xprompts", {})
        nested = (
            {
                name: deserialize_macro(local)
                for name, local in nested_data.items()
                if isinstance(name, str) and isinstance(local, dict)
            }
            if isinstance(nested_data, dict)
            else {}
        )
        return Macro(
            name=entry["name"],
            content=entry["content"],
            inputs=inputs,
            source_path=entry.get("source_path"),
            tags=parse_tags(entry.get("tags")),
            local_macros=nested,
        )

    result: dict[str, Macro] = {}
    for name, entry in data.items():
        if isinstance(name, str) and isinstance(entry, dict):
            result[name] = deserialize_macro(entry)
    return result
