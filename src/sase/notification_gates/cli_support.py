"""Shared plumbing for the headless ``sase gate`` subcommands.

``answer``, ``act``, and ``show`` are the headless peers of the ACE modals and
the mobile bridge: they resolve a gate bundle from the ``kind``/``request_id``
pair ``sase gate create`` emits, then call exactly the same shared entry points
every other surface calls. Nothing in this module reimplements gate behavior --
its whole job is turning CLI words into the arguments those entry points take,
and turning their failures into pointed messages and stable exit codes.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import bundle_paths
from sase.notification_gates.registry import GateAdapter

#: Exit codes shared with ``sase gate wait`` so a script can branch uniformly.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CANCELLED = 3


class GateCliError(Exception):
    """A usage failure raised before any shared gate entry point is called."""


@dataclass(frozen=True)
class ResolvedGateCliBundle:
    """One verified bundle plus the paths a headless subcommand reports."""

    kind: str
    request_id: str
    root: Path
    response_path: Path
    envelope: dict[str, Any]
    adapter: GateAdapter


def resolve_gate_cli_bundle(kind: str, request_id: str) -> ResolvedGateCliBundle:
    """Resolve and hash-verify the bundle named by a creation descriptor."""
    paths = bundle_paths(kind, request_id)
    if not paths.request.is_file():
        raise GateCliError(
            f"no gate bundle for {kind}/{request_id}: {paths.request} is missing"
        )
    envelope, adapter = load_and_verify_bundle(paths.root)
    return ResolvedGateCliBundle(
        kind=kind,
        request_id=request_id,
        root=paths.root,
        response_path=paths.response,
        envelope=envelope,
        adapter=adapter,
    )


def report_gate_error(command: str, exc: GateError) -> int:
    """Print one gate failure and return the exit code it maps to."""
    print(
        f"sase gate {command}: error [{exc.code}] {exc.target}: {exc}",
        file=sys.stderr,
    )
    if exc.code == "partial_attempt":
        print(
            "sase gate answer: pass --resume to continue after the failed "
            "option, or --restart to run the whole branch again",
            file=sys.stderr,
        )
    return EXIT_CANCELLED if exc.code == "gate_cancelled" else EXIT_ERROR


def emit_json(payload: Mapping[str, Any]) -> None:
    """Write one stable machine-readable payload to stdout."""
    json.dump(dict(payload), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


class JsonArgumentReader:
    """Read ``--input``-style JSON arguments, allowing stdin exactly once.

    Two arguments both spelled ``-`` would silently receive the same value,
    which is the kind of quiet wrong answer this epic exists to remove, so the
    second use is a usage error instead.
    """

    def __init__(self, stdin: TextIO | None = None) -> None:
        self._stdin = sys.stdin if stdin is None else stdin
        self._stdin_used = False

    def read(self, raw: str, *, target: str) -> Any:
        """Parse one JSON value from ``@file``, ``-``, or a literal."""
        if raw == "-":
            if self._stdin_used:
                raise GateCliError(
                    f"{target}: stdin can only be read once per invocation"
                )
            self._stdin_used = True
            text = self._stdin.read()
        elif raw.startswith("@"):
            path = Path(raw[1:]).expanduser()
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise GateCliError(f"{target}: cannot read {path}: {exc}") from exc
        else:
            text = raw
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GateCliError(f"{target}: invalid JSON: {exc}") from exc


def split_assignment(raw: str, *, target: str) -> tuple[str, str]:
    """Split one ``name=value`` argument, keeping ``=`` inside the value."""
    name, separator, value = raw.partition("=")
    if not separator or not name:
        raise GateCliError(f"{target}: expected name=value, got {raw!r}")
    return name, value


__all__ = [
    "EXIT_CANCELLED",
    "EXIT_ERROR",
    "EXIT_OK",
    "GateCliError",
    "JsonArgumentReader",
    "ResolvedGateCliBundle",
    "emit_json",
    "report_gate_error",
    "resolve_gate_cli_bundle",
    "split_assignment",
]
