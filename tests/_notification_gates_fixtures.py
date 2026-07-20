"""Request builders shared by the notification gate test modules."""

from __future__ import annotations


def gate_spec(
    *,
    request_id: str = "request-1",
    kind: str = "hitl",
    command: str | None = None,
    auto: object = False,
    timeout: float | None = None,
) -> dict[str, object]:
    option_id = "accept" if kind == "hitl" else "approve"
    script = command or (
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "value = json.load(sys.stdin)\n"
        "print(json.dumps({'status': 'ok', 'input': value}))\n"
    )
    spec: dict[str, object] = {
        "schema_version": 3,
        "request_id": request_id,
        "kind": kind,
        "producer": {"agent": "test"},
        "continuation_mode": "resume_agent",
        "payload": {"title": "Review this"},
        "presentation": {
            "notes": ["Review requested"],
            "tags": ["Gate"],
            "files": ["preview.md"],
            "preview": "preview.md",
        },
        "query": option_id,
        "primary_branch": [option_id],
        "options": [
            {
                "id": option_id,
                "label": option_id.title(),
                "command": {"argv": [f"commands/{option_id}"]},
                "input_schema": {"type": "object"},
                "result_schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "ok"}},
                },
            }
        ],
        "resources": [
            {
                "path": f"commands/{option_id}",
                "role": "command",
                "content": script,
            },
            {"path": "preview.md", "role": "preview", "content": "# Preview\n"},
        ],
        "auto": auto,
    }
    if timeout is not None:
        spec["gate_timeout_seconds"] = timeout
    return spec


def custom_gate_spec(
    *,
    request_id: str = "custom-request",
    auto: object = False,
    feedback: str | None = None,
) -> dict[str, object]:
    proceed: dict[str, object] = {
        "id": "proceed",
        "label": "Proceed safely",
        "icon": "✅",
        "command": {"argv": ["commands/proceed"]},
        "input_schema": {"type": "object"},
        "result_schema": {
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"const": "ok"}},
        },
    }
    if feedback is not None:
        proceed["feedback"] = feedback
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {"open": {"shape": True}},
        "presentation": {
            "icon": "🛡️",
            "sender": "safety-check",
            "notes": ["Confirm guarded work"],
        },
        "query": "(proceed AND audit AND broken)",
        "primary_branch": ["proceed", "audit", "broken"],
        "options": [
            proceed,
            {
                "id": "audit",
                "label": "Write audit record",
                "icon": "📝",
                "command": {"argv": ["commands/audit"]},
            },
            {
                "id": "broken",
                "label": "Try fallible follow-up",
                "default_selected": False,
                "command": {"argv": ["commands/broken"]},
            },
        ],
        "groups": [
            {
                "options": ["broken", "proceed", "audit"],
                "label": "Proceed safely",
                "icon": "✅",
            }
        ],
        "resources": [
            {
                "path": "commands/proceed",
                "role": "command",
                "content": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "json.load(sys.stdin)\n"
                    "print(json.dumps({'status': 'ok'}))\n"
                ),
            },
            {
                "path": "commands/audit",
                "role": "command",
                "content": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "value = json.load(sys.stdin)\n"
                    "print(json.dumps({'audit': value}))\n"
                ),
            },
            {
                "path": "commands/broken",
                "role": "command",
                "content": "#!/bin/sh\nprintf 'follow-up failed' >&2\nexit 7\n",
            },
        ],
        "auto": auto,
    }
