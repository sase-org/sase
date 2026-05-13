# Reducing `sdd/beads/issues.jsonl` Merge Conflicts

Date: 2026-05-13 (updated 2026-05-12 with second-pass corrections, upstream beads comparison, Jujutsu/git-bug prior art,
single-workspace write-race analysis, and corrections to the proposed Git driver config)

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
- There is no `.gitattributes` merge driver configured for `sdd/beads/issues.jsonl`. In fact, the repo has no
  `.gitattributes` file at all, so the JSONL file is treated as ordinary auto-detected text and is subject to default
  line-ending normalization, default `eol` handling, and the default text merge driver.
- Bead IDs are sequential and dotted: `sase-<root>` for top-level beads, `sase-<root>.<phase>` for children, etc. They
  carry semantic meaning that downstream code, tales, plans, and humans rely on. They are not interchangeable hashes.
- `sase-3c.2` ([37b00a5d1](#)) introduced local-store ID allocation: `next_counter` advances from the current
  checkout's `config.json` rather than a cross-workspace authority. This makes ID-collision risk a function of how often
  two checkouts allocate from the same `next_counter` value before merging — the merge driver discussion below has to
  account for that explicitly.

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

## Single-Workspace Write Race

Before any merge-driver design, it is worth flagging that `mutation.rs` has no advisory file lock. Each mutation reads
the full store, mutates, writes `issues.jsonl.tmp`, and renames over `issues.jsonl`. Two concurrent processes in the
same workspace (for example, a long-running TUI plus a `sase bead` CLI invocation, or two agents launched into the same
checkout) will race: the later rename wins and silently discards the earlier write. This is a separate failure mode
from Git merge conflicts and produces no conflict markers, so it does not surface as user-visible noise — it just loses
mutations.

Implications for the merge-driver work:

- Any commit hook that runs `sase bead` mutations and `git add sdd/beads/issues.jsonl` must serialize per workspace.
- A `flock(2)` (or `fs2`/`fd-lock` in Rust) advisory lock on a sibling lock file is cheap and should be added
  alongside or before the merge driver. The Rust core can take it inside `mutation.rs`; Python callers go through the
  binding and inherit the lock.
- Without it, fixing the Git side only reduces *post-merge* noise; intra-workspace silent overwrites remain.

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
107K+ processed PRs (a 27.67% conflict rate) drawn from 142K+ agentic PRs across 59K+ repositories, and extracts 336K+
fine-grained conflict regions. Source: [AgenticFlict arXiv](https://arxiv.org/abs/2604.03551).

### Upstream `beads` (Steve Yegge's `bd`)

SASE's bead system is derived from `steveyegge/beads`. The acknowledgement at `docs/acknowledgements.md:38-67` already
notes that SASE forks the JSONL-with-SQLite-cache shape. The upstream answer to JSONL conflicts is materially different
from SASE's situation and worth describing precisely:

- Upstream ships a background daemon that treats the SQLite database as the working source of truth and re-exports the
  JSONL with a ~5s debounce, so most concurrent writes never collide on JSONL itself.
- Upstream switched to hash-based IDs (`bd-a1b2`) in v0.20.1+ specifically to eliminate cross-branch ID collisions, so
  "same ID, different content" can be interpreted as an update rather than a conflict.
- Upstream's documented conflict guidance is to "keep both lines" — i.e., effectively `merge=union`.

Crucially, the "keep both" strategy is only safe upstream *because* IDs are hashes and importers treat duplicate IDs as
idempotent updates. SASE intentionally keeps human-meaningful sequential IDs (`sase-3a.2.5`) so Option 2 (`merge=union`)
inherits the unsafety described below without inheriting the safety net. Switching SASE to hash IDs is not viable
without breaking the hierarchical naming convention that tales, plans, prompts, hooks, and humans depend on.
Source: [steveyegge/beads FAQ](https://github.com/steveyegge/beads/blob/main/docs/FAQ.md).

### `git-bug`

`git-bug` stores each bug in dedicated Git refs (under `refs/bugs/`) as an append-only sequence of operations
(create/edit-title/comment/label/etc.). Concurrent edits become independent ref tips that merge by replaying the
operation log in commit order. This is essentially a CRDT-ish design carried by Git's own object model. It avoids the
"single file rewritten on every mutation" pattern entirely and is the closest production-grade prior art to
[[option-5-event-sourced]] below. SASE cannot adopt it wholesale because it stores state in Git refs rather than
working-tree files (which breaks normal review/diff workflows), but its operation-log mental model translates directly
to an event-sourced design.

### Jujutsu (`jj`)

Jujutsu records merge conflicts as data inside commits — as an ordered list of tree objects rather than a single tree
— so rebases over conflicts succeed instead of aborting, and `MergedTree::resolve()` is invoked lazily. If a SASE user
adopts `jj`-on-Git, today's "every rebase replays the same JSONL conflict" pain disappears at the VCS layer without any
SASE-side work. Source: [Jujutsu conflicts](https://jj-vcs.github.io/jj/latest/technical/conflicts/).

This does not solve the problem for git-only users, but it is the right reference point for any custom semantic merge:
the goal is to make Git behave more like `jj` for this one path, not to invent a new conflict model from scratch.

### JSON Patch / JSON Merge Patch standards

Field-level merge rules do not need to be invented — they can be specified in standard terms. RFC 6902 (JSON Patch)
defines an operation log: `add`, `remove`, `replace`, `move`, `copy`, `test`. RFC 7396 (JSON Merge Patch) defines a
recursive-object replace semantics with `null` as deletion. Both are useful framings:

- The internal three-way merge can be modelled as `patch(base → ours)` and `patch(base → theirs)` composed against
  `base`, with the merge policy living in how the two patches are combined per-field.
- Storing operation logs (Option 5 below) as JSON Patch entries gives free interoperability with external tooling.

Sources: [RFC 6902](https://www.rfc-editor.org/rfc/rfc6902), [RFC 7396](https://www.rfc-editor.org/rfc/rfc7396).

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

- Unsafe for duplicate IDs. Upstream `beads` works around this by using hash IDs and treating "same ID" as idempotent
  update; SASE's sequential IDs do not give us that safety net.
- Unsafe for same-bead concurrent updates.
- Can keep stale and fresh versions of the same issue.
- Does not enforce sorted output, schema validity, or dependency uniqueness.
- Combines especially poorly with the sorted export in `jsonl.rs`: the file is no longer sorted by ID after union,
  which then produces noisier diffs and *more* future conflicts.

Verdict: do not use for authoritative bead state. This is the strategy upstream documents, but it is unsafe under
SASE's ID scheme and sort policy.

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

### Option 7: SQLite Source of Truth, JSONL as Generated Export

This is upstream beads' actual answer. Promote `sdd/beads/beads.db` (or a fresh SQLite file) to the authoritative
working store, write JSONL via a debounced exporter, and decide whether the JSONL even needs to be tracked.

Pros:

- Eliminates the "rewrite the entire file on every mutation" pattern that causes most textual conflicts.
- Concurrent writers in one workspace coordinate through SQLite's WAL, removing the silent-overwrite race documented
  above.
- Aligns with the upstream design SASE forked from, so future cherry-picks become cheaper.

Cons:

- Either JSONL stops being version-controlled (loses git portability and reviewability of bead changes — a stated SASE
  goal) or JSONL stays tracked and we are back to merging it.
- Multi-workspace visibility is now solved by re-importing JSONL on workspace switch, which `e6375ee1a` (scope bead
  CLI reads to current store) and the broader `remove_cross_workspace_bead_reads` plan have already moved away from.
- A binary SQLite file does not diff usefully in code review.

Verdict: do not adopt as-is. Reconsider only if the merge-driver path proves insufficient *and* the team accepts
losing git-tracked bead state.

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
   - commit `.gitattributes` with:

     ```gitattributes
     sdd/beads/issues.jsonl merge=sase-beads-jsonl -text
     sdd/beads/config.json   merge=sase-beads-config -text
     ```

     `-text` is deliberate: the file is machine-generated by the Rust exporter with deterministic LF line endings, and
     we do not want Git's `core.autocrlf` or `eol` settings to renormalize bytes that the merge driver is about to
     read three-way.

   - add `sase doctor --fix` or workspace setup logic that installs the driver into local Git config (driver commands
     cannot live in `.gitattributes`; Git intentionally requires per-repo install for security):

     ```bash
     git config merge.sase-beads-jsonl.name "SASE bead JSONL semantic merge"
     git config merge.sase-beads-jsonl.driver "sase bead git-merge-driver %O %A %B %P"
     # Use the SAME driver for the recursive (criss-cross) base merge so virtual
     # ancestors get bead-aware merging too. Do NOT set this to `binary` — that
     # makes Git treat the file as unmergeable during recursive merge and falls
     # back to conflict markers, defeating the driver. Omit `recursive` entirely
     # to inherit `driver`, or set it explicitly to the same command.
     git config merge.sase-beads-jsonl.recursive true
     ```

     `%P` passes the pathname so the driver can emit better diagnostics. The driver should exit non-zero with a
     human-readable summary on unresolved conflicts so Git leaves the file in the index with stage entries intact.

4. Add a manual fallback:
   - `sase bead resolve-conflict sdd/beads/issues.jsonl` should inspect index stages, run the same semantic merge, and
     print unresolved bead IDs/fields if it cannot finish.

5. Add validation:
   - `sase bead doctor` should flag duplicate IDs in JSONL.
   - CI or `just check` should include a fixture that simulates Git driver inputs for common conflict shapes.

6. Add an advisory write lock in `mutation.rs`:
   - acquire `flock(2)` on a sibling lock file (e.g., `sdd/beads/.issues.jsonl.lock`) for the full read-mutate-rename
     transaction, using a Rust crate such as `fs2` or `fd-lock`;
   - hold the lock across `git add sdd/beads/issues.jsonl` in any caller that combines mutation with staging, so the
     index never observes a half-written file;
   - this is independent of the merge driver but should land in the same epic — without it the merge driver only
     reduces *post-merge* noise, while same-workspace silent overwrites continue.

7. Add cheap textual-conflict reducers in the writer:
   - omit `updated_at` rewrites when no field actually changed (today every preclaim/launch hook touches `updated_at`,
     producing one-line conflicts even when both sides are doing the same logical operation);
   - emit a stable, alphabetized key order in `IssueWire` serialization so unrelated field reorderings cannot cause
     textual conflicts;
   - keep the sort-by-ID export, but consider sharding the JSONL into multiple sorted blocks (e.g., one block per root
     bead family) so concurrent activity in `sase-3a` does not contend on byte ranges adjacent to `sase-3b`. Cheap
     because it requires no schema change.

8. Add targeted conflict fixtures:
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

## Empirical Validation Plan

The current note argues from history (632 commits touching the file, 621 since 2026-05-01) and from code shape. Before
landing the merge driver, instrument:

- emit a structured log line from `mutation.rs` for each rewrite, tagged with the workspace path, bead IDs touched,
  and whether the rewrite was a no-op-after-normalization;
- count Git merge driver invocations and outcomes (`resolved`, `conflict`, `aborted`) in a local counter under
  `~/.sase/metrics/bead_merge.jsonl`;
- after one week of normal multi-agent activity, compare the conflict rate against the AgenticFlict baseline
  (27.67% across all paths) to size the problem and gate later work.

This also gives the team a regression detector: a sudden conflict-rate spike after a refactor is a leading indicator
that some hook started touching the file when it should not.

## Open Decisions

- Should same-field conflicts use latest `updated_at`, a status-specific lattice, or fail closed by default? The
  recommended starting policy is a lattice for `status` and `closed_at`, latest-write-wins (timestamped) for free-text
  fields where both sides edited, and fail-closed when timestamps tie or are missing.
- Should `notes` be append-merged, structured into a list, or treated as manual on both-sided changes? Notes carry
  commit metadata in current usage, so the safe default is fail-closed; investigate moving structured commit-metadata
  out of notes before changing the policy.
- Should `sase bead work` keep committing `in_progress` preclaims, or should launch claims move to transient state
  after the merge driver lands? Preclaims account for a large share of the one-line conflicts; transient state is
  preferable, but is gated on [[option-6-move-volatile-claim-state]].
- ~~Should top-level bead IDs remain sequential base36 IDs if agents create new top-level beads from isolated
  checkouts?~~ Resolved by `sase-3c.2` (commit `37b00a5d1`) and `sase-3c.1` (commit `e6375ee1a`): IDs are allocated
  from the local store. This means duplicate-ID collisions are now possible whenever two checkouts allocate from the
  same `next_counter` without an intervening pull. The merge driver MUST detect this case and fail closed; renaming
  IDs in-merge is not safe because external references (tales, plans, prompts, ChangeSpecs) embed the IDs.

## Bottom Line

The conflict source is not JSONL itself; it is using a single line-oriented file for entity state that has field-level
merge semantics. A SASE-owned semantic Git merge driver is the pragmatic fix. It should be implemented before a storage
rewrite, and its resolver core should become the reusable merge policy for any later per-bead-file or event-log design.
