# Reducing `sdd/beads/issues.jsonl` Merge Conflicts

Date: 2026-05-13

## Question

Agents running in parallel frequently conflict on `sdd/beads/issues.jsonl`. What storage or merge strategy should SASE
use so bead state remains git-portable without forcing every agent integration through manual JSONL conflict
resolution?

## Current SASE Shape

The bead store is currently a git-tracked JSONL materialized view:

- `sdd/beads/issues.jsonl` has 903 rows and is about 770 KiB in this workspace.
- `../sase-core/crates/sase_core/src/bead/mutation.rs` loads all issues, mutates an in-memory vector, then rewrites
  `issues.jsonl` by writing `issues.jsonl.tmp` and renaming it.
- `../sase-core/crates/sase_core/src/bead/jsonl.rs` exports rows sorted by `id`, one JSON object per issue.
- `sdd/beads/config.json` holds `next_counter`; `beads.db` is a compatibility/cache artifact, not tracked in this
  workspace.
- There is no `.gitattributes` merge driver configured for `sdd/beads/issues.jsonl`.

The local history confirms that this is a high-churn file. Across the visible history, 632 commits touched
`sdd/beads/issues.jsonl`; 621 of those are since 2026-05-01. Most are one-row state updates: 456 commits changed exactly
one line by the numstat view. The expensive cases are kickoff/preclaim commits and mass updates: 26 commits changed 20
or more total lines.

The current active bead set also creates a natural conflict hotspot. `sase-3a` has many in-progress phase beads, and
`sase bead work` style operations can mark many phase rows `in_progress` and set assignees in one commit. Those rows
are the same rows later closed by phase agents.

## Why Conflicts Happen

Git sees the file as line-oriented text, but bead semantics are entity-oriented:

- Independent issue updates are safe only when Git can merge different rows cleanly.
- Concurrent updates to the same bead are a one-line conflict even when the field changes are semantically mergeable,
  for example one side sets `assignee`, the other side sets `notes`.
- `updated_at` is touched by nearly every mutation, so two otherwise independent field updates to the same bead almost
  always conflict textually.
- Sorted export makes concurrent creation near the same ID range conflict more often than append-at-end logs would.
- A line-union merge is unsafe because duplicate bead IDs are invalid application state even if every line is valid
  JSON. The Rust import path currently parses rows into a vector; uniqueness is an application invariant rather than a
  guaranteed JSONL property.

The recent `remove_cross_workspace_bead_reads` plan intentionally makes the current checkout's `sdd/beads/issues.jsonl`
the single source of truth. That is a good consistency boundary, but it means Git merge behavior now has to carry the
parallel-agent integration load directly.

## Prior Art

