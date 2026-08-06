"""Durable selection-health store, false-negative detection, and reporting.

Diff-scoped selection is a heuristic (see :mod:`tests._test_selection`), so the
only honest way to run it as the default verification lane is to *measure*
whether it has ever been wrong. This module owns that measurement.

Two kinds of record land in one host-local store:

``selection``
    One per ``tools/run_pytest scoped`` run: the manifest the engine produced,
    plus the duration and outcome the runner appended.
``full-run``
    One per full-lane run (``just test`` / ``just check-full`` / the coverage
    leg): the node IDs that failed, and the commit they failed at.

A **false negative** is a test that failed in a full run and was *excluded* by a
scoped run over an ancestor of the same change. Correlating the two record
kinds is what turns "selection is probably fine" into a number.

The store lives under ``${SASE_HOME:-~/.sase}/test-selection/<project-key>/``
rather than in ``.pytest_cache``, because the numbered workspaces are ephemeral
and the correlation surface that matters spans them: a phase agent in
``sase_3`` and one in ``sase_11`` write manifests that a land agent in
``sase_7`` needs to read.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tests._test_selection_graph import SelectionError, is_visual_path, run_git


HEALTH_SCHEMA = 1

STORE_SUBDIRECTORY = "test-selection"
DEFAULT_SASE_HOME = Path("~/.sase")
RETENTION_DAYS = 30

SASE_HOME_ENV = "SASE_HOME"
#: Overrides the whole store location; the tests and `--store` use it.
STORE_ENV = "SASE_TEST_SELECTION_HEALTH_DIR"
#: Overrides the per-project namespace inside the store.
PROJECT_KEY_ENV = "SASE_TEST_SELECTION_HEALTH_PROJECT_KEY"
#: JSON handed to the full-lane pytest plugin by ``tools/run_pytest``. The
#: runner resolves the store in the parent process, so the plugin never has to
#: guess at a ``SASE_HOME`` that the suite's own fixtures redirect per test.
RECORD_ENV = "SASE_TEST_SELECTION_HEALTH_RECORD"

KIND_SELECTION = "selection"
KIND_FULL_RUN = "full-run"

#: The full suite's measured cost, in worker-seconds, from the Tier 1 research
#: report: 25,937 tests summed across twelve xdist workers. It is the baseline
#: a scoped run is credited against, and it is deliberately a constant: the
#: point of the metric is host demand avoided, not a re-measured wall time.
FULL_SUITE_WORKER_SECONDS = 3650.0

_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_RECORD_NAME_PATTERN = re.compile(
    r"^(?P<timestamp>\d{8}T\d{6}Z)-(?P<head>[0-9a-f]+|unknown)-(?P<pid>\d+)"
    r"(?:-(?P<kind>[a-z-]+))?\.json$"
)
_GITHUB_REMOTE_PATTERN = re.compile(
    r"github\.com[:/](?P<org>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)
_WORKSPACE_SUFFIX_PATTERN = re.compile(r"_\d+$")
_UNSAFE_KEY_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")


# --------------------------------------------------------------------------
# Store location
# --------------------------------------------------------------------------


def _key_from_remote_url(url: str) -> str | None:
    match = _GITHUB_REMOTE_PATTERN.search(url.strip())
    if match is None:
        return None
    return f"gh_{match['org']}__{match['repo']}"


def _key_from_root(root: Path) -> str:
    name = _WORKSPACE_SUFFIX_PATTERN.sub("", root.name)
    sanitized = _UNSAFE_KEY_CHARACTERS.sub("-", name).strip("-")
    return sanitized or "unknown"


def project_key(root: Path, environ: Mapping[str, str] | None = None) -> str:
    """Namespace the store by project, the way ProjectSpec keys do.

    The GitHub remote yields exactly SASE's ``gh_<org>__<repo>`` directory key,
    which is what makes one store shared by every numbered workspace of the
    same project. A repository with no usable remote falls back to its own
    directory name with the ``_<N>`` workspace suffix stripped, which shares
    the store across workspaces just as well.
    """
    environ = os.environ if environ is None else environ
    override = environ.get(PROJECT_KEY_ENV)
    if override:
        return override
    try:
        url = run_git(root, "remote", "get-url", "origin")
    except SelectionError:
        url = ""
    return _key_from_remote_url(url) or _key_from_root(root)


def store_directory(root: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the host-local record store for ``root``'s project."""
    environ = os.environ if environ is None else environ
    override = environ.get(STORE_ENV)
    if override:
        return Path(override).expanduser()
    sase_home = environ.get(SASE_HOME_ENV)
    home = Path(sase_home).expanduser() if sase_home else DEFAULT_SASE_HOME.expanduser()
    return home / STORE_SUBDIRECTORY / project_key(root, environ)


