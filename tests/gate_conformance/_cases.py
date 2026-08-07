"""The one fixture set every gate surface is held to.

A case is a gate specification plus the submissions to make against it and the
observable facts that must hold afterward, stated in terms no surface owns:
what each command received on stdin, what the durable response recorded, and
which failure code landed in ``errors/``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Submission capabilities a surface may or may not have yet.
CAP_FEEDBACK = "feedback"
CAP_OPTION_INPUTS = "option_inputs"
CAP_RETRY = "retry"
CAP_SHARED_INPUT = "shared_input"

_ECHO_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "print(json.dumps({'status': 'ok', 'input': json.load(sys.stdin)}))\n"
)


def _counting_command(counter: Path, *, fail_first: bool = False) -> str:
    """A command that reports how many times it has run.

    ``fail_first`` makes the first run exit non-zero, which is how a case
    reaches a partially executed AND branch without racing anything.
    """
    return (
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "value = json.load(sys.stdin)\n"
        f"counter = pathlib.Path({str(counter)!r})\n"
        "runs = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(runs + 1))\n"
        f"if {fail_first!r} and runs == 0:\n"
        "    sys.stderr.write('first run fails')\n"
        "    raise SystemExit(9)\n"
        "print(json.dumps({'status': 'ok', 'input': value, 'runs': runs + 1}))\n"
    )


@dataclass(frozen=True)
class Submission:
    """One answer attempt, expressed the way every surface can consume it."""

    selected: tuple[str, ...]
    input_data: Any | None = None
    option_inputs: dict[str, Any] | None = None
    feedback: str | None = None
    retry: str | None = None


@dataclass(frozen=True)
class ConformanceCase:
    """One gate plus the submissions and facts that define correct behavior."""

    id: str
    spec: dict[str, Any]
    submission: Submission
    requires: frozenset[str] = frozenset()
    #: Submissions made first, whose outcome is deliberately not asserted --
    #: they exist to put the gate into the state the case is about.
    prior: tuple[Submission, ...] = ()
    cancel_before_submit: bool = False
    answered: bool = True
    #: option id -> subset of that option's command result that must match.
    expected_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: option id -> the exact value recorded in ``response.option_inputs``.
    expected_response_inputs: dict[str, Any] = field(default_factory=dict)
    expected_feedback: str | None = None
    #: The code that must appear in the bundle's ``errors/`` records.
    expected_error_code: str | None = None
    #: Substrings of which the surface's failure message must contain one.
    #: More than one spelling is listed where a surface deliberately renames a
    #: code for its own audience -- mobile reports a cancelled gate as
    #: ``conflict_already_handled`` -- which is presentation, not behavior.
    expected_error_text: tuple[str, ...] = ()


def _spec(
    request_id: str,
    options: list[dict[str, Any]],
    *,
    query: str | None = None,
    commands: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a single-branch custom gate spec from option declarations."""
    option_ids = [str(option["id"]) for option in options]
    branch = query or (
        option_ids[0] if len(option_ids) == 1 else "(" + " AND ".join(option_ids) + ")"
    )
    spec: dict[str, Any] = {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "conformance"},
        "payload": {},
        "presentation": {
            "icon": "🧪",
            "title": f"Conformance {request_id}",
            "notes": [f"Conformance {request_id}"],
        },
        "query": branch,
        "primary_branch": option_ids,
        "options": [
            {**option, "command": {"argv": [f"commands/{option['id']}"]}}
            for option in options
        ],
        "resources": [
            {
                "path": f"commands/{option_id}",
                "role": "command",
                "content": (commands or {}).get(option_id, _ECHO_COMMAND),
            }
            for option_id in option_ids
        ],
    }
    if len(option_ids) > 1:
        spec["groups"] = [{"options": option_ids, "label": "Run every step"}]
    return spec


def _no_input(_tmp: Path) -> ConformanceCase:
    return ConformanceCase(
        id="no_input",
        spec=_spec("conf-no-input", [{"id": "proceed", "label": "Proceed"}]),
        submission=Submission(selected=("proceed",)),
        expected_results={"proceed": {"input": {}}},
        expected_response_inputs={"proceed": {}},
    )