Git supports path-specific merge behavior through attributes. The `merge` attribute selects built-in or custom merge
drivers, and Git's custom driver contract passes the ancestor, current, and other versions as `%O`, `%A`, and `%B`; the
driver writes the result back to `%A` and returns success or conflict. Source: [Git gitattributes merge
documentation](https://git-scm.com/docs/gitattributes).

Git's built-in `union` driver keeps lines from both sides rather than emitting conflict markers, but the docs explicitly
warn that the result can be randomly ordered and should be manually verified. That warning matters here: union can keep
two rows with the same bead ID, resurrect stale state, or preserve both sides of a deletion/update conflict.

Git `rerere` can reduce repeated manual work by recording a conflict resolution and replaying it when the same textual
conflict appears again. Source: [Git rerere documentation](https://git-scm.com/book/en/v2/Git-Tools-Rerere). It is a
useful operator setting, but it does not understand bead IDs or fields, and it only helps after a human has already
resolved an equivalent conflict once.

Gira, a Git-backed issue tracker, ships a custom JSON merge driver. Its documented rules are close to what SASE needs:
three-way comparison, field-level merging, latest-write-wins when the same field is changed, maximum counters for state
files, and manual conflicts for deletion-vs-modification cases. Source: [Gira custom merge driver
docs](https://gira.goatbytes.io/03-integrations/git-merge-driver/).

Generic syntax-aware merge tools such as Mergiraf can parse structured files and act as Git merge drivers, but they do
not encode SASE's bead-specific invariants: one row per ID, status transitions, dependency tuple uniqueness,
`next_counter` monotonicity, and explicit deletion semantics. Source: [Mergiraf overview](https://terminaltrove.com/mergiraf/).

This is not a niche problem for agentic workflows. The AgenticFlict paper reports 29K+ conflicted agent PRs out of
107K+ processed PRs, a 27.67% conflict rate, and 336K+ fine-grained conflict regions. Source: [AgenticFlict
arXiv](https://arxiv.org/abs/2604.03551).

## Options

### Option 1: Keep Status Quo, Add Better Manual Tooling

Add `sase bead resolve-conflict` that reads Git index stages for `sdd/beads/issues.jsonl`, presents changed bead IDs,
and writes a resolved JSONL file. Recommend `rerere.enabled=true` for frequent integrators.

Pros:

- Smallest implementation.
- Gives humans a safer workflow than editing conflict markers inside JSONL.
- Useful even if a future custom merge driver fails and leaves a manual conflict.

Cons:

- Does not reduce first-time conflicts.
- Still interrupts agent landing.
- Does not help automated merge/rebase paths unless wrapped by higher-level commit logic.

Verdict: useful fallback, not sufficient.

### Option 2: Configure Git `merge=union` for `issues.jsonl`

Add an attribute like:

```gitattributes
sdd/beads/issues.jsonl merge=union
```

Pros:

- Nearly free.
- Helps simple concurrent row additions.

Cons:

- Unsafe for duplicate IDs.
- Unsafe for same-bead concurrent updates.
- Can keep stale and fresh versions of the same issue.
- Does not enforce sorted output, schema validity, or dependency uniqueness.

Verdict: do not use for authoritative bead state.

### Option 3: Custom Semantic Merge Driver for Bead JSONL

Implement a SASE merge driver that parses base/ours/theirs JSONL by `id`, performs a three-way semantic merge, validates
the result, sorts rows by ID, and writes compact JSONL. Configure it through `.gitattributes` plus local Git config
installed by `sase init`, `sase doctor --fix`, or workspace preparation.

Candidate rules:

- Parse all three inputs using the Rust JSONL parser, but fail closed on duplicate IDs in any side.
- Build the union of bead IDs from base/ours/theirs.
- For a new ID present on only one side, keep it.
- For the same new ID created independently on both sides, fail with a clear duplicate-ID conflict unless the full row is
  identical.
- For a deleted ID versus unchanged ID, keep deletion.
- For a deleted ID versus modified ID, fail and ask for a human decision.
- For an existing ID modified by only one side, take the modified row.
- For an existing ID modified by both sides, merge fields independently when they changed from base on only one side.
- For fields changed by both sides:
  - use explicit business rules for status lifecycle fields;
  - prefer `closed` over `in_progress` when one side closed the bead and the other only claimed or touched it earlier;
  - choose the side with the later `updated_at` for true same-field conflicts when both timestamps parse;
  - fail if timestamps are missing/equal and values differ.
- Merge `dependencies` by `(issue_id, depends_on_id)` tuple; fail on same tuple with different metadata unless metadata
  differs only by blank creator/timestamp.
- Preserve `notes` carefully. If both sides changed notes differently, either append with a generated separator or fail;
  do not silently latest-write-wins notes because notes often carry commit metadata.
- Validate every resulting `IssueWire`.
- For `config.json`, merge `next_counter` by max and require matching `issue_prefix`; this can be a second driver or a
  companion resolver used by the same setup command.

Pros:

- Best near-term risk/reward.
- Preserves current storage, CLI, docs, and git portability.
- Solves the actual mismatch: Git needs bead-aware semantics, not just line-aware text merges.
- Can reuse Rust bead parser/wire validation and live next to existing mutation code.
- Can fail closed for ambiguous cases instead of corrupting the store.

Cons:

- Requires local Git config; `.gitattributes` alone cannot define the command.
- Needs careful tests for same-ID updates, deletes, duplicate IDs, malformed rows, and config counters.
- Latest-write-wins is only safe for some fields. Status and notes need explicit rules.

Verdict: recommended first implementation.

### Option 4: Split Storage to One File Per Bead

Replace `issues.jsonl` as the primary tracked state with `sdd/beads/issues/<id>.json` or
`sdd/beads/issues/<prefix>/<id>.json`, and treat JSONL as generated compatibility/export output.

Pros:

- Standard Git handles independent bead changes as independent files.
- Creation of different bead IDs no longer conflicts on one sorted file.
- Easier review: one file diff is one bead.
- Allows generated indices/cache files to be ignored.

Cons:

- Does not solve concurrent updates to the same bead.
- Does not solve duplicate top-level ID allocation by itself.
- Large migration across Rust core, Python facades, docs, tests, and any mobile/helper readers.
- Many small files are fine at SASE scale but still more filesystem churn than one JSONL file.

Verdict: good medium-term simplification, but it should still keep the semantic merge rules for same-bead conflicts.

### Option 5: Event-Sourced Per-Agent Operation Logs

Store immutable operations instead of a mutable materialized JSONL row set, for example:

```text
sdd/beads/events/202605/<agent-or-run-id>.jsonl
```

Each mutation appends a create/update/close/dep event to a per-agent or per-run file. The current issue view is derived
into SQLite and optionally exported to `issues.jsonl`.

Pros:

- Best fit for parallel agents: independent agents write independent files.
- Preserves audit history naturally.
- Makes "what happened" clearer than repeatedly overwriting full issue rows.
- Avoids most Git conflicts if event files are per-agent/per-run and immutable after close.

Cons:

- Larger design change than a merge driver.
- Requires deterministic replay rules for conflicting operations.
- Needs compaction/snapshot strategy to avoid unbounded read cost.
- Requires a migration and backwards-compatibility story.

Verdict: best long-term concurrency model if SASE expects heavy multi-agent bead mutation to continue, but too much for
the immediate pain.

### Option 6: Move Volatile Claim State Out of Git

Keep durable bead definitions and closure metadata in tracked state, but store transient fields such as
`status=in_progress`, `assignee`, launch claims, and maybe `updated_at` in local runtime state or a separate generated
file.

Pros:

- Removes the highest-churn fields from the version-controlled file.
- Avoids committing "agent has launched" noise.
- Makes tracked bead history more durable and less operational.

Cons:

- Changes user-visible semantics of `sase bead list --status=in_progress` across clones.
- Cross-workspace and multi-machine visibility of active work becomes a separate synchronization problem.
- Closure still mutates durable state, so conflicts are reduced but not eliminated.

Verdict: worth considering for product semantics, but not a standalone merge-conflict fix.

## Recommendation

Implement a custom semantic merge driver first, plus a manual resolver command as its fallback.

This is the smallest change that directly addresses the current storage model. It keeps `issues.jsonl` as the
git-portable source of truth while giving Git the missing bead-level semantics. It also aligns with the recent
single-store direction: each checkout owns its current `sdd/beads/issues.jsonl`, and normal Git integration becomes
responsible for combining branches.

Do not use `merge=union` for this file. It is attractive because JSONL is line-oriented, but bead IDs are unique
entities. Preserving both lines is data corruption, not a successful merge.

After the merge driver is stable, decide whether to keep JSONL long term or migrate to one-file-per-bead or event logs.
The merge driver code should be written so its core three-way merge function is storage-format independent: `base
issues + ours issues + theirs issues -> merged issues or typed conflicts`. That lets the same semantic resolver survive
a future storage split.

## Proposed Implementation Plan

1. Add Rust core merge primitives:
   - parse three JSONL inputs with duplicate-ID detection;
   - compute entity-level changed fields against base;
   - produce `MergedIssues` or `BeadMergeConflict` diagnostics;
   - reuse `IssueWire::validate()`.

2. Add a CLI entry point:
   - `sase bead merge-jsonl <base> <ours> <theirs>` writes merged JSONL to stdout, or
   - `sase bead git-merge-driver %O %A %B` writes the result into `%A`, matching Git driver expectations.

3. Configure Git:
   - commit `.gitattributes` with `sdd/beads/issues.jsonl merge=sase-beads-jsonl`;
   - add `sase doctor --fix` or workspace setup logic that runs:

```bash
git config merge.sase-beads-jsonl.name "SASE bead JSONL semantic merge"
git config merge.sase-beads-jsonl.driver "sase bead git-merge-driver %O %A %B"
git config merge.sase-beads-jsonl.recursive binary
```

4. Add a manual fallback:
   - `sase bead resolve-conflict sdd/beads/issues.jsonl` should inspect index stages, run the same semantic merge, and
     print unresolved bead IDs/fields if it cannot finish.

5. Add validation:
   - `sase bead doctor` should flag duplicate IDs in JSONL.
   - CI or `just check` should include a fixture that simulates Git driver inputs for common conflict shapes.

6. Add targeted conflict fixtures:
   - different rows changed;
   - same row, disjoint fields changed;
   - same row, status claim vs close;
   - same row, both append/change notes;
   - dependency additions from both sides;
   - independent new IDs;
   - duplicate new ID with different content;
   - delete vs update;
   - malformed line;
   - `config.json` counter max merge.

## Open Decisions

- Should same-field conflicts use latest `updated_at`, a status-specific lattice, or fail closed by default?
- Should `notes` be append-merged, structured into a list, or treated as manual on both-sided changes?
- Should `sase bead work` keep committing `in_progress` preclaims, or should launch claims move to transient state after
  the merge driver lands?
- Should top-level bead IDs remain sequential base36 IDs if agents create new top-level beads from isolated checkouts?
  A merge driver can detect duplicate IDs, but avoiding duplicates requires either a coordinated allocator or a less
  collision-prone ID scheme.

## Bottom Line

The conflict source is not JSONL itself; it is using a single line-oriented file for entity state that has field-level
merge semantics. A SASE-owned semantic Git merge driver is the pragmatic fix. It should be implemented before a storage
rewrite, and its resolver core should become the reusable merge policy for any later per-bead-file or event-log design.