# --------------------------------------------------------------------------
# Writing records
# --------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def record_filename(kind: str, *, now: datetime, head: str | None, pid: int) -> str:
    stamp = now.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)
    short_head = (head or "unknown")[:12]
    suffix = "" if kind == KIND_SELECTION else f"-{kind}"
    return f"{stamp}-{short_head}-{pid}{suffix}.json"


def allocate_record_path(
    store: Path,
    kind: str,
    *,
    head: str | None,
    pid: int,
    now: datetime | None = None,
) -> Path:
    """Reserve a record path, creating and pruning the store on the way.

    Allocation is separate from writing because the full-lane recorder lives in
    a pytest plugin inside an ``execv``'d child: the runner picks the path (and
    pays the pruning cost) before handing off.
    """
    now = now or _now()
    store.mkdir(parents=True, exist_ok=True)
    prune_store(store, now=now)
    return store / record_filename(kind, now=now, head=head, pid=pid)


def write_record(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def record_selection(
    store: Path,
    manifest: Mapping[str, Any],
    *,
    pid: int | None = None,
    now: datetime | None = None,
) -> Path:
    """Persist a completed scoped-run manifest to the durable store."""
    head = str((manifest.get("baseline") or {}).get("head") or "") or None
    path = allocate_record_path(
        store,
        KIND_SELECTION,
        head=head,
        pid=os.getpid() if pid is None else pid,
        now=now,
    )
    write_record(
        path,
        {
            "schema": HEALTH_SCHEMA,
            "kind": KIND_SELECTION,
            "recorded_at": (now or _now()).astimezone(UTC).isoformat(),
            "manifest": dict(manifest),
        },
    )
    return path


def full_run_record(
    *,
    head: str | None,
    mode: str,
    failures: Sequence[str],
    exit_status: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    return {
        "schema": HEALTH_SCHEMA,
        "kind": KIND_FULL_RUN,
        "recorded_at": (now or _now()).astimezone(UTC).isoformat(),
        "head": head,
        "mode": mode,
        "exit_status": exit_status,
        "failures": sorted(set(failures)),
    }


def _record_timestamp(path: Path) -> datetime | None:
    match = _RECORD_NAME_PATTERN.match(path.name)
    if match is None:
        return None
    try:
        parsed = datetime.strptime(match["timestamp"], _TIMESTAMP_FORMAT)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC)


def prune_store(
    store: Path, *, now: datetime | None = None, retention_days: int = RETENTION_DAYS
) -> list[Path]:
    """Drop records older than ``retention_days``; return what was removed.

    Records whose names the store does not recognise are left alone: this
    directory is under the user's ``~/.sase``, and a pruner that deletes
    unfamiliar files there is a liability, not a feature.
    """
    cutoff = (now or _now()) - timedelta(days=retention_days)
    removed: list[Path] = []
    try:
        entries = sorted(store.iterdir())
    except OSError:
        return removed
    for entry in entries:
        stamp = _record_timestamp(entry)
        if stamp is None or stamp >= cutoff:
            continue
        try:
            entry.unlink()
        except OSError:
            continue
        removed.append(entry)
    return removed


# --------------------------------------------------------------------------
# Reading records
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectionRecord:
    name: str
    recorded_at: str | None
    manifest: dict[str, Any]

    @property
    def head(self) -> str | None:
        head = (self.manifest.get("baseline") or {}).get("head")
        return str(head) if head else None

    @property
    def escalated(self) -> bool:
        return bool(self.manifest.get("escalated"))

    @property
    def selected(self) -> frozenset[str]:
        return frozenset(str(path) for path in self.manifest.get("selected") or ())

    @property
    def selected_count(self) -> int:
        return int(self.manifest.get("selected_count") or 0)

    @property
    def rules(self) -> tuple[str, ...]:
        return tuple(str(rule) for rule in self.manifest.get("rules_fired") or ())

    @property
    def duration(self) -> float | None:
        duration = self.manifest.get("duration")
        return float(duration) if isinstance(duration, (int, float)) else None

    @property
    def outcome(self) -> str:
        return str(self.manifest.get("outcome") or "unknown")

    @property
    def contexts(self) -> dict[str, Any]:
        contexts = self.manifest.get("contexts")
        return contexts if isinstance(contexts, dict) else {}


@dataclass(frozen=True)
class FullRunRecord:
    name: str
    recorded_at: str | None
    head: str | None
    mode: str
    failures: tuple[str, ...]


@dataclass(frozen=True)
class HealthRecords:
    selections: tuple[SelectionRecord, ...] = ()
    full_runs: tuple[FullRunRecord, ...] = ()


def load_records(store: Path) -> HealthRecords:
    """Read every readable record in ``store``; ignore anything unparseable."""
    selections: list[SelectionRecord] = []
    full_runs: list[FullRunRecord] = []
    try:
        entries = sorted(store.glob("*.json"))
    except OSError:
        entries = []
    for entry in entries:
        try:
            payload = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        recorded_at = payload.get("recorded_at")
        recorded_at = str(recorded_at) if recorded_at else None
        kind = payload.get("kind")
        if kind == KIND_SELECTION and isinstance(payload.get("manifest"), dict):
            selections.append(
                SelectionRecord(
                    name=entry.name,
                    recorded_at=recorded_at,
                    manifest=payload["manifest"],
                )
            )
        elif kind == KIND_FULL_RUN:
            head = payload.get("head")
            full_runs.append(
                FullRunRecord(
                    name=entry.name,
                    recorded_at=recorded_at,
                    head=str(head) if head else None,
                    mode=str(payload.get("mode") or "unknown"),
                    failures=tuple(
                        str(failure) for failure in payload.get("failures") or ()
                    ),
                )
            )
    return HealthRecords(selections=tuple(selections), full_runs=tuple(full_runs))


# --------------------------------------------------------------------------
# False-negative detection
# --------------------------------------------------------------------------


AncestorOracle = Callable[[str, str], bool]


def git_ancestor_oracle(root: Path) -> AncestorOracle:
    """An ``is-ancestor`` predicate, memoised per commit pair.

    A commit this workspace has never fetched — a sibling workspace's manifest
    can name one — answers ``False`` rather than raising: an unverifiable
    ancestry claim must not be reported as a false negative.
    """
    cache: dict[tuple[str, str], bool] = {}

    def _is_ancestor(ancestor: str, descendant: str) -> bool:
        key = (ancestor, descendant)
        if key not in cache:
            try:
                run_git(root, "merge-base", "--is-ancestor", ancestor, descendant)
            except SelectionError:
                cache[key] = False
            else:
                cache[key] = True
        return cache[key]

    return _is_ancestor


def nodeid_test_file(nodeid: str) -> str:
    """The file part of a pytest node ID.

    Named subject-first rather than ``test_file_for_nodeid`` so importing it
    into a test module does not make pytest try to collect it.
    """
    return nodeid.split("::", 1)[0].replace("\\", "/")


@dataclass(frozen=True)
class FalseNegative:
    nodeid: str
    test_file: str
    selection_record: str
    selection_head: str | None
    full_run_record: str
    full_run_head: str | None
    rules: tuple[str, ...]


def find_false_negatives(
    records: HealthRecords, *, is_ancestor: AncestorOracle
) -> list[FalseNegative]:
    """Match full-run failures against scoped runs that excluded them.

    Escalated manifests are skipped because they ran everything: they excluded
    nothing and cannot have missed anything. Visual paths are skipped because
    the selector excludes them unconditionally and by design; ``just
    test-visual`` is their lane.
    """
    candidates = [
        selection
        for selection in records.selections
        if not selection.escalated and selection.head
    ]
    false_negatives: list[FalseNegative] = []
    for full_run in records.full_runs:
        if not full_run.head or not full_run.failures:
            continue
        for nodeid in full_run.failures:
            test_file = nodeid_test_file(nodeid)
            if is_visual_path(test_file):
                continue
            for selection in candidates:
                if test_file in selection.selected:
                    continue
                head = selection.head
                assert head is not None
                if not is_ancestor(head, full_run.head):
                    continue
                false_negatives.append(
                    FalseNegative(
                        nodeid=nodeid,
                        test_file=test_file,
                        selection_record=selection.name,
                        selection_head=head,
                        full_run_record=full_run.name,
                        full_run_head=full_run.head,
                        rules=selection.rules,
                    )
                )
    return false_negatives


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _median(values: Sequence[float]) -> float | None:
    return _percentile(values, 0.5)


@dataclass(frozen=True)
class SelectionHealth:
    scoped_runs: int = 0
    escalated_runs: int = 0
    full_runs: int = 0
    universe_count: int | None = None
    median_selected: float | None = None
    p90_selected: float | None = None
    median_duration: float | None = None
    worker_seconds_saved: float = 0.0
    rule_histogram: dict[str, int] = field(default_factory=dict)
    outcome_histogram: dict[str, int] = field(default_factory=dict)
    context_runs: int = 0
    context_stale_runs: int = 0
    context_selected_total: int = 0
    false_negatives: tuple[FalseNegative, ...] = ()

    @property
    def escalation_rate(self) -> float | None:
        if not self.scoped_runs:
            return None
        return self.escalated_runs / self.scoped_runs

    @property
    def median_selected_ratio(self) -> float | None:
        if self.median_selected is None or not self.universe_count:
            return None
        return self.median_selected / self.universe_count


def summarize(
    records: HealthRecords, *, is_ancestor: AncestorOracle
) -> SelectionHealth:
    """Reduce the store to the numbers the project owner reads."""
    scoped = records.selections
    unescalated = [selection for selection in scoped if not selection.escalated]
    selected_counts = [float(selection.selected_count) for selection in unescalated]
    durations = [
        selection.duration
        for selection in unescalated
        if selection.duration is not None
    ]

    rule_histogram: dict[str, int] = {}
    outcome_histogram: dict[str, int] = {}
    for selection in scoped:
        for rule in selection.rules:
            rule_histogram[rule] = rule_histogram.get(rule, 0) + 1
        outcome_histogram[selection.outcome] = (
            outcome_histogram.get(selection.outcome, 0) + 1
        )

    saved = sum(
        max(0.0, FULL_SUITE_WORKER_SECONDS - (selection.duration or 0.0))
        for selection in unescalated
    )
    universes = [
        int(selection.manifest.get("universe_count") or 0)
        for selection in scoped
        if selection.manifest.get("universe_count")
    ]

    with_baseline = [
        selection.contexts for selection in scoped if selection.contexts.get("baseline")
    ]

    return SelectionHealth(
        scoped_runs=len(scoped),
        escalated_runs=len(scoped) - len(unescalated),
        full_runs=len(records.full_runs),
        universe_count=max(universes) if universes else None,
        median_selected=_median(selected_counts),
        p90_selected=_percentile(selected_counts, 0.9),
        median_duration=_median(durations),
        worker_seconds_saved=saved,
        rule_histogram=dict(sorted(rule_histogram.items())),
        outcome_histogram=dict(sorted(outcome_histogram.items())),
        context_runs=len(with_baseline),
        context_stale_runs=sum(
            1 for contexts in with_baseline if contexts.get("stale")
        ),
        context_selected_total=sum(
            int(contexts.get("selected_count") or 0) for contexts in with_baseline
        ),
        false_negatives=tuple(find_false_negatives(records, is_ancestor=is_ancestor)),
    )


def _format_count(value: float | None, *, universe: int | None) -> str:
    if value is None:
        return "n/a"
    if universe:
        return f"{value:.0f} ({value / universe:.1%} of {universe})"
    return f"{value:.0f}"


def _format_seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}s"


