"""W1-W3 skew witnesses for update-skew auto-restart.

Witnesses are the "update actually happened" half of the classifier's
``signature ∧ witness ∧ probe`` rule:

- W1 (boot identity drift): the ``code_identity`` snapshot persisted in
  ``agent_meta.json`` at boot no longer matches current disk state.
- W2 (update journal): a ``sase update`` journal row falls between boot
  and the failure.
- W3 (file-level proof): the culprit symbol or module exists at the boot
  revision and not at HEAD (or the reverse), with the culprit commit
  named by ``git log -S``.

The fresh-interpreter probe (W4) belongs to the healer, so witnesses
assembled here never carry a probe result: a Tier 1-2 match with an
update witness therefore classifies ``defer`` (probe pending), never
``relaunch``.

W3 runs bounded git subprocesses (2 s timeouts each) and is the only
expensive witness. It is gated on the cheap failure-facts prefilter:
without skew-shaped text there is no symbol worth proving, so the git
calls are skipped outright.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Mapping

from sase.agent.auto_restart.managed_roots import (
    ManagedRoot,
    code_identity_digest,
    current_code_identity,
)
from sase.core.agent_auto_restart_wire import (
    AutoRestartFileProofWire,
    AutoRestartRefreshLogLineWire,
    AutoRestartWitnessesWire,
)
from sase.core.time import get_timezone

#: Timeout for each bounded git probe (seconds).
GIT_PROBE_TIMEOUT_SECONDS = 2

#: At most this many journal updates are attached to one witness bundle.
MAX_JOURNAL_UPDATES = 32

_REFRESH_LINE_RE = re.compile(
    r"Refreshing sase runner code after dependency wait:\s*"
    r"(?P<from>[0-9a-fA-F]{7,40})\s*->\s*(?P<to>[0-9a-fA-F]{7,40})"
)

_CANNOT_IMPORT_RE = re.compile(
    r"cannot import name ['\"](?P<symbol>[^'\"]+)['\"]"
    r"\s+from\s+['\"](?P<module>[^'\"]+)['\"]"
)
_NO_MODULE_RE = re.compile(r"No module named ['\"](?P<module>[^'\"]+)['\"]")


@dataclass(frozen=True)
class WitnessInputs:
    """Everything witness collection needs for one failed agent."""

    facts: Mapping[str, Any] | None
    boot_identity: Mapping[str, Any] | None
    booted_at: str | None
    finished_at: float | None
    artifacts_timestamp: str | None
    done_mtime: float | None
    error_text: str
    traceback_text: str
    log_tail: str
    managed_roots: tuple[ManagedRoot, ...]
    journal_path: Path | None = None
    enable_file_proof: bool = True


def _parse_refresh_log_line(log_tail: str) -> AutoRestartRefreshLogLineWire | None:
    """Parse the runner refresh line from a log tail, if present."""
    match: re.Match[str] | None = None
    for candidate in _REFRESH_LINE_RE.finditer(log_tail or ""):
        match = candidate
    if match is None:
        return None
    return AutoRestartRefreshLogLineWire(
        from_rev=match.group("from"),
        to_rev=match.group("to"),
    )


def _extract_proof_target(
    facts: Mapping[str, Any] | None,
    *,
    error_text: str,
    traceback_text: str,
) -> tuple[str | None, str | None]:
    """Extract the ``(module, symbol)`` pair W3 should prove.

    Structured facts win; otherwise the Tier 1 import-family regexes run
    over the error text. Either element may be ``None`` when unknown.
    """
    if isinstance(facts, Mapping):
        import_error = facts.get("import_error")
        if isinstance(import_error, Mapping):
            module = import_error.get("name")
            symbol = import_error.get("missing_symbol")
            if isinstance(module, str) and module:
                return module, symbol if isinstance(symbol, str) else None
        attribute_error = facts.get("attribute_error")
        if isinstance(attribute_error, Mapping):
            module = attribute_error.get("module")
            attribute = attribute_error.get("attribute")
            if isinstance(module, str) and module:
                return module, attribute if isinstance(attribute, str) else None
    haystack = f"{error_text or ''}\n{traceback_text or ''}"
    match = _CANNOT_IMPORT_RE.search(haystack)
    if match is not None:
        return match.group("module"), match.group("symbol")
    match = _NO_MODULE_RE.search(haystack)
    if match is not None:
        module = match.group("module").split(".")[0]
        return module, None
    return None, None


def _select_proof_root(
    module: str | None,
    managed_roots: tuple[ManagedRoot, ...],
) -> ManagedRoot | None:
    """Select the managed root that owns *module*, if any."""
    if not module:
        return None
    by_role: dict[str, ManagedRoot] = {}
    for root in managed_roots:
        by_role.setdefault(root.role, root)
    if module == "sase_core_rs" or module.startswith("sase_core"):
        return by_role.get("core")
    if module == "sase" or module.startswith("sase."):
        return by_role.get("host")
    first = module.split(".")[0].replace("_", "-")
    for root in managed_roots:
        if root.name.lower() == first.lower():
            return root
    return None


def _run_git(
    root: str, *args: str, timeout: float = GIT_PROBE_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str] | None:
    """Run one bounded git command under *root*; ``None`` on any failure."""
    try:
        return subprocess.run(
            ("git", "-C", root, *args),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
            env={
                **os.environ,
                "GIT_PAGER": "cat",
                "GIT_OPTIONAL_LOCKS": "0",
            },
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _module_relpaths(module: str) -> list[str]:
    """Candidate repo-relative paths for *module* across known layouts."""
    dotted = module.replace(".", "/")
    candidates = [
        f"src/{dotted}.py",
        f"{dotted}.py",
        f"src/{dotted}/__init__.py",
        f"{dotted}/__init__.py",
    ]
    seen: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.append(candidate)
    return seen


def _pick_relpath(root: str, module: str, revisions: list[str]) -> str | None:
    """Return the first candidate path existing at any of *revisions*."""
    for relpath in _module_relpaths(module):
        for revision in revisions:
            if not revision:
                continue
            completed = _run_git(root, "cat-file", "-e", f"{revision}:{relpath}")
            if completed is not None and completed.returncode == 0:
                return relpath
    return None


def _grep_at_revision(
    root: str, revision: str, relpath: str, symbol: str
) -> bool | None:
    """Return whether *symbol* occurs at *revision*; ``None`` if unknown."""
    completed = _run_git(
        root, "grep", "-q", "--fixed-strings", symbol, revision, "--", relpath
    )
    if completed is None:
        return None
    return completed.returncode == 0


def _culprit_commit(
    root: str, boot_rev: str, relpath: str, symbol: str
) -> tuple[str | None, str | None]:
    """Name the commit that changed *symbol* between boot and HEAD."""
    completed = _run_git(
        root,
        "log",
        f"-S{symbol}",
        "--format=%H%x00%s",
        f"{boot_rev}..HEAD",
        "--",
        relpath,
    )
    if completed is None or completed.returncode != 0:
        return None, None
    first_line = (completed.stdout or "").splitlines()
    if not first_line:
        return None, None
    commit, _, subject = first_line[0].partition("\x00")
    commit = commit.strip()
    if not commit:
        return None, None
    return commit, subject.strip() or None


def _collect_file_proof(
    *,
    module: str,
    symbol: str | None,
    root: ManagedRoot,
    boot_rev: str | None,
) -> AutoRestartFileProofWire | None:
    """Collect W3 file-level proof with bounded git calls.

    Returns ``None`` when nothing could be established (no git repo, no
    known revision, unknown module path). Partial knowledge is returned
    as a proof with ``None`` fields rather than dropped.
    """
    source_root = root.source_root
    if not source_root:
        return None
    head = _run_git(source_root, "rev-parse", "HEAD")
    head_rev = (
        (head.stdout or "").strip()
        if head is not None and head.returncode == 0
        else None
    )
    revisions = [rev for rev in (boot_rev, head_rev, "HEAD") if rev]
    relpath = _pick_relpath(source_root, module, revisions)
    if relpath is None:
        return None
    if symbol:
        boot_has = (
            _grep_at_revision(source_root, boot_rev, relpath, symbol)
            if boot_rev
            else None
        )
        head_has = _grep_at_revision(source_root, head_rev or "HEAD", relpath, symbol)
        culprit_commit: str | None = None
        culprit_subject: str | None = None
        if boot_rev:
            culprit_commit, culprit_subject = _culprit_commit(
                source_root, boot_rev, relpath, symbol
            )
        return AutoRestartFileProofWire(
            symbol=symbol,
            module=module,
            boot_has=boot_has,
            head_has=head_has,
            culprit_commit=culprit_commit,
            culprit_subject=culprit_subject,
        )
    boot_has_file: bool | None = None
    head_has_file: bool | None = None
    if boot_rev:
        completed = _run_git(source_root, "cat-file", "-e", f"{boot_rev}:{relpath}")
        if completed is not None:
            boot_has_file = completed.returncode == 0
    completed = _run_git(
        source_root, "cat-file", "-e", f"{head_rev or 'HEAD'}:{relpath}"
    )
    if completed is not None:
        head_has_file = completed.returncode == 0
    if boot_has_file is None and head_has_file is None:
        return None
    return AutoRestartFileProofWire(
        symbol=None,
        module=module,
        boot_has=boot_has_file,
        head_has=head_has_file,
        culprit_commit=None,
        culprit_subject=None,
    )


def _boot_commit_for_root(
    boot_identity: Mapping[str, Any] | None, root: ManagedRoot
) -> str | None:
    """Return the boot commit recorded for *root*, if any."""
    if not isinstance(boot_identity, Mapping):
        return None
    raw_roots = boot_identity.get("roots")
    if not isinstance(raw_roots, list):
        return None
    for entry in raw_roots:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("name") == root.name:
            commit = entry.get("commit")
            if isinstance(commit, str) and commit:
                return commit
    return None


def collect_witnesses(inputs: WitnessInputs) -> AutoRestartWitnessesWire:
    """Collect the W1-W3 witness bundle for one failed agent."""
    boot_digest = code_identity_digest(inputs.boot_identity)
    current_digest = code_identity_digest(current_code_identity())
    journal_updates = _collect_journal_updates(
        journal_path=inputs.journal_path,
        booted_at=inputs.booted_at,
        finished_at=inputs.finished_at,
        artifacts_timestamp=inputs.artifacts_timestamp,
        done_mtime=inputs.done_mtime,
    )
    refresh_log_line = _parse_refresh_log_line(inputs.log_tail)
    file_proof = _collect_witness_file_proof(inputs, refresh_log_line)
    return AutoRestartWitnessesWire(
        boot_identity=boot_digest,
        current_identity=current_digest,
        journal_updates=tuple(journal_updates),
        file_proof=file_proof,
        probe=None,
        refresh_log_line=refresh_log_line,
    )


def _collect_witness_file_proof(
    inputs: WitnessInputs,
    refresh_log_line: AutoRestartRefreshLogLineWire | None,
) -> AutoRestartFileProofWire | None:
    """Collect W3, gated on the cheap skew prefilter.

    The prefilter gate is the real consumer the ``sase-1j6`` epic-symbol
    row was waiting for: without skew-shaped text there is no symbol
    worth proving, so the bounded git calls are skipped outright.
    """
    from sase.axe.runner_failure_facts import facts_look_like_update_skew

    if not inputs.enable_file_proof:
        return None
    prefilter_facts: dict[str, Any]
    if isinstance(inputs.facts, Mapping):
        prefilter_facts = dict(inputs.facts)
    else:
        prefilter_facts = {
            "error_text": f"{inputs.error_text}\n{inputs.traceback_text}",
        }
    if not facts_look_like_update_skew(prefilter_facts):
        return None
    module, symbol = _extract_proof_target(
        inputs.facts if isinstance(inputs.facts, Mapping) else None,
        error_text=inputs.error_text,
        traceback_text=inputs.traceback_text,
    )
    if module is None:
        return None
    root = _select_proof_root(module, inputs.managed_roots)
    if root is None:
        return None
    boot_rev = _boot_commit_for_root(inputs.boot_identity, root)
    if boot_rev is None and refresh_log_line is not None and root.role == "host":
        boot_rev = refresh_log_line.from_rev or None
    if boot_rev is None:
        return None
    return _collect_file_proof(
        module=module, symbol=symbol, root=root, boot_rev=boot_rev
    )


def _parse_time(value: Any) -> datetime.datetime | None:
    """Parse ISO strings, epoch numbers, and artifact timestamps.

    Naive values are interpreted in the configured local timezone:
    artifact directory names and journal rows are local-time
    constructions, so reading them as UTC would shift W2 windows by
    the UTC offset.
    """
    local = get_timezone()
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(float(value), tz=datetime.UTC)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=local)
        return parsed
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 14:
        try:
            parsed = datetime.datetime.strptime(digits, "%Y%m%d%H%M%S")
        except ValueError:
            return None
        return parsed.replace(tzinfo=local)
    if len(digits) == 12:
        try:
            parsed = datetime.datetime.strptime(digits, "%y%m%d%H%M%S")
        except ValueError:
            return None
        return parsed.replace(tzinfo=local)
    return None


def _collect_journal_updates(
    *,
    journal_path: Path | None,
    booted_at: str | None,
    finished_at: float | None,
    artifacts_timestamp: str | None,
    done_mtime: float | None,
) -> list[str]:
    """Return journal update timestamps between boot and the failure.

    The window starts at ``booted_at`` (falling back to the artifacts
    timestamp, which approximates launch for agents that waited) and ends
    at ``finished_at`` (falling back to the ``done.json`` mtime, then to
    now). A later update must never count: the window end is always the
    failure, not the scan time. Without a launch bound there is no
    window, so nothing matches.
    """
    if journal_path is None:
        from sase.dev_update.journal import dev_update_journal_path

        journal_path = dev_update_journal_path()
    start = _parse_time(booted_at) or _parse_time(artifacts_timestamp)
    if start is None:
        return []
    end = (
        _parse_time(finished_at)
        or _parse_time(done_mtime)
        or datetime.datetime.now(datetime.UTC)
    )
    if start > end:
        start, end = end, start
    try:
        lines = journal_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    updates: list[str] = []
    for line in lines:
        if len(updates) >= MAX_JOURNAL_UPDATES:
            break
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        stamp = _parse_time(record.get("timestamp"))
        if stamp is None:
            continue
        if stamp < start:
            continue
        if stamp > end:
            continue
        raw = record.get("timestamp")
        updates.append(str(raw) if raw is not None else stamp.isoformat())
    return updates


__all__ = [
    "GIT_PROBE_TIMEOUT_SECONDS",
    "MAX_JOURNAL_UPDATES",
    "WitnessInputs",
    "collect_witnesses",
]
