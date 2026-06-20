# SASE agent QoL patterns from recent chats - 2026-06-20

## Scope

This note consolidates two independent research passes over recent SASE chat
transcripts. The goal is to identify recurring, actionable friction that makes
SASE agents slower, more expensive, or less likely to terminate with the right
answer.

Inputs reviewed: the two prior research-agent transcripts
(`sase-ace_run-260620_173114` and `sase-ace_run-260620_173125`), their two
research notes, representative cited chats from 2026-06-20, and the local code
paths for commit dispatch, commit-message handling, bead creation, finalizer
dirty-state discovery, and provider retry behavior.

The two research passes broadly agree. The second pass had stronger code
grounding for `sase commit`, workspace setup, and bead metadata. The first pass
more clearly captured linked-repo finalizer misses and the need to distinguish
provider/auth failures from task failures. One important correction: current
Claude retry defaults do include a broad `"API Error"` retry pattern, so the
provider finding is not "no retry exists"; the problem is that auth failures
are classified too late and too broadly, after expensive work has already been
launched, and they receive the same continuation prompt as resumable task work.

## Evidence sample

The chat list is inflated by duplicate wrapper rows (`ace-run`,
`tmp_*-main`, workflow child rows, and error rows), so the useful unit is a
deduplicated conversation. The sampled set covers bead workers, plan/implement
runs, epic closeouts, finalizer Q&A, and provider-error rows.

Representative transcripts:

| Transcript | Signal |
| --- | --- |
| `sase-ace_run-260620_140203` | Empty bead context; repeated `sase commit` sync races; consumed message files; stale Rust/global `sase` pitfalls. |
| `sase-ace_run-260620_140209` | Child bead required parent-epic lookup; validation and formatting surfaced late. |
| `sase-tmp_260620_151033-workflow_tmp_260620_151033_main_ERROR-260620_151051` | Commit finalizer failed after two passes with dirty main, `sase-core`, and `sase-nvim` workspaces. |
| `sase-tmp_260620_165748-main-260620_170842` | Closeout found real remaining work in linked-repo advisory fallback; direct `pytest` resolved to a stale workspace path. |
| `sase-tmp_260620_170317-main-260620_170701` | Closeout found a real `%{...}` directive acceptance gap after child beads were closed. |
| `sase-tmp_260620_172151-main-260620_172745` | Closeout had to verify from diffs because child notes were mostly commit pointers, some unreachable. |
| `sase-tmp_260620_171132-workflow_tmp_260620_171132_main_ERROR-260620_171135` | 401 auth failure wrapped in the generic continuation prompt promising preserved edits. |

## Pattern 1: commit bookkeeping dominates task closeout

The most common high-cost detour is `sase commit` losing a race against
`origin/master` while bead-state files are staged. Parallel agents closing
sibling beads all touch `sdd/beads/issues.jsonl` and
`sdd/beads/events/**`, so the command often returns a manual conflict and the
agent performs the same recovery loop by hand: stash, fast-forward, pop,
inspect incoming commits, restage bead state, recreate the message file, rerun
checks, and retry.

Evidence: `sase-ace_run-260620_140203` ran the recovery loop multiple times;
`sase-ace_run-260620_145510`, `...145512`, `...153543`, and the `sase-52.*`
implementation chats show the same shape, including duplicate close-event
cleanup and note re-derivation. The `tmp_260620_151033` finalizer failure ended
with dirty files in three repos plus stray `commit_message.md` files after two
passes.

Relevant code: `src/sase/vcs_provider/plugins/_git_commit_dispatch.py` stages
user files and bead files, then `_merge_with_master()` fetches, stashes with
`git stash --keep-index`, and returns a manual conflict on merge failure. The
dispatcher stages all changed files under `sdd/beads/` before and after the
merge. `src/sase/main/cl_handler.py` reads `-M/--message-file` and deletes it
before `CommitWorkflow.run()`, so any later sync failure consumes the only
message-file copy.

Interpretation: the command has the information needed to handle the common
case itself. Agents should only be forced into manual recovery when the
incoming commit actually overlaps their task files semantically, as happened
once in `sase-ace_run-260620_140203`.

