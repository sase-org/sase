"""Keep persisted Agent fields JSON-safe or explicitly encoded."""

from __future__ import annotations

import dataclasses
import re
from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType


_JSON_NATIVE_ANNOTATION_TOKENS = frozenset(
    {
        "str",
        "int",
        "float",
        "bool",
        "None",
        "list",
        "dict",
        "tuple",
        "Literal",
        "Any",
        "datetime",
        "AgentType",
        "VarValue",
    }
)

# Fields with dedicated encoder/decoder pairs in agent_bundle.py.
_ENCODED_BUNDLE_FIELDS = frozenset(
    {
        "finalizer_status",
        "linked_repos",
        "wait_epic_follows",
        "wait_turn_bindings",
        "imported_source_owner",
    }
)


def _annotation_tokens(annotation: object) -> set[str]:
    readable = (
        annotation
        if isinstance(annotation, str)
        else getattr(annotation, "__name__", repr(annotation))
    )
    without_literal_values = re.sub(r"Literal\[[^\]]*\]", "Literal", readable)
    return set(re.findall(r"[A-Za-z_]\w*", without_literal_values))


def test_persisted_agent_fields_have_json_native_or_explicit_encoding() -> None:
    minimal_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="minimal",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 1, 1),
    )
    persisted = set(minimal_agent.to_bundle_dict())
    non_native: dict[str, str] = {}

    for field in dataclasses.fields(Agent):
        if field.name not in persisted:
            continue
        annotation = field.type if isinstance(field.type, str) else repr(field.type)
        unexpected = _annotation_tokens(annotation) - _JSON_NATIVE_ANNOTATION_TOKENS
        if unexpected:
            non_native[field.name] = annotation
            assert field.name in _ENCODED_BUNDLE_FIELDS, (
                f"Persisted Agent field {field.name!r} has non-native annotation "
                f"{annotation!r}. Add it to _RUNTIME_ONLY_BUNDLE_FIELDS in "
                "agent_bundle.py, or add an encoder/decoder pair and list it in "
                "_ENCODED_BUNDLE_FIELDS."
            )

    stale_encoded_fields = _ENCODED_BUNDLE_FIELDS - non_native.keys()
    assert not stale_encoded_fields, (
        "_ENCODED_BUNDLE_FIELDS contains fields that are no longer persisted with "
        f"non-native annotations: {sorted(stale_encoded_fields)}"
    )
