"""Small public SDK for script-only axe chops.

Chop scripts receive a JSON context through ``--context`` and may write a
versioned result document to ``SASE_CHOP_RESULT_FILE``. The helpers here keep
that plumbing consistent for builtin and third-party chop packages.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TextIO

from sase.axe.chop_script_context import ChopScriptContext, read_chop_context
from sase.core.axe_chop_facade import (
    CHOP_RESULT_SCHEMA_VERSION,
    validate_chop_result,
)

from .report import ChopReport, Tone

ChopResultStatus = Literal["ok", "no_op", "check_error"]
SummaryValue = int | str | None


@dataclass(frozen=True)
class ChopArguments:
    """Common command-line arguments accepted by chop scripts."""

    context: str
    verbose: bool


@dataclass(frozen=True)
class ChopInvocation:
    """Loaded context and logger for one direct chop invocation."""

    arguments: ChopArguments
    context: ChopScriptContext
    logger: ChopLogger


@dataclass(frozen=True)
class ChopSummary:
    """Parsed representation of the shared human-readable summary line."""

    name: str
    line: str
    counters: dict[str, int]
    reason: str | None = None


def _env_truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() not in {"0", "false", "no", "off"})


def parse_chop_arguments(
    argv: Sequence[str] | None = None,
    *,
    description: str | None = None,
) -> ChopArguments:
    """Parse the common ``--context`` and verbose arguments for a chop."""

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--context", required=True, help="Path to chop context JSON")
    parser.add_argument(
        "-V",
        "--verbose",
        action="store_true",
        help="Emit debug diagnostics to stderr",
    )
    parsed = parser.parse_args(argv)
    return ChopArguments(
        context=str(parsed.context),
        verbose=bool(parsed.verbose) or _env_truthy(os.getenv("SASE_CHOP_VERBOSE")),
    )


class ChopLogger:
    """Leveled chop logger with opt-in debug output.

    Info messages stay on stdout to preserve the existing chop log contract.
    Debug messages are sent to stderr only when verbose mode is active.
    """

    def __init__(
        self,
        *,
        verbose: bool = False,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self.verbose = verbose
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr
        self._summaries: list[ChopSummary] = []

    def __call__(self, message: str, style: str | None = None) -> None:
        """Support the callback signature used by axe job runners."""

        del style
        self.info(message)

    def info(self, message: str) -> None:
        """Write an informational line to stdout."""

        print(message, file=self._stdout)
        summary = parse_summary(message)
        if summary is not None:
            self._summaries.append(summary)

    def debug(self, message: str) -> None:
        """Write a debug line to stderr when verbose mode is enabled."""

        if self.verbose:
            print(message, file=self._stderr)

    def warning(self, message: str) -> None:
        """Write a warning line to stderr."""

        print(message, file=self._stderr)

    def error(self, message: str) -> None:
        """Write an error line to stderr."""

        print(message, file=self._stderr)

    @property
    def last_summary(self) -> ChopSummary | None:
        """Return the most recently emitted summary, if one was observed."""

        return self._summaries[-1] if self._summaries else None


def load_chop_invocation(
    argv: Sequence[str] | None = None,
    *,
    description: str | None = None,
) -> ChopInvocation:
    """Parse common arguments, load context, and construct the shared logger."""

    arguments = parse_chop_arguments(argv, description=description)
    context = read_chop_context(arguments.context)
    verbose = arguments.verbose or context.verbose_lumberjack_diagnostics
    return ChopInvocation(
        arguments=arguments,
        context=context,
        logger=ChopLogger(verbose=verbose),
    )


def parse_summary(line: str) -> ChopSummary | None:
    """Parse a ``name: key=value ... reason=...`` chop summary line."""

    prefix, separator, body = line.partition(":")
    name = prefix.strip()
    if not separator or not name or any(char.isspace() for char in name):
        return None

    counters: dict[str, int] = {}
    reason: str | None = None
    tokens = body.split()
    if not tokens:
        return None
    for token in tokens:
        key, equals, value = token.partition("=")
        if not equals or not key or not value:
            return None
        if key == "reason":
            reason = value
            continue
        try:
            counters[key] = int(value)
        except ValueError:
            continue
    if not counters and reason is None:
        return None
    return ChopSummary(
        name=name,
        line=line,
        counters=counters,
        reason=reason,
    )


def emit_summary(
    name: str,
    fields: Mapping[str, SummaryValue],
    *,
    reason: str | None = None,
    logger: ChopLogger | Callable[[str], None] | None = None,
) -> str:
    """Emit and return the shared compact chop summary format."""

    parts = [f"{name}:"]
    parts.extend(
        f"{key}={value if value is not None else '-'}" for key, value in fields.items()
    )
    if reason:
        parts.append(f"reason={reason}")
    line = " ".join(parts)
    if logger is None:
        print(line)
    elif isinstance(logger, ChopLogger):
        logger.info(line)
    else:
        logger(line)
    return line


def launch_proposal(
    prompt: str,
    workspace: str,
    *,
    proposal_id: str | None = None,
    agent_name: str | None = None,
    clan: str | None = None,
    clan_summary: str | None = None,
    tribe: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    env: Mapping[str, str] | None = None,
    dedupe_key: str | None = None,
    wait_on: int | str | None = None,
) -> dict[str, Any]:
    """Build one structured agent-launch proposal."""

    proposal: dict[str, Any] = {
        "prompt": prompt,
        "workspace": workspace,
    }
    optional: dict[str, Any] = {
        "id": proposal_id,
        "agent_name": agent_name,
        "clan": clan,
        "clan_summary": clan_summary,
        "tribe": tribe,
        "model": model,
        "effort": effort,
        "dedupe_key": dedupe_key,
        "wait_on": wait_on,
    }
    proposal.update(
        {key: value for key, value in optional.items() if value is not None}
    )
    if env:
        proposal["env"] = dict(env)
    return proposal


@dataclass
class ChopResultBuilder:
    """Builder for a schema-versioned structured chop result."""

    status: ChopResultStatus = "ok"
    summary: str | None = None
    reason: str | None = None
    counters: dict[str, int] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    proposed_launches: list[dict[str, Any]] = field(default_factory=list)
    report: ChopReport | Mapping[str, Any] | None = None

    @classmethod
    def from_summary(cls, summary: ChopSummary) -> ChopResultBuilder:
        """Build a result whose status reflects the summary's no-op reason."""

        return cls(
            status="no_op" if summary.reason else "ok",
            summary=summary.line,
            reason=summary.reason,
            counters=dict(summary.counters),
        )

    def counter(self, name: str, value: int) -> ChopResultBuilder:
        """Add or replace an integer counter."""

        self.counters[name] = value
        return self

    def add_evidence(self, path: str | os.PathLike[str]) -> ChopResultBuilder:
        """Add a file reference to the result evidence list."""

        self.evidence.append(os.fspath(path))
        return self

    def propose(
        self,
        prompt: str,
        workspace: str,
        *,
        proposal_id: str | None = None,
        agent_name: str | None = None,
        clan: str | None = None,
        clan_summary: str | None = None,
        tribe: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        env: Mapping[str, str] | None = None,
        dedupe_key: str | None = None,
        wait_on: int | str | None = None,
    ) -> ChopResultBuilder:
        """Append a launch proposal built by :func:`launch_proposal`."""

        self.proposed_launches.append(
            launch_proposal(
                prompt,
                workspace,
                proposal_id=proposal_id,
                agent_name=agent_name,
                clan=clan,
                clan_summary=clan_summary,
                tribe=tribe,
                model=model,
                effort=effort,
                env=env,
                dedupe_key=dedupe_key,
                wait_on=wait_on,
            )
        )
        return self

    def add_proposal(
        self,
        prompt: str,
        workspace: str,
        *,
        proposal_id: str | None = None,
        agent_name: str | None = None,
        clan: str | None = None,
        clan_summary: str | None = None,
        tribe: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        env: Mapping[str, str] | None = None,
        dedupe_key: str | None = None,
        wait_on: int | str | None = None,
    ) -> ChopResultBuilder:
        """Alias for :meth:`propose` with an explicit collection-style name."""

        return self.propose(
            prompt,
            workspace,
            proposal_id=proposal_id,
            agent_name=agent_name,
            clan=clan,
            clan_summary=clan_summary,
            tribe=tribe,
            model=model,
            effort=effort,
            env=env,
            dedupe_key=dedupe_key,
            wait_on=wait_on,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-compatible result document."""

        document: dict[str, Any] = {
            "schema_version": CHOP_RESULT_SCHEMA_VERSION,
            "status": self.status,
            "counters": dict(self.counters),
            "proposed_launches": list(self.proposed_launches),
        }
        if self.summary is not None:
            document["summary"] = self.summary
        if self.reason is not None:
            document["reason"] = self.reason
        if self.evidence:
            document["evidence"] = list(self.evidence)
        if isinstance(self.report, ChopReport):
            if self.report:
                document["report"] = self.report.to_dict()
        elif self.report is not None:
            document["report"] = dict(self.report)
        return document

    def write(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        context: ChopScriptContext | None = None,
    ) -> dict[str, Any]:
        """Validate and atomically write this result document."""

        return write_chop_result(self, path, context=context)


def resolve_chop_result_file(
    context: ChopScriptContext | None = None,
    *,
    required: bool = True,
) -> Path | None:
    """Resolve the runner-provided result file from env or chop context."""

    configured = os.getenv("SASE_CHOP_RESULT_FILE")
    if not configured and context is not None:
        configured = context.result_file
    if configured:
        return Path(configured)
    if required:
        raise RuntimeError(
            "No chop result path configured; set SASE_CHOP_RESULT_FILE or "
            "provide context.result_file"
        )
    return None


def _atomic_write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(document, file, indent=2, sort_keys=True)
            file.write("\n")
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise


def write_chop_result(
    result: ChopResultBuilder | Mapping[str, Any],
    path: str | os.PathLike[str] | None = None,
    *,
    context: ChopScriptContext | None = None,
) -> dict[str, Any]:
    """Validate and atomically write a structured chop result document."""

    destination = Path(path) if path is not None else resolve_chop_result_file(context)
    assert destination is not None
    document = (
        result.to_dict() if isinstance(result, ChopResultBuilder) else dict(result)
    )
    normalized = validate_chop_result(document)
    _atomic_write_json(destination, normalized)
    return normalized


__all__ = [
    "CHOP_RESULT_SCHEMA_VERSION",
    "ChopArguments",
    "ChopInvocation",
    "ChopLogger",
    "ChopReport",
    "ChopResultBuilder",
    "ChopResultStatus",
    "ChopSummary",
    "Tone",
    "emit_summary",
    "launch_proposal",
    "load_chop_invocation",
    "parse_chop_arguments",
    "parse_summary",
    "resolve_chop_result_file",
    "write_chop_result",
]
