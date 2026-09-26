"""``sase tool receipts`` opportunity report over retained verdict receipts.

Lists retained verdict receipts and measures content-equivalent verification
repeats: how often a named tool re-ran on a content-identical tree. The
comparison is content-addressed — it compares Git blobs by content, not only
HEAD — so a verified dirty tree that is later committed and rechecked at a
new HEAD counts as a repeat opportunity. Toolchain, environment, extra
arguments, and catalog identity stay in the key.

The report informs a later reuse decision; it never changes what ``run``
executes. Every ``sase tool run`` still spawns its child. A measurement
opportunity is not a covering receipt: use ``sase tool receipt TOOL`` to ask
whether the current tree is covered now. Runs whose history is unavailable
(missing Git objects, unresolvable repos, incomplete fingerprints) are
reported as uncomparable, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from sase.config.tools import tool_project_identity
from sase.content_layout import discover_project_root
from sase.core.tool_run import tool_run_store_path
from sase.tool.liveness import reconcile_unsettled_tool_runs
from sase.tool.render import EMPTY

_DELETED = "<deleted>"
_MAX_RUNS = 500
_MAX_UNCOMPARABLE = 50
_MAX_GIT_CALLS = 400
_GIT_TIMEOUT_SECONDS = 10

_MEASUREMENT_NOTE = (
    "opportunities are measurement only; every `sase tool run` still "
    "executes its child. An opportunity is not a covering receipt: "
    "run `sase tool receipt TOOL` to ask whether the current tree is covered."
)


class _ReceiptsQueryError(ValueError):
    """User-facing receipts usage error (exit 2)."""


@dataclass(frozen=True)
class ToolReceiptsCliRequest:
    days: int
    json: bool


def handle_receipts(request: ToolReceiptsCliRequest) -> int:
    """Render ``sase tool receipts``; 0 reported, 1 store failure, 2 usage."""

    try:
        days = _validate_days(request.days)
    except _ReceiptsQueryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    reconcile_unsettled_tool_runs()
    project = tool_project_identity()
    now_ts = int(time.time())
    try:
        envelope = _build_envelope(project, days, now_ts)
    except Exception as exc:  # noqa: BLE001 - query failures are nonzero.
        print(f"receipts report failed: {exc}", file=sys.stderr)
        return 1
    if request.json:
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return 0
    _print_human(envelope)
    for diagnostic in envelope.get("diagnostics") or ():
        print(str(diagnostic), file=sys.stderr)
    return 0


def _validate_days(days: int) -> int:
    if days < 0:
        raise _ReceiptsQueryError("-d/--days must be >= 0")
    return days


def _build_envelope(project: str, days: int, now_ts: int) -> dict[str, Any]:
    """Assemble the versioned receipts opportunity envelope."""

    since_ts = now_ts - days * 86400
    store_path = str(tool_run_store_path())
    receipts, runs, truncated, diagnostics = _load_ledger(store_path, project, since_ts)
    receipt_items: list[dict[str, Any]] = []
    active = expired = superseded = 0
    for receipt in receipts:
        expiry = receipt.expiry_ts
        is_expired = expiry <= now_ts
        status = receipt.status
        if status == "active" and not is_expired:
            active += 1
        elif is_expired:
            expired += 1
        else:
            superseded += 1
        receipt_items.append(
            {
                "receipt_id": receipt.receipt_id,
                "run_id": receipt.source_run_id,
                "tool": receipt.tool_name,
                "verdict": receipt.verdict,
                "age_seconds": max(0, now_ts - receipt.mint_ts),
                "expired": is_expired,
                "status": status,
            }
        )
    index = _GitContentIndex(project)
    groups, uncomparable = _find_opportunities(runs, index)
    group_entries: list[dict[str, Any]] = []
    per_tool: dict[str, dict[str, int]] = {}
    repeat_runs = 0
    repeat_duration_ms = 0
    for position, group in enumerate(groups, start=1):
        ordered = sorted(group, key=lambda run: (run.created_ts, run.run_id))
        repeats = ordered[1:]
        saved_ms = sum(run.duration_ms or 0 for run in repeats)
        heads = {head for run in ordered for head in run.heads()}
        entry = {
            "group_id": position,
            "tool": ordered[0].tool,
            "run_ids": [run.run_id for run in ordered],
            "first_ts": ordered[0].created_ts,
            "last_ts": ordered[-1].created_ts,
            "runs": len(ordered),
            "repeat_runs": len(repeats),
            "repeat_duration_ms": saved_ms,
            "spans_commits": len(heads) > 1,
            "repos": sorted({repo for run in ordered for repo in run.repos()}),
        }
        group_entries.append(entry)
        repeat_runs += len(repeats)
        repeat_duration_ms += saved_ms
        tool_stats = per_tool.setdefault(
            ordered[0].tool, {"groups": 0, "repeat_runs": 0, "repeat_ms": 0}
        )
        tool_stats["groups"] += 1
        tool_stats["repeat_runs"] += len(repeats)
        tool_stats["repeat_ms"] += saved_ms
    top_tools = [
        {
            "tool": tool,
            "groups": stats["groups"],
            "repeat_runs": stats["repeat_runs"],
            "repeat_duration_ms": stats["repeat_ms"],
        }
        for tool, stats in sorted(
            per_tool.items(),
            key=lambda item: (-item[1]["repeat_runs"], -item[1]["repeat_ms"]),
        )
    ]
    uncomparable_entries = [
        {"run_id": run_id, "tool": tool, "reason": reason}
        for run_id, tool, reason in uncomparable[:_MAX_UNCOMPARABLE]
    ]
    return {
        "schema_version": 1,
        "project": project,
        "window": {"days": days, "since_ts": since_ts, "now_ts": now_ts},
        "receipts": {
            "count": len(receipt_items),
            "active": active,
            "expired": expired,
            "superseded": superseded,
            "items": receipt_items,
        },
        "opportunities": {
            "group_count": len(group_entries),
            "repeat_runs": repeat_runs,
            "repeat_duration_ms": repeat_duration_ms,
            "repeat_hours": round(repeat_duration_ms / 3600000, 2),
            "groups": group_entries,
            "top_tools": top_tools,
        },
        "uncomparable": {
            "count": len(uncomparable),
            "truncated": len(uncomparable) > len(uncomparable_entries),
            "runs": uncomparable_entries,
        },
        "runs_scanned": len(runs),
        "runs_truncated": truncated,
        "note": _MEASUREMENT_NOTE,
        "diagnostics": diagnostics,
    }


@dataclass
class _LedgerReceipt:
    receipt_id: str
    source_run_id: str
    tool_name: str
    verdict: str
    mint_ts: int
    expiry_ts: int
    status: str


@dataclass
class _LedgerRun:
    run_id: str
    tool: str
    definition_digest: str
    extra_args_digest: str
    created_ts: int
    duration_ms: int | None
    fingerprint: dict[str, Any] | None

    def repos(self) -> list[str]:
        if not self.fingerprint:
            return []
        return [
            str(repo.get("identity") or "")
            for repo in self.fingerprint.get("repos") or ()
            if isinstance(repo, dict)
        ]

    def heads(self) -> list[str]:
        if not self.fingerprint:
            return []
        return [
            str(repo.get("head") or "")
            for repo in self.fingerprint.get("repos") or ()
            if isinstance(repo, dict) and repo.get("head")
        ]


def _load_ledger(
    store_path: str, project: str, since_ts: int
) -> tuple[list[_LedgerReceipt], list[_LedgerRun], bool, list[str]]:
    """Read receipts and windowed runs without ever writing to the store."""

    try:
        connection = sqlite3.connect(f"file:{store_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return [], [], False, ["tool run store does not exist"]
    try:
        receipts = _load_receipts(connection, project, since_ts)
        runs, truncated = _load_runs(connection, project, since_ts)
    except sqlite3.Error as exc:
        if "no such table" in str(exc):
            return [], [], False, [f"receipt ledger unavailable: {exc}"]
        raise
    finally:
        connection.close()
    return receipts, runs, truncated, []


def _load_receipts(
    connection: sqlite3.Connection, project: str, since_ts: int
) -> list[_LedgerReceipt]:
    try:
        rows = connection.execute(
            "SELECT receipt_id, source_run_id, tool_name, verdict,"
            " mint_ts, expiry_ts, status FROM tool_receipts"
            " WHERE project = ? AND mint_ts >= ? ORDER BY mint_ts DESC",
            (project, since_ts),
        ).fetchall()
    except sqlite3.Error as exc:
        if "no such table" in str(exc):
            return []
        raise
    return [
        _LedgerReceipt(
            receipt_id=str(row[0]),
            source_run_id=str(row[1]),
            tool_name=str(row[2]),
            verdict=str(row[3]),
            mint_ts=int(row[4]),
            expiry_ts=int(row[5]),
            status=str(row[6]),
        )
        for row in rows
    ]


def _load_runs(
    connection: sqlite3.Connection, project: str, since_ts: int
) -> tuple[list[_LedgerRun], bool]:
    rows = connection.execute(
        "SELECT run_id, tool_name, definition_digest, extra_args_digest,"
        " created_ts, duration_ms, fingerprint_after_json FROM runs"
        " WHERE project = ? AND created_ts >= ?"
        " ORDER BY created_ts DESC LIMIT ?",
        (project, since_ts, _MAX_RUNS + 1),
    ).fetchall()
    truncated = len(rows) > _MAX_RUNS
    runs: list[_LedgerRun] = []
    for row in rows[:_MAX_RUNS]:
        fingerprint: dict[str, Any] | None = None
        if row[6]:
            try:
                parsed = json.loads(str(row[6]))
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, dict):
                fingerprint = parsed
        duration = row[5]
        runs.append(
            _LedgerRun(
                run_id=str(row[0]),
                tool=str(row[1] or ""),
                definition_digest=str(row[2] or ""),
                extra_args_digest=str(row[3] or ""),
                created_ts=int(row[4]),
                duration_ms=int(duration) if duration is not None else None,
                fingerprint=fingerprint,
            )
        )
    return runs, truncated


class _Uncomparable(Exception):
    """One run cannot be content-compared; record the reason, never guess."""


class _GitContentIndex:
    """Bounded cache of Git object facts used for content comparison."""

    def __init__(self, project: str) -> None:
        self._project = project
        found = discover_project_root()
        self._root = found if found is not None else Path.cwd()
        self._repo_paths: dict[str, Path | None] = {}
        self._head_exists: dict[tuple[str, str], bool] = {}
        self._diff_names: dict[tuple[str, str, str], frozenset[str] | None] = {}
        self._blob_hashes: dict[tuple[str, str, str], str | None] = {}
        self.calls = 0

    def _budgeted(self) -> None:
        if self.calls >= _MAX_GIT_CALLS:
            raise _Uncomparable("content comparison budget exceeded")

    def _run_git(self, repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
        self._budgeted()
        self.calls += 1
        return subprocess.run(
            ("git", "-C", str(repo), *args),
            check=False,
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )

    def repo_path(self, identity: str) -> Path:
        """Resolve a fingerprint repo identity to a local checkout."""

        if identity not in self._repo_paths:
            path: Path | None = None
            if identity == self._project or identity in {"current", "."}:
                candidate = self._git_root(self._root)
                path = candidate if candidate is not None else self._root
            else:
                clone = self._root.joinpath("sase", "repos", "linked", identity)
                if self._is_git_dir(clone):
                    path = clone
            self._repo_paths[identity] = path
        resolved = self._repo_paths[identity]
        if resolved is None:
            raise _Uncomparable(f"unresolvable repo {identity!r}")
        return resolved

    @staticmethod
    def _is_git_dir(path: Path) -> bool:
        return path.is_dir() and ((path / ".git").exists() or (path / "HEAD").exists())

    def _git_root(self, start: Path) -> Path | None:
        try:
            self.calls += 1
            proc = subprocess.run(
                ("git", "-C", str(start), "rev-parse", "--show-toplevel"),
                check=False,
                capture_output=True,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        return Path(proc.stdout.decode("utf-8", "replace").strip() or str(start))

    def head_exists(self, repo: Path, head: str) -> bool:
        key = (str(repo), head)
        if key not in self._head_exists:
            try:
                proc = self._run_git(repo, "cat-file", "-e", head)
            except (OSError, subprocess.SubprocessError):
                self._head_exists[key] = False
            else:
                self._head_exists[key] = proc.returncode == 0
        return self._head_exists[key]

    def diff_names(self, repo: Path, first: str, second: str) -> frozenset[str]:
        key = (str(repo), first, second)
        if key not in self._diff_names:
            try:
                proc = self._run_git(repo, "diff", "--name-only", first, second)
            except (OSError, subprocess.SubprocessError):
                self._diff_names[key] = None
            else:
                if proc.returncode != 0:
                    self._diff_names[key] = None
                else:
                    names = {
                        line
                        for line in proc.stdout.decode("utf-8", "replace").splitlines()
                        if line.strip()
                    }
                    self._diff_names[key] = frozenset(names)
        result = self._diff_names[key]
        if result is None:
            raise _Uncomparable("cannot diff commits")
        return result

    def blob_sha256(self, repo: Path, head: str, path: str) -> str | None:
        """Return the sha256 of ``path`` at ``head``, or None when absent."""

        key = (str(repo), head, path)
        if key not in self._blob_hashes:
            try:
                proc = self._run_git(repo, "show", f"{head}:{path}")
            except (OSError, subprocess.SubprocessError):
                self._blob_hashes[key] = None
            else:
                if proc.returncode != 0:
                    self._blob_hashes[key] = None
                else:
                    self._blob_hashes[key] = hashlib.sha256(proc.stdout).hexdigest()
        return self._blob_hashes[key]


def _find_opportunities(
    runs: list[_LedgerRun], index: _GitContentIndex
) -> tuple[list[list[_LedgerRun]], list[tuple[str, str, str]]]:
    """Group content-equivalent runs; collect uncomparable runs with reasons."""

    comparable: list[_LedgerRun] = []
    keys: dict[str, tuple[Any, ...]] = {}
    uncomparable: list[tuple[str, str, str]] = []
    for run in runs:
        try:
            keys[run.run_id] = _base_key(run)
        except _Uncomparable as exc:
            uncomparable.append((run.run_id, run.tool, str(exc)))
            continue
        comparable.append(run)
    parents = {run.run_id: run.run_id for run in comparable}

    def find(run_id: str) -> str:
        while parents[run_id] != run_id:
            parents[run_id] = parents[parents[run_id]]
            run_id = parents[run_id]
        return run_id

    for position, left in enumerate(comparable):
        for right in comparable[position + 1 :]:
            if keys[left.run_id] != keys[right.run_id]:
                continue
            try:
                equivalent = _runs_equivalent(left, right, index)
            except _Uncomparable as exc:
                uncomparable.append((right.run_id, right.tool, str(exc)))
                continue
            if equivalent:
                parents[find(left.run_id)] = find(right.run_id)
    buckets: dict[str, list[_LedgerRun]] = {}
    for run in comparable:
        if any(entry[0] == run.run_id for entry in uncomparable):
            continue
        buckets.setdefault(find(run.run_id), []).append(run)
    groups = [bucket for bucket in buckets.values() if len(bucket) > 1]
    groups.sort(key=lambda bucket: min(run.created_ts for run in bucket))
    return groups, uncomparable


def _base_key(run: _LedgerRun) -> tuple[Any, ...]:
    """Return the non-tree comparison key, or raise _Uncomparable."""

    fingerprint = run.fingerprint
    if not fingerprint:
        raise _Uncomparable("missing fingerprint")
    completeness = fingerprint.get("completeness") or {}
    if not isinstance(completeness, dict) or not completeness.get("complete"):
        missing = (
            completeness.get("missing") if isinstance(completeness, dict) else None
        )
        detail = ", ".join(str(item) for item in missing or ()) or "incomplete"
        raise _Uncomparable(f"incomplete fingerprint: {detail}")
    toolchain: list[tuple[str, str | None, int | None]] = []
    raw_toolchain = fingerprint.get("toolchain") or {}
    if not isinstance(raw_toolchain, dict):
        raise _Uncomparable("malformed toolchain snapshot")
    for name in sorted(raw_toolchain):
        probe = raw_toolchain[name]
        if not isinstance(probe, dict) or probe.get("incomplete"):
            raise _Uncomparable(f"incomplete toolchain probe {name!r}")
        toolchain.append((str(name), probe.get("output"), probe.get("exit_code")))
    env = fingerprint.get("env") or {}
    if not isinstance(env, dict):
        raise _Uncomparable("malformed env snapshot")
    inputs: list[tuple[str, str, str | None]] = []
    for record in fingerprint.get("inputs") or ():
        if not isinstance(record, dict):
            raise _Uncomparable("malformed input snapshot")
        if record.get("incomplete"):
            raise _Uncomparable(f"incomplete input {record.get('pattern')!r}")
        for match in record.get("matches") or ():
            if not isinstance(match, dict):
                raise _Uncomparable("malformed input snapshot")
            if match.get("incomplete"):
                raise _Uncomparable(f"incomplete input {record.get('pattern')!r}")
            inputs.append(
                (
                    str(record.get("pattern") or ""),
                    str(match.get("path") or ""),
                    match.get("content_hash"),
                )
            )
    return (
        run.tool,
        run.definition_digest,
        run.extra_args_digest,
        tuple(toolchain),
        tuple(sorted((str(key), value) for key, value in env.items())),
        tuple(sorted(inputs)),
    )


def _repo_views(run: _LedgerRun) -> dict[str, tuple[str | None, dict[str, str]]]:
    """Return ``{identity: (head, {path: content-hash-or-DELETED})}``."""

    fingerprint = run.fingerprint or {}
    views: dict[str, tuple[str | None, dict[str, str]]] = {}
    for repo in fingerprint.get("repos") or ():
        if not isinstance(repo, dict):
            raise _Uncomparable("malformed repo snapshot")
        identity = str(repo.get("identity") or "")
        if repo.get("incomplete"):
            raise _Uncomparable(f"incomplete repo {identity!r}")
        dirty: dict[str, str] = {}
        for entry in repo.get("dirty_paths") or ():
            if not isinstance(entry, dict):
                raise _Uncomparable(f"malformed dirty paths in {identity!r}")
            path = str(entry.get("path") or "")
            if entry.get("incomplete") or (
                entry.get("kind") != "deleted" and not entry.get("content_hash")
            ):
                raise _Uncomparable(f"unhashed dirty path {path!r}")
            dirty[path] = (
                _DELETED
                if entry.get("kind") == "deleted"
                else str(entry.get("content_hash"))
            )
        views[identity] = (repo.get("head"), dirty)
    return views


def _runs_equivalent(
    left: _LedgerRun, right: _LedgerRun, index: _GitContentIndex
) -> bool:
    """Return whether two same-key runs observed content-identical trees."""

    left_views = _repo_views(left)
    right_views = _repo_views(right)
    if set(left_views) != set(right_views):
        return False
    for identity in left_views:
        left_head, left_dirty = left_views[identity]
        right_head, right_dirty = right_views[identity]
        if left_head == right_head and left_head is not None:
            if left_dirty != right_dirty:
                return False
            continue
        repo = index.repo_path(identity)
        for head in (left_head, right_head):
            if not head or not index.head_exists(repo, head):
                raise _Uncomparable(f"missing Git object {head or 'HEAD'!r}")
        assert left_head is not None and right_head is not None
        changed = index.diff_names(repo, left_head, right_head)
        if not changed <= set(left_dirty) | set(right_dirty):
            return False
        for path in set(left_dirty) | set(right_dirty):
            if left_dirty.get(path, _MISSING) == right_dirty.get(path, _MISSING):
                continue
            if not _dirty_matches_other_side(
                index, repo, path, left_head, left_dirty, right_head, right_dirty
            ):
                return False
    return True


_MISSING = "<absent>"


def _dirty_matches_other_side(
    index: _GitContentIndex,
    repo: Path,
    path: str,
    left_head: str,
    left_dirty: dict[str, str],
    right_head: str,
    right_dirty: dict[str, str],
) -> bool:
    """Check one dirty path's content against the opposite commit."""

    left_value = left_dirty.get(path, _MISSING)
    right_value = right_dirty.get(path, _MISSING)
    left_committed = index.blob_sha256(repo, left_head, path)
    right_committed = index.blob_sha256(repo, right_head, path)
    left_actual = (
        left_value
        if left_value != _MISSING
        else (left_committed if left_committed is not None else _DELETED)
    )
    right_actual = (
        right_value
        if right_value != _MISSING
        else (right_committed if right_committed is not None else _DELETED)
    )
    if left_actual == _DELETED or right_actual == _DELETED:
        return left_actual == right_actual
    if left_actual != _MISSING and right_actual != _MISSING:
        return left_actual == right_actual
    return False


