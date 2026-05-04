"""Local xprompt handling for multi-prompt launches."""

import json
import os
import tempfile

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
    }


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
    from sase.core.paths import get_sase_tmpdir

    data: dict[str, object] = {}
    for name, xp in xprompts.items():
        data[name] = {
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
        }

    fd, path = tempfile.mkstemp(
        suffix=".json", prefix="sase_local_xprompts_", dir=get_sase_tmpdir()
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

    result: dict[str, XPrompt] = {}
    for name, entry in data.items():
        inputs = []
        for inp in entry.get("inputs", []):
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
        result[name] = XPrompt(
            name=entry["name"],
            content=entry["content"],
            inputs=inputs,
            source_path=entry.get("source_path"),
            tags=parse_tags(entry.get("tags")),
        )
    return result