def render_report(health: SelectionHealth) -> list[str]:
    """Render the store as prose a human can act on, not a JSON dump."""
    lines = ["Diff-scoped test selection health", ""]
    if not health.scoped_runs and not health.full_runs:
        lines.append("No runs recorded yet. Run `just check` to record one.")
        return lines

    rate = health.escalation_rate
    lines.extend(
        [
            f"scoped runs recorded:   {health.scoped_runs}",
            f"  escalated to full:    {health.escalated_runs}"
            + (f" ({rate:.1%})" if rate is not None else ""),
            "  median selected:      "
            + _format_count(health.median_selected, universe=health.universe_count),
            "  p90 selected:         "
            + _format_count(health.p90_selected, universe=health.universe_count),
            f"  median duration:      {_format_seconds(health.median_duration)}",
            f"full-lane runs recorded: {health.full_runs}",
            "",
            "worker-seconds avoided vs. running the full suite instead: "
            f"{health.worker_seconds_saved:,.0f}"
            f" (~{health.worker_seconds_saved / 60:,.0f} worker-minutes, "
            f"at {FULL_SUITE_WORKER_SECONDS:,.0f}s per full run)",
            "",
        ]
    )

    lines.append("broadening rules fired:")
    if health.rule_histogram:
        for rule, count in health.rule_histogram.items():
            lines.append(f"  {count:>4}  {rule}")
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append("scoped run outcomes:")
    if health.outcome_histogram:
        for outcome, count in health.outcome_histogram.items():
            lines.append(f"  {count:>4}  {outcome}")
    else:
        lines.append("  (none)")
    lines.append("")

    lines.extend(_render_contexts(health))
    lines.append("")

    lines.extend(_render_false_negatives(health))
    return lines