def _required_scalar(_tmp: Path) -> ConformanceCase:
    return ConformanceCase(
        id="required_scalar",
        spec=_spec(
            "conf-required",
            [
                {
                    "id": "deploy",
                    "label": "Deploy",
                    "inputs": [
                        {
                            "id": "target_env",
                            "label": "Target environment",
                            "type": "line",
                            "required": True,
                        }
                    ],
                }
            ],
        ),
        submission=Submission(
            selected=("deploy",),
            option_inputs={"deploy": {"target_env": "staging"}},
        ),
        requires=frozenset({CAP_OPTION_INPUTS}),
        expected_results={"deploy": {"input": {"target_env": "staging"}}},
        expected_response_inputs={"deploy": {"target_env": "staging"}},
    )


def _optional_scalar_omitted(_tmp: Path) -> ConformanceCase:
    return ConformanceCase(
        id="optional_scalar_omitted",
        spec=_spec(
            "conf-optional",
            [
                {
                    "id": "deploy",
                    "label": "Deploy",
                    "inputs": [
                        {
                            "id": "ticket",
                            "label": "Ticket",
                            "type": "line",
                            "default": "none",
                        }
                    ],
                }
            ],
        ),
        # A declared default is authoring metadata a form seeds from; it is
        # deliberately not injected host-side, so an omitted optional field
        # reaches the command as absent rather than as its default.
        submission=Submission(selected=("deploy",), option_inputs={"deploy": {}}),
        requires=frozenset({CAP_OPTION_INPUTS}),
        expected_results={"deploy": {"input": {}}},
        expected_response_inputs={"deploy": {}},
    )


def _every_input_type(_tmp: Path) -> ConformanceCase:
    value = {
        "a_word": "token",
        "a_line": "one line",
        "a_text": "two\nlines",
        "a_path": "/tmp/example",
        "an_agent": "worker.1",
        "an_int": 7,
        "a_float": 1.5,
        "a_bool": True,
        "an_enum": "fast",
        "many_lines": ["first", "second"],
    }
    return ConformanceCase(
        id="every_input_type",
        spec=_spec(
            "conf-types",
            [
                {
                    "id": "run",
                    "label": "Run",
                    "inputs": [
                        {"id": "a_word", "label": "Word", "type": "word"},
                        {"id": "a_line", "label": "Line", "type": "line"},
                        {"id": "a_text", "label": "Text", "type": "text"},
                        {"id": "a_path", "label": "Path", "type": "path"},
                        {"id": "an_agent", "label": "Agent", "type": "agent"},
                        {"id": "an_int", "label": "Int", "type": "int"},
                        {"id": "a_float", "label": "Float", "type": "float"},
                        {"id": "a_bool", "label": "Bool", "type": "bool"},
                        {
                            "id": "an_enum",
                            "label": "Mode",
                            "type": "enum",
                            "choices": ["fast", "thorough"],
                        },
                        {
                            "id": "many_lines",
                            "label": "Lines",
                            "type": "line",
                            "repeatable": True,
                        },
                    ],
                }
            ],
        ),
        submission=Submission(selected=("run",), option_inputs={"run": value}),
        requires=frozenset({CAP_OPTION_INPUTS}),
        expected_results={"run": {"input": value}},
        expected_response_inputs={"run": value},
    )


def _invalid_input(_tmp: Path) -> ConformanceCase:
    return ConformanceCase(
        id="invalid_input",
        spec=_spec(
            "conf-invalid",
            [
                {
                    "id": "deploy",
                    "label": "Deploy",
                    "inputs": [
                        {
                            "id": "target_env",
                            "label": "Target environment",
                            "type": "line",
                            "required": True,
                        }
                    ],
                }
            ],
        ),
        submission=Submission(selected=("deploy",), option_inputs={"deploy": {}}),
        requires=frozenset({CAP_OPTION_INPUTS}),
        answered=False,
        expected_error_code="schema_validation_failed",
    )


