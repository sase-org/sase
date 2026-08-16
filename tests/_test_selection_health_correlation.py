"""Correlate scoped selections with full-run failures.

A false negative is a test that failed in a full run and was excluded by a
scoped run over an ancestor of the same change. A scoped run is charged with a
failure only when all of these hold:

* both records name the same workspace;
* the scoped HEAD is an ancestor of the full-run HEAD;
* the full run's change set is equal to or a superset of the scoped change set;
* the scoped run did not escalate or select the failing test's file.

Pre-schema-2 records lack the identity needed to satisfy those rules, so they
are counted but never correlated. Reproducible flakes are reported separately
as suppressed matches rather than selection misses.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tests._test_selection_graph import SelectionError, is_visual_path, run_git
from tests._test_selection_health_records import FullRunRecord, HealthRecords


AncestorOracle = Callable[[str, str], bool]
CommitOrderOracle = Callable[[str], int | None]
CollectibleNodeIdOracle = Callable[[str], bool]


#: Test files whose failure can be a deterministic, correct consequence of an
#: uncommitted edit rather than intermittency: each scans the listed source
#: root(s) with an AST/text walk and compares the result against a checked-in
#: reviewed inventory (see ``tests/_agent_artifact_marker_audit_helpers.py``
#: and its siblings) or against a fixed invariant the scan must never violate.
#: Editing a file under a listed root without updating the inventory, or in a
#: way the invariant forbids, breaks the audit in that workspace by design —
#: see sase-lc. Deliberately hand-maintained rather than sniffed from each
#: file's own `rglob` call: a wrong guess here would silently discard real
#: flake evidence, so a new source-tree audit must be added deliberately.
_SOURCE_AUDIT_SCAN_ROOTS: dict[str, tuple[str, ...]] = {
    "tests/test_agent_artifact_marker_path_passing_audit.py": ("src/sase/",),
    "tests/test_agent_artifact_marker_mutation_audit.py": ("src/sase/",),
    "tests/test_commit_type_tag_contract.py": ("src/sase/",),
    "tests/test_timezone_display_guard.py": ("src/sase/",),
    "tests/test_agent_tribe_terminology.py": ("src/", "docs/"),
    "tests/test_markdown_print_width.py": ("src/sase/",),
    "tests/test_sdd_canonical_layout.py": ("src/sase/sdd/", "docs/", "tests/"),
    "tests/test_proc_submission_static_invariants.py": ("src/sase/",),
    "tests/workspace_provider/test_primary_writable_store_import_boundary.py": (
        "src/sase/",
    ),
}


def _is_attributable_dirty_failure(nodeid: str, full_run: FullRunRecord) -> bool:
    """Whether ``full_run``'s own dirty tree, not intermittency, explains ``nodeid``.

    Requires positive proof, never an inference from absence: an explicitly
    recorded ``tree_dirty is True`` (a missing or unresolved flag stays
    evidence, per the module-level warning on
    :attr:`FullRunRecord.tree_dirty`) and a changed path that falls inside the
    exact root a registered source-tree audit scans. Both a recorded clean
    tree and an unrelated changed-file set leave the failure in the ordinary
    evidence bar untouched.
    """
    if full_run.tree_dirty is not True:
        return False
    roots = _SOURCE_AUDIT_SCAN_ROOTS.get(nodeid_test_file(nodeid))
    if not roots:
        return False
    changed = full_run.changed_files
    if not changed:
        return False
    return any(path.startswith(root) for path in changed for root in roots)


def attributable_dirty_failures(
    full_runs: Sequence[FullRunRecord],
    *,
    max_failures_per_run: int | None = None,
) -> tuple[tuple[str, str], ...]:
    """``(nodeid, record name)`` pairs :func:`_flake_evidence_nodeids` excluded.

    Kept separate from the evidence computation so the gate can report exactly
    how many failures it discounted and why, instead of asking a reader to
    trust a shrinking count with no explanation attached.
    """
    eligible = _ordered_flake_candidate_runs(
        full_runs, max_failures_per_run=max_failures_per_run, commit_order=None
    )
    return tuple(
        (nodeid, full_run.name)
        for full_run in eligible
        for nodeid in full_run.failures
        if _is_attributable_dirty_failure(nodeid, full_run)
    )


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


def git_commit_order_oracle(root: Path) -> CommitOrderOracle:
    """A commit timestamp lookup, memoised per commit.

    Full runs from parallel workspaces can finish out of commit order: an old
    broken workspace may write its record after another workspace has already
    tested a fixed descendant. Sorting by commit time keeps that fixed run from
    looking like an interleaved pass for the older broken tree.
    """
    cache: dict[str, int | None] = {}

    def _commit_order(commit: str) -> int | None:
        if commit not in cache:
            try:
                value = run_git(root, "show", "-s", "--format=%ct", commit)
            except SelectionError:
                cache[commit] = None
            else:
                try:
                    cache[commit] = int(value.strip())
                except ValueError:
                    cache[commit] = None
        return cache[commit]

    return _commit_order


def nodeid_test_file(nodeid: str) -> str:
    """The file part of a pytest node ID.

    Named subject-first rather than ``test_file_for_nodeid`` so importing it
    into a test module does not make pytest try to collect it.
    """
    return nodeid.split("::", 1)[0].replace("\\", "/")


def collectible_nodeid_oracle(root: Path) -> CollectibleNodeIdOracle:
    """A ``nodeid -> still exists to run`` predicate, memoised per test file.

    A renamed or deleted test's old node ID can never pass again, so a
    baseline gate that judges it as a live flake is judging a test that no
    longer exists. This approximates "still collectable" by parsing the
    node's test file and checking whether a function or method with its name
    is still defined anywhere in it — deliberately not tied to the class it
    was originally nested under, or to a real pytest collection pass: a node
    whose class was renamed but whose function name survives elsewhere in the
    file reads as collectable rather than stale. Understating staleness only
    leaves an old node gated exactly as it is today; overstating it would
    hide a live reproducible flake from the gate, which is the worse failure
    mode.
    """
    cache: dict[str, frozenset[str] | None] = {}

    def _defined_test_names(test_file: str) -> frozenset[str] | None:
        if test_file not in cache:
            try:
                source = (root / test_file).read_text(encoding="utf-8")
                tree = ast.parse(source, filename=test_file)
            except (OSError, SyntaxError):
                cache[test_file] = None
            else:
                cache[test_file] = frozenset(
                    node.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                )
        return cache[test_file]

    def _is_collectible(nodeid: str) -> bool:
        names = _defined_test_names(nodeid_test_file(nodeid))
        if names is None:
            return False
        symbol = nodeid.rsplit("::", 1)[-1].split("[", 1)[0]
        return symbol in names

    return _is_collectible


@dataclass(frozen=True)
class FalseNegative:
    nodeid: str
    test_file: str
    selection_record: str
    selection_head: str | None
    selection_changed_files: tuple[str, ...]
    full_run_record: str
    full_run_head: str | None
    workspace: str
    rules: tuple[str, ...]


@dataclass(frozen=True)
class PreSchemaRecords:
    """Records with no correlation identity, and so not correlated at all."""

    selections: int = 0
    full_runs: int = 0

    @property
    def total(self) -> int:
        return self.selections + self.full_runs


def count_pre_schema_records(records: HealthRecords) -> PreSchemaRecords:
    """How much of the store predates the identity correlation requires.

    The store holds up to ``RETENTION_DAYS`` of records written before schema
    2, and those can only be dropped from the metric, never rescued: the
    workspace and change set they would need were never written down. A
    reader seeing "0 false negatives" is entitled to know how many records
    that zero was computed over.
    """
    return PreSchemaRecords(
        selections=sum(
            1 for selection in records.selections if selection.identity is None
        ),
        full_runs=sum(1 for full_run in records.full_runs if full_run.identity is None),
    )


def _flake_evidence_nodeids(
    full_runs: Sequence[FullRunRecord],
    *,
    max_failures_per_run: int | None,
    commit_order: CommitOrderOracle | None,
) -> frozenset[str]:
    """Node IDs with unrelated failures and an interleaved independent pass.

    A genuine miss recurs only across the ancestors of the one diff that broke
    it, so every full run charging it shares that diff's files. A deterministic
    break on master has the opposite shape: unrelated workspaces all keep
    failing the same node until the fix lands, after which they pass. A
    reproducible flake needs stronger evidence than unrelated failing change
    sets: the same node must also pass in an eligible full run between those
    failures, and that passing run must not be changing the node's own test
    file.

    A hand-maintained node-ID list was considered and rejected for this rule:
    the real store already shows failures reproducing across unrelated diffs
    on nodes no bead had enumerated yet (an out-of-date ``sase_core_rs``
    binding failing ``test_malformed_header_block_leaves_authored_metadata_visible``
    identically in five unrelated workspaces), so a fixed list would already be
    behind. This check needs no maintenance and generalizes to whatever the
    next flake turns out to be.

    Requires at least two full runs with a recorded change set (schema 2+) for
    the same node; a node seen failing only once, or only in runs with no
    identity, is never called reproducible here.

    ``max_failures_per_run`` lets the regression gate ask the narrower question
    this metric was built for: one-node or low-cardinality failures. A broken
    suite run with hundreds of failures should not promote every node it names
    into flake debt.

    ``commit_order`` keeps parallel workspace records in commit order when the
    caller can resolve the commits. Without it, the sequence order is used.

    A failure :func:`_is_attributable_dirty_failure` can explain — a
    registered source-tree audit, failing in a run recorded with an
    uncommitted change under the exact root it scans — never enters
    ``failures_by_node`` at all: it is the editing workspace's own tree,
    correctly caught, not cross-workspace evidence of anything. See
    :func:`attributable_dirty_failures` for the matching exclusion count a
    report can show.

    This is the shared evidence bar behind :func:`reproducible_flake_nodeids`
    and :func:`stale_flake_nodeids`, which differ only in which side of
    "still collectable" they keep — neither reasons about that here.
    """
    eligible_runs = _ordered_flake_candidate_runs(
        full_runs,
        max_failures_per_run=max_failures_per_run,
        commit_order=commit_order,
    )
    failures_by_node: dict[str, list[tuple[int, frozenset[str]]]] = {}
    for index, full_run in enumerate(eligible_runs):
        changed_files = full_run.changed_files
        assert changed_files is not None
        for nodeid in full_run.failures:
            if _is_attributable_dirty_failure(nodeid, full_run):
                continue
            failures_by_node.setdefault(nodeid, []).append((index, changed_files))

    flakes: set[str] = set()
    for nodeid, failures in failures_by_node.items():
        unique = {changed for _index, changed in failures}
        if len(unique) < 2:
            continue
        if frozenset.intersection(*unique):
            continue
        if _has_interleaved_independent_pass(eligible_runs, nodeid, failures):
            flakes.add(nodeid)
    return frozenset(flakes)


def reproducible_flake_nodeids(
    full_runs: Sequence[FullRunRecord],
    *,
    max_failures_per_run: int | None = None,
    commit_order: CommitOrderOracle | None = None,
    collectible: CollectibleNodeIdOracle | None = None,
) -> frozenset[str]:
    """The :func:`_flake_evidence_nodeids` bar, minus stale node IDs.

    A renamed or deleted test's old node ID can never appear in a passing run
    again, so without a staleness check it would meet this evidence bar
    forever and manufacture permanent pressure to bump the baseline cutoff.
    ``collectible`` answers whether a node ID still names a test in the
    working tree; a node that fails it is reported by
    :func:`stale_flake_nodeids` instead. Omitting ``collectible`` trusts
    every node ID as live, matching every caller from before this parameter
    existed.
    """
    evidence = _flake_evidence_nodeids(
        full_runs, max_failures_per_run=max_failures_per_run, commit_order=commit_order
    )
    if collectible is None:
        return evidence
    return frozenset(nodeid for nodeid in evidence if collectible(nodeid))


def stale_flake_nodeids(
    full_runs: Sequence[FullRunRecord],
    *,
    collectible: CollectibleNodeIdOracle,
    max_failures_per_run: int | None = None,
    commit_order: CommitOrderOracle | None = None,
) -> frozenset[str]:
    """The other half of :func:`reproducible_flake_nodeids`'s staleness split.

    Same evidence bar, only the node ID no longer names a collectable test —
    a renamed or deleted test, reported so it reads as removable baseline
    debt instead of disappearing silently.
    """
    evidence = _flake_evidence_nodeids(
        full_runs, max_failures_per_run=max_failures_per_run, commit_order=commit_order
    )
    return frozenset(nodeid for nodeid in evidence if not collectible(nodeid))


def _is_flake_gate_eligible(
    full_run: FullRunRecord, *, max_failures_per_run: int | None
) -> bool:
    if (
        max_failures_per_run is not None
        and len(full_run.failures) > max_failures_per_run
    ):
        return False
    return full_run.changed_files is not None


def _ordered_flake_candidate_runs(
    full_runs: Sequence[FullRunRecord],
    *,
    max_failures_per_run: int | None,
    commit_order: CommitOrderOracle | None,
) -> tuple[FullRunRecord, ...]:
    eligible: list[tuple[int, int, int, FullRunRecord]] = []
    for index, full_run in enumerate(full_runs):
        if not _is_flake_gate_eligible(
            full_run, max_failures_per_run=max_failures_per_run
        ):
            continue
        missing_order = 1
        sort_key = index
        if commit_order is not None and full_run.head:
            resolved = commit_order(full_run.head)
            if resolved is not None:
                missing_order = 0
                sort_key = resolved
        eligible.append((missing_order, sort_key, index, full_run))
    return tuple(
        full_run
        for _missing_order, _sort_key, _index, full_run in sorted(
            eligible, key=lambda item: item[:3]
        )
    )


def unresolved_commit_order_count(
    full_runs: Sequence[FullRunRecord],
    *,
    max_failures_per_run: int | None = None,
    commit_order: CommitOrderOracle | None = None,
) -> int:
    """How many flake-eligible runs :func:`_ordered_flake_candidate_runs` could
    not place by real commit time and instead sorted last by list order.

    ``git_commit_order_oracle`` cannot resolve a commit this workspace has
    never fetched — a sibling workspace's record can name one — and an
    unresolved head is the mechanism by which a cross-workspace record could
    get mis-ordered relative to the run it actually raced. Reported so that
    drift is visible rather than silently absorbed by the fallback.
    """
    if commit_order is None:
        return 0
    return sum(
        1
        for full_run in full_runs
        if _is_flake_gate_eligible(full_run, max_failures_per_run=max_failures_per_run)
        and (not full_run.head or commit_order(full_run.head) is None)
    )


def _has_interleaved_independent_pass(
    full_runs: Sequence[FullRunRecord],
    nodeid: str,
    failures: Sequence[tuple[int, frozenset[str]]],
) -> bool:
    first = failures[0][0]
    last = failures[-1][0]
    if last - first < 2:
        return False
    test_file = nodeid_test_file(nodeid)
    for full_run in full_runs[first + 1 : last]:
        if nodeid in full_run.failures:
            continue
        if full_run.changed_files is not None and test_file in full_run.changed_files:
            continue
        return True
    return False


def _correlate_full_run_failures(
    records: HealthRecords, *, is_ancestor: AncestorOracle
) -> list[FalseNegative]:
    """Every full-run failure an ancestor scoped selection excluded, unfiltered.

    A pair must plausibly describe *the same change* (see the module
    docstring): same workspace, scoped HEAD an ancestor of the full run's, and
    the full run's change set a superset of or equal to the scoped run's.
    Without all three, one workspace's flake is charged to another workspace's
    selection, which is what this correlator existed to avoid measuring.

    Escalated manifests are skipped because they ran everything: they excluded
    nothing and cannot have missed anything. Visual paths are skipped because
    the selector excludes them unconditionally and by design; ``just
    test-visual`` is their lane. Records with no identity — anything written
    before schema 2 — are skipped and counted by
    :func:`count_pre_schema_records`.

    Shared by :func:`find_false_negatives` and :func:`find_flake_suppressed`,
    which split this list on :func:`reproducible_flake_nodeids` rather than
    each re-walking the store.
    """
    candidates = [
        (selection, identity)
        for selection in records.selections
        if not selection.escalated
        and selection.head
        and (identity := selection.identity) is not None
    ]
    matches: list[FalseNegative] = []
    for full_run in records.full_runs:
        full_run_identity = full_run.identity
        if not full_run.head or not full_run.failures or full_run_identity is None:
            continue
        full_workspace, full_changed = full_run_identity
        related = [
            (selection, changed)
            for selection, (workspace, changed) in candidates
            if workspace == full_workspace and changed <= full_changed
        ]
        for nodeid in full_run.failures:
            test_file = nodeid_test_file(nodeid)
            if is_visual_path(test_file):
                continue
            for selection, changed in related:
                if test_file in selection.selected:
                    continue
                head = selection.head
                assert head is not None
                if not is_ancestor(head, full_run.head):
                    continue
                matches.append(
                    FalseNegative(
                        nodeid=nodeid,
                        test_file=test_file,
                        selection_record=selection.name,
                        selection_head=head,
                        selection_changed_files=tuple(sorted(changed)),
                        full_run_record=full_run.name,
                        full_run_head=full_run.head,
                        workspace=full_workspace,
                        rules=selection.rules,
                    )
                )
    return matches


def find_false_negatives(
    records: HealthRecords,
    *,
    is_ancestor: AncestorOracle,
    commit_order: CommitOrderOracle | None = None,
) -> list[FalseNegative]:
    """Match full-run failures against scoped runs that excluded them.

    See :func:`_correlate_full_run_failures` for the matching rule. A match
    whose node is a :func:`reproducible_flake_nodeids` member is excluded here
    and reported instead by :func:`find_flake_suppressed`: it is evidence the
    lane cannot act on, not a selection miss.
    """
    flaky = reproducible_flake_nodeids(records.full_runs, commit_order=commit_order)
    return [
        match
        for match in _correlate_full_run_failures(records, is_ancestor=is_ancestor)
        if match.nodeid not in flaky
    ]


def find_flake_suppressed(
    records: HealthRecords,
    *,
    is_ancestor: AncestorOracle,
    commit_order: CommitOrderOracle | None = None,
) -> list[FalseNegative]:
    """The other half of :func:`find_false_negatives`'s split: known flakes.

    Same matches, same matching rule — only routed here instead because their
    node is a :func:`reproducible_flake_nodeids` member. Excluded from the
    false-negative count, but never silently dropped: the health report counts
    and lists these too.
    """
    flaky = reproducible_flake_nodeids(records.full_runs, commit_order=commit_order)
    return [
        match
        for match in _correlate_full_run_failures(records, is_ancestor=is_ancestor)
        if match.nodeid in flaky
    ]