def _render_contexts(health: SelectionHealth) -> list[str]:
    """Whether per-test coverage ground truth is reaching these runs at all.

    This is the reading that says whether contexts earn their CI cost: runs
    with no baseline got the static closure alone, and a high stale count next
    to a non-zero false-negative count is the signal to refresh more often.
    """
    if not health.scoped_runs:
        return ["coverage contexts: no scoped runs recorded"]
    without = health.scoped_runs - health.context_runs
    lines = [
        "coverage contexts:",
        f"  runs with a baseline:  {health.context_runs} of {health.scoped_runs}",
        f"  runs without one:      {without} (static closure alone)",
        f"  runs on a stale one:   {health.context_stale_runs}",
        f"  test files contributed: {health.context_selected_total} (cumulative)",
    ]
    if without and not health.context_runs:
        lines.append("  Run `just refresh-contexts-baseline` to cache one.")
    return lines


def _render_false_negatives(health: SelectionHealth) -> list[str]:
    if not health.false_negatives:
        return [
            "false negatives: 0",
            "  No full-run failure has ever been excluded by a scoped run over an",
            "  ancestor of the same change.",
        ]
    # One missed test excluded by twenty ancestor selections is one problem,
    # not twenty; group so the headline number is the number of tests.
    grouped: dict[str, list[FalseNegative]] = {}
    for false_negative in health.false_negatives:
        grouped.setdefault(false_negative.nodeid, []).append(false_negative)

    lines = [
        f"false negatives: {len(grouped)}"
        f" ({len(health.false_negatives)} scoped run/failure matches)"
    ]
    for nodeid, matches in sorted(grouped.items()):
        rules = sorted({rule for match in matches for rule in match.rules})
        lines.append(f"  {nodeid}")
        lines.append(
            f"    failed in {matches[0].full_run_record} "
            f"(head {(matches[0].full_run_head or '?')[:12]})"
        )
        lines.append(
            f"    excluded by {len(matches)} scoped run(s), first "
            f"{matches[0].selection_record} "
            f"(head {(matches[0].selection_head or '?')[:12]})"
        )
        lines.append(f"    rules across those runs: {', '.join(rules) or 'none'}")
    lines.extend(
        [
            "",
            "  A non-zero count means the selection heuristic is unsound as tuned.",
            "  Raise SASE_TEST_SELECTION_DEPTH to 3 or add the missed tests to",
            "  tests/contract_manifest.txt, then re-measure.",
        ]
    )
    return lines