def _divergent_option_inputs(_tmp: Path) -> ConformanceCase:
    return ConformanceCase(
        id="divergent_option_inputs",
        spec=_spec(
            "conf-divergent",
            [
                {
                    "id": "build",
                    "label": "Build",
                    "inputs": [
                        {
                            "id": "profile",
                            "label": "Profile",
                            "type": "word",
                            "required": True,
                        }
                    ],
                },
                {
                    "id": "publish",
                    "label": "Publish",
                    "inputs": [
                        {
                            "id": "channel",
                            "label": "Channel",
                            "type": "word",
                            "required": True,
                        }
                    ],
                },
            ],
        ),
        # Each option's compiled schema is additionalProperties:false, so a
        # single shared value could not satisfy both: this is the workaround
        # per-option submission removed.
        submission=Submission(
            selected=("build", "publish"),
            option_inputs={
                "build": {"profile": "release"},
                "publish": {"channel": "beta"},
            },
        ),
        requires=frozenset({CAP_OPTION_INPUTS}),
        expected_results={
            "build": {"input": {"profile": "release"}},
            "publish": {"input": {"channel": "beta"}},
        },
        expected_response_inputs={
            "build": {"profile": "release"},
            "publish": {"channel": "beta"},
        },
    )


def _feedback_plus_input(_tmp: Path) -> ConformanceCase:
    return ConformanceCase(
        id="feedback_plus_input",
        spec=_spec(
            "conf-feedback",
            [
                {
                    "id": "reject",
                    "label": "Reject",
                    "feedback": "optional",
                    "inputs": [
                        {"id": "reason_code", "label": "Reason", "type": "word"}
                    ],
                }
            ],
        ),
        submission=Submission(
            selected=("reject",),
            option_inputs={"reject": {"reason_code": "scope"}},
            feedback="Too broad for one CL",
        ),
        requires=frozenset({CAP_OPTION_INPUTS, CAP_FEEDBACK}),
        expected_results={
            "reject": {
                "input": {
                    "reason_code": "scope",
                    "feedback": "Too broad for one CL",
                }
            }
        },
        expected_response_inputs={
            "reject": {"reason_code": "scope", "feedback": "Too broad for one CL"}
        },
        expected_feedback="Too broad for one CL",
    )


def _feedback_only(_tmp: Path) -> ConformanceCase:
    """The note reaches a declaring command and no other, on every surface."""
    return ConformanceCase(
        id="feedback_only",
        spec=_spec(
            "conf-note",
            [
                {
                    "id": "accept",
                    "label": "Accept",
                    "feedback": "optional",
                    "input_schema": {
                        "type": "object",
                        "properties": {"feedback": {"type": "string"}},
                        "additionalProperties": False,
                    },
                },
                {"id": "log", "label": "Log", "input_schema": {}},
            ],
        ),
        submission=Submission(selected=("accept", "log"), feedback="looks right"),
        requires=frozenset({CAP_FEEDBACK}),
        expected_results={
            "accept": {"input": {"feedback": "looks right"}},
            "log": {"input": {}},
        },
        expected_response_inputs={
            "accept": {"feedback": "looks right"},
            "log": {},
        },
        expected_feedback="looks right",
    )


def _secret_field(_tmp: Path) -> ConformanceCase:
    return ConformanceCase(
        id="secret_field",
        spec=_spec(
            "conf-secret",
            [
                {
                    "id": "rotate",
                    "label": "Rotate",
                    "inputs": [
                        {
                            "id": "token",
                            "label": "Token",
                            "type": "line",
                            "required": True,
                            "secret": True,
                        }
                    ],
                }
            ],
        ),
        submission=Submission(
            selected=("rotate",), option_inputs={"rotate": {"token": "hunter2"}}
        ),
        requires=frozenset({CAP_OPTION_INPUTS}),
        # Unredacted on stdin, redacted in the durable audit record.
        expected_results={"rotate": {"input": {"token": "hunter2"}}},
        expected_response_inputs={"rotate": {"token": {"$redacted": True}}},
    )