## Pattern 2: workspace and test environment drift wastes full runs

Several agents spent turns on toolchain or workspace state rather than the task:
stale Rust bindings, wrong Python selection, stale console-script shebangs,
global `sase` shadowing the workspace editable install, missing adjacent linked
checkouts, and `uv` lock issues.

Evidence: `sase-ace_run-260620_140203` rebuilt `sase_core_rs` after `%{...}`
tests failed on a stale sibling `sase-core`, then found `sase memory init` had
used the global `~/.local/bin/sase` instead of the workspace `.venv/bin/sase`.
`sase-tmp_260620_165748-main-260620_170842` found direct `pytest` was using an
old shebang pointing at a sibling workspace; `.venv/bin/python -m pytest` passed
the same test. Other cited runs hit wrong-Python pyo3 builds, `uv` lockfile
breakage, missing adjacent checkouts, and repeated clean-tree reruns to prove
commit-finalizer failures were pre-existing.

Relevant code/context: install guidance lives in `memory/build_and_run.md`, but
it is an instruction burden rather than an automated workspace invariant.
Commit-finalizer tests under `src/sase/llm_provider/` appear to depend on live
linked/sibling repo state and should be fixture-backed instead.

Interpretation: setup drift turns small tasks into environment diagnosis. Worse,
because every agent rediscovers the same pre-existing failures independently,
the cost multiplies across parallel work.

## Pattern 3: child beads lack enough task context

Bead workers and closeout agents frequently begin by discovering that the child
bead has an empty description or no design pointer. They then walk up to the
parent epic, inspect event streams, or reconstruct intent from commits.

Evidence: `sase-ace_run-260620_140203` starts with "The bead description is
empty" and reads the epic for the real design. `sase-ace_run-260620_140209`
moves from `sase bead show`, to bead-store inspection, to the parent epic before
finding the design file. `sase-tmp_260620_172151-main-260620_172745` shows why
this hurts closeout: child notes were mostly commit pointers, and some hashes
were no longer reachable.

Relevant code: `src/sase/bead/model.py` has a `design` field, and
`src/sase/bead/cli_crud.py` sets it for PLAN beads from `plan(<path>)`. PHASE
beads created with `phase(<parent>)` get `design=""` unless the caller fills it
manually.

Interpretation: the system already has a place to store the pointer, but the
workflow does not propagate it to the beads agents actually execute. This makes
every worker pay a discovery tax and makes closeout less reliable.

## Pattern 4: linked-repo finalization remains high-risk

Linked-repo finalization has improved, but recent chats still show cases where
SASE either missed dirty linked work or required multiple follow-up passes to
discover and clean it.

Evidence: `tmp_260620_135238` and `tmp_260620_135239` diagnosed a finalizer
result that reported clean/no changes while a linked workspace still had dirty
files. `sase-ace_run-260620_144314` favored run-start baselines over relying
only on opened-workspace markers or live config reconstruction.
`tmp_260620_151033` ended with dirty main, `sase-core`, and `sase-nvim`
workspaces after two finalizer passes.

Relevant code: `src/sase/llm_provider/commit_finalizer_state.py` combines
configured linked targets with opened-linked marker artifacts, then checks
changed files. `src/sase/linked_repos.py` records opened linked workspace dirs,
but part of the target set is still reconstructed at closeout time.

Interpretation: missed linked work is the most dangerous correctness failure in
the sample because SASE can report completion while real work is left dirty.
This belongs near the top of the implementation backlog even if the daily
token-cost winner is the bead-store commit race.

## Pattern 5: provider failures need earlier, sharper classification

The error rows include a burst of 401 authentication failures around
17:10-17:11. These were wrapped in the same continuation language as context
limits or transient provider issues, including a claim that on-disk edits were
preserved.

Evidence: `sase-tmp_260620_171132-workflow_tmp_260620_171132_main_ERROR-260620_171135`
prompts the agent to resume preserved edits, then immediately fails with
`401 Invalid authentication credentials`. Similar rows appear for
`tmp_260620_171123`, `tmp_260620_171120`, and several `gh` workflow children.