def health_payload(health: SelectionHealth) -> dict[str, Any]:
    """The same summary, for anything that would rather parse than read."""
    return {
        "schema": HEALTH_SCHEMA,
        "scoped_runs": health.scoped_runs,
        "escalated_runs": health.escalated_runs,
        "escalation_rate": health.escalation_rate,
        "full_runs": health.full_runs,
        "universe_count": health.universe_count,
        "median_selected": health.median_selected,
        "median_selected_ratio": health.median_selected_ratio,
        "p90_selected": health.p90_selected,
        "median_duration": health.median_duration,
        "worker_seconds_saved": health.worker_seconds_saved,
        "rule_histogram": health.rule_histogram,
        "outcome_histogram": health.outcome_histogram,
        "context_runs": health.context_runs,
        "context_stale_runs": health.context_stale_runs,
        "context_selected_total": health.context_selected_total,
        "false_negatives": [
            {
                "nodeid": false_negative.nodeid,
                "test_file": false_negative.test_file,
                "selection_record": false_negative.selection_record,
                "selection_head": false_negative.selection_head,
                "full_run_record": false_negative.full_run_record,
                "full_run_head": false_negative.full_run_head,
                "rules": list(false_negative.rules),
            }
            for false_negative in health.false_negatives
        ],
    }
