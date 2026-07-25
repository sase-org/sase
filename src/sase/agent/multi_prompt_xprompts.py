"""Local xprompt handling for multi-prompt launches."""

import json
import os
import re
import tempfile
from typing import Any

from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
from sase.xprompt.models import UNSET as _UNSET
from sase.xprompt.models import XPrompt


def extract_called_xprompt_names(text: str, available_xprompts: set[str]) -> set[str]:
    """Extract xprompt names called in *text*.

    Supports shorthand syntaxes by preprocessing before extraction.
    """
    from sase.xprompt._parsing import preprocess_shorthand_syntax
    from sase.xprompt.workflow_validator_extract import extract_xprompt_calls

    preprocessed = preprocess_shorthand_syntax(text, available_xprompts)
    return {
        call.name
        for call in extract_xprompt_calls(preprocessed)
        if call.name in available_xprompts
    } | _model_directive_xprompt_names(preprocessed, available_xprompts)


def _model_directive_xprompt_names(
    text: str,
    available_xprompts: set[str],
) -> set[str]:
    """Return local xprompt names referenced as ``%model:#name`` values."""
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
        if candidate in available_xprompts:
            names.add(candidate)
    return names


def local_xprompts_for_segment(
    segment: str, local_xprompts: dict[str, XPrompt]
) -> dict[str, XPrompt]:
    """Return only local xprompts referenced by this segment.

    Includes transitive references between local xprompts so a called xprompt
    can depend on other local xprompts.
    """
    if not local_xprompts:
        return {}

    available = set(local_xprompts.keys())
    needed = extract_called_xprompt_names(segment, available)
    queue = list(needed)

    while queue:
        name = queue.pop()
        xp = local_xprompts.get(name)
        if xp is None:
            continue
        for called in extract_called_xprompt_names(xp.content, available):
            if called not in needed:
                needed.add(called)
                queue.append(called)

    # Preserve original definition order for deterministic serialization.
    return {name: xp for name, xp in local_xprompts.items() if name in needed}


def serialize_local_xprompts(xprompts: dict[str, XPrompt]) -> str:
    """Serialize local xprompts to a temp JSON file.

    Returns the path to the temp file.
    """
    from sase.core.paths import get_sase_managed_tmpdir

    def serialize_xprompt(xp: XPrompt) -> dict[str, object]:
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
                name: serialize_xprompt(local)
                for name, local in xp.local_xprompts.items()
            },
        }

    data: dict[str, object] = {
        name: serialize_xprompt(xp) for name, xp in xprompts.items()
    }

    fd, path = tempfile.mkstemp(
        suffix=".json",
        prefix="sase_local_xprompts_",
        dir=get_sase_managed_tmpdir("handoff"),
    )
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def deserialize_local_xprompts(path: str) -> dict[str, XPrompt]:
    """Read a local-xprompts JSON file and reconstruct XPrompt objects."""
    from sase.xprompt.models import InputArg, InputType
    from sase.xprompt.tags import parse_tags

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    def deserialize_xprompt(entry: dict[str, Any]) -> XPrompt:
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
                name: deserialize_xprompt(local)
                for name, local in nested_data.items()
                if isinstance(name, str) and isinstance(local, dict)
            }
            if isinstance(nested_data, dict)
            else {}
        )
        return XPrompt(
            name=entry["name"],
            content=entry["content"],
            inputs=inputs,
            source_path=entry.get("source_path"),
            tags=parse_tags(entry.get("tags")),
            local_xprompts=nested,
        )

    result: dict[str, XPrompt] = {}
    for name, entry in data.items():
        if isinstance(name, str) and isinstance(entry, dict):
            result[name] = deserialize_xprompt(entry)
    return result