Relevant code: `src/sase/llm_provider/claude.py` raises on any non-zero provider
subprocess exit. Claude's built-in retry config includes `"API Error"` with
three retries and the generic continuation prompt; matching is substring-based
in `src/sase/llm_provider/retry_config.py`.

Interpretation: retry support exists, but the classification is too coarse.
Auth failures should be recognized before expensive sibling workflows are
launched, marked as environment/provider failures, and kept out of the generic
"resume preserved edits" path unless there is real on-disk state to resume.

## Other useful signals

- Closeout agents are valuable. They found real unfinished work in `sase-51`
  and `sase-52` after child beads had been closed, including advisory fallback
  behavior and `%{...}` directive acceptance. This argues for making closeout
  more structured, not for removing it.
- Full gates are expensive and sometimes repeated. Agents run targeted tests,
  then full `just check`, then commit preflight/fix steps, and sometimes repeat
  after environment-only changes or incoming commits. Scope-aware gating and
  cached clean-tree results would reduce churn.
- Some dispatcher chats are effectively blank because the meaningful outcome is
  in hidden Python steps. A one-line transcript summary with `count=`,
  `launched=`, and `reason=` would make later audits cheaper.

## Recommendation: the 3 highest-impact changes

### 1. Make `sase commit` survive common bead-store races and preserve message files

This is the highest-impact quality-of-life change because it fires at the end
of many successful tasks and currently turns completion into a manual recovery
loop.

Recommended shape:

- Defer deletion of `-M/--message-file` until `CommitWorkflow.run()` succeeds,
  or stop deleting it at all. A failed sync should never consume the only copy
  of the commit message.
- Teach `_merge_with_master()` to detect conflicts confined to generated bead
  state (`sdd/beads/issues.jsonl` and `sdd/beads/events/**`) and recover
  automatically: fast-forward to `origin/master`, reapply or regenerate this
  agent's bead mutation on the fresh base, restage, and continue.
- Add duplicate-close/idempotency guardrails so a retry cannot create repeated
  `issue_closed` events.
- When a real semantic conflict remains, return a structured error naming the
  incoming commits and overlapping non-bead files, so the agent starts from the
  right diagnosis.

Expected impact: removes the most frequent repeated detour in the chats,
including message recreation, bead-note recovery, and benign `issues.jsonl`
reconciliation.

### 2. Make ephemeral workspaces self-healing and finalizer tests hermetic

This removes zero-product-value debugging from one-line tasks and avoids every
agent rediscovering the same local setup failures.

Recommended shape:

- On workspace open/reuse, automatically ensure the editable install, Rust
  binding, and linked checkouts are coherent. In practice this means promoting
  the current `just install` guidance into a workspace-prep step that also
  covers `just rust-install` and linked-repo path resolution.
- Prefer workspace-local binaries in generated commands and docs-sensitive
  regeneration paths, or at least detect when `which sase` resolves outside the
  current workspace.
- Make commit-finalizer tests independent of live linked/sibling repo state by
  using fixtures for dirty linked repos, advisory paths, and config fallbacks.
- Cache or summarize clean-tree gate results so agents do not rerun the full
  suite solely to prove a known environmental failure is not theirs.

Expected impact: fewer stale-binding rebuilds, fewer wrong-binary regressions,
fewer full-gate reruns, and much faster termination for narrow changes.

### 3. Put design and acceptance context directly on child/phase beads

This improves both speed and correctness for bead workers and closeout agents.

Recommended shape:

- When creating a PHASE/child bead, inherit the parent plan/design path into the
  existing `design` field and add a concise description or acceptance note.
- Add a `sase bead show --full -j`-style source that includes parent epic,
  design path, phase section, dependencies, event-stream notes, related commits,
  and linked workspace paths.
- Store durable verification pointers in notes. Bare short commit hashes are
  not enough when worktrees move, branches rebase, or the verifier is in a
  different checkout.
- Feed that packet into closeout prompts so verifiers can focus on source/tests
  instead of reconstructing what "done" was supposed to mean.

Expected impact: removes the repeated 2-3 hop design hunt at the start of bead
runs, makes closeout cheaper, and reduces the chance that agents close a bead
whose real acceptance criteria were hidden in a parent epic or stale note.