def _print_human(envelope: dict[str, Any]) -> None:
    console = Console(width=120, highlight=False)
    receipts = envelope.get("receipts") or {}
    items = [item for item in receipts.get("items") or () if isinstance(item, dict)]
    window = envelope.get("window") or {}
    console.print(
        f"receipts for {envelope.get('project')} "
        f"(last {window.get('days')}d): "
        f"{receipts.get('count', 0)} retained "
        f"({receipts.get('active', 0)} active, "
        f"{receipts.get('expired', 0)} expired, "
        f"{receipts.get('superseded', 0)} superseded)"
    )
    if not items:
        print("no recorded receipts")
    else:
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("TOOL", no_wrap=True)
        table.add_column("RECEIPT", overflow="fold")
        table.add_column("VERDICT", no_wrap=True)
        table.add_column("AGE", no_wrap=True)
        table.add_column("STATUS", no_wrap=True)
        for item in items:
            status = str(item.get("status") or EMPTY)
            if item.get("expired"):
                status = "expired"
            table.add_row(
                str(item.get("tool") or EMPTY),
                _short_id(item.get("receipt_id")),
                str(item.get("verdict") or EMPTY),
                _format_age(item.get("age_seconds")),
                _format_status(status),
            )
        console.print(table)
    opportunities = envelope.get("opportunities") or {}
    groups = [
        group for group in opportunities.get("groups") or () if isinstance(group, dict)
    ]
    console.print(
        f"content-equivalent repeats: {opportunities.get('group_count', 0)} groups, "
        f"{opportunities.get('repeat_runs', 0)} repeat runs, "
        f"{opportunities.get('repeat_hours', 0)}h summed duration"
    )
    if groups:
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("GROUP", no_wrap=True)
        table.add_column("TOOL", no_wrap=True)
        table.add_column("RUNS", no_wrap=True)
        table.add_column("SAVED", no_wrap=True)
        table.add_column("COMMITS", no_wrap=True)
        for group in groups:
            table.add_row(
                str(group.get("group_id") or EMPTY),
                str(group.get("tool") or EMPTY),
                str(group.get("runs") or EMPTY),
                _format_duration_ms(group.get("repeat_duration_ms")),
                "dirty-to-commit" if group.get("spans_commits") else "same HEAD",
            )
        console.print(table)
        top_tools = [
            entry
            for entry in opportunities.get("top_tools") or ()
            if isinstance(entry, dict)
        ]
        for entry in top_tools[:5]:
            console.print(
                f"  {entry.get('tool')}: "
                f"{entry.get('repeat_runs')} repeats, "
                f"{_format_duration_ms(entry.get('repeat_duration_ms'))}"
            )
    else:
        print("no content-equivalent repeats")
    uncomparable = envelope.get("uncomparable") or {}
    if uncomparable.get("count"):
        print(
            f"{uncomparable.get('count')} runs uncomparable"
            + (" (truncated)" if uncomparable.get("truncated") else "")
        )
    if envelope.get("runs_truncated"):
        print(f"run history truncated to the newest {_MAX_RUNS} runs")
    print(_MEASUREMENT_NOTE)


def _short_id(value: object) -> str:
    text = str(value or "").strip()
    return text[:12] if text else EMPTY


def _format_status(status: str) -> str:
    if status == "active":
        return "[green]active[/green]"
    if status == "expired":
        return "[yellow]expired[/yellow]"
    return f"[dim]{status or EMPTY}[/dim]"


def _format_age(age_seconds: object) -> str:
    if type(age_seconds) is bool or not isinstance(age_seconds, (int, float)):
        return EMPTY
    total = max(0, int(age_seconds))
    if total < 60:
        return f"{total}s"
    minutes, seconds = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _format_duration_ms(value: object) -> str:
    if type(value) is bool or not isinstance(value, (int, float)):
        return EMPTY
    total_ms = max(0, int(value))
    if total_ms < 1000:
        return f"{total_ms}ms"
    total_seconds = total_ms // 1000
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes, seconds = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


__all__ = ["ToolReceiptsCliRequest", "handle_receipts"]