def _legacy_shared_input(_tmp: Path) -> ConformanceCase:
    """A bundle authored before ``inputs`` existed keeps its shared-value path."""
    return ConformanceCase(
        id="legacy_shared_input",
        spec=_spec(
            "conf-legacy",
            [
                {
                    "id": "apply",
                    "label": "Apply",
                    "input_schema": {
                        "type": "object",
                        "properties": {"ticket": {"type": "string"}},
                        "required": ["ticket"],
                    },
                },
                {"id": "record", "label": "Record", "input_schema": {}},
            ],
        ),
        submission=Submission(
            selected=("apply", "record"), input_data={"ticket": "OPS-1"}
        ),
        requires=frozenset({CAP_SHARED_INPUT}),
        expected_results={
            "apply": {"input": {"ticket": "OPS-1"}},
            "record": {"input": {"ticket": "OPS-1"}},
        },
        expected_response_inputs={
            "apply": {"ticket": "OPS-1"},
            "record": {"ticket": "OPS-1"},
        },
    )


def _cancellation_race(_tmp: Path) -> ConformanceCase:
    return ConformanceCase(
        id="cancellation_race",
        spec=_spec("conf-cancelled", [{"id": "proceed", "label": "Proceed"}]),
        submission=Submission(selected=("proceed",)),
        cancel_before_submit=True,
        answered=False,
        expected_error_text=("cancel", "already handled"),
    )


def _retry_spec(tmp: Path, request_id: str) -> dict[str, Any]:
    return _spec(
        request_id,
        [
            {"id": "first", "label": "First step"},
            {"id": "second", "label": "Second step"},
        ],
        commands={
            "first": _counting_command(tmp / f"{request_id}-first"),
            "second": _counting_command(tmp / f"{request_id}-second", fail_first=True),
        },
    )


def _partial_attempt(tmp: Path) -> ConformanceCase:
    return ConformanceCase(
        id="partial_attempt",
        spec=_retry_spec(tmp, "conf-partial"),
        prior=(Submission(selected=("first", "second")),),
        submission=Submission(selected=("first", "second")),
        answered=False,
        expected_error_text=("partially executed",),
    )


def _retry_resume(tmp: Path) -> ConformanceCase:
    return ConformanceCase(
        id="retry_resume",
        spec=_retry_spec(tmp, "conf-resume"),
        prior=(Submission(selected=("first", "second")),),
        submission=Submission(selected=("first", "second"), retry="resume"),
        requires=frozenset({CAP_RETRY}),
        # `first` ran once, in the failed attempt, and its recorded result is
        # replayed rather than re-run.
        expected_results={"first": {"runs": 1}, "second": {"runs": 2}},
    )


def _retry_restart(tmp: Path) -> ConformanceCase:
    return ConformanceCase(
        id="retry_restart",
        spec=_retry_spec(tmp, "conf-restart"),
        prior=(Submission(selected=("first", "second")),),
        submission=Submission(selected=("first", "second"), retry="restart"),
        requires=frozenset({CAP_RETRY}),
        expected_results={"first": {"runs": 2}, "second": {"runs": 2}},
    )


CASE_BUILDERS: dict[str, Callable[[Path], ConformanceCase]] = {
    "cancellation_race": _cancellation_race,
    "divergent_option_inputs": _divergent_option_inputs,
    "every_input_type": _every_input_type,
    "feedback_only": _feedback_only,
    "feedback_plus_input": _feedback_plus_input,
    "invalid_input": _invalid_input,
    "legacy_shared_input": _legacy_shared_input,
    "no_input": _no_input,
    "optional_scalar_omitted": _optional_scalar_omitted,
    "partial_attempt": _partial_attempt,
    "required_scalar": _required_scalar,
    "retry_restart": _retry_restart,
    "retry_resume": _retry_resume,
    "secret_field": _secret_field,
}


__all__ = [
    "CAP_FEEDBACK",
    "CAP_OPTION_INPUTS",
    "CAP_RETRY",
    "CAP_SHARED_INPUT",
    "CASE_BUILDERS",
    "ConformanceCase",
    "Submission",
]
