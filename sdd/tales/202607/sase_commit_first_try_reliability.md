---
create_time: 2026-07-07 17:00:17
status: done
prompt: sdd/prompts/202607/sase_commit_first_try_reliability.md
---
# Make `sase commit` succeed on the first try

## Problem

`sase commit` (invoked by agents via the `/sase_git_commit` skill) fails roughly 10–15% of the time, and nearly every
failure converts a finished task into a long manual recovery loop. Evidence:

- `~/.sase_git_commit.jsonl` (wrapper telemetry): 446 failed vs 2610 ok commit events overall; recent daily rates of
  15/96 (07-06) and 11/73 (07-07) failures, all exit code 1.
- July chat transcripts: 36 chat files narrate a "merge conflict while syncing with `origin/master`" recovery, and 36
  narrate "recreate the commit message and retry". Example: `sase-tmp_260707_134628-main-260707_141803` spent ~30
  minutes on a commit whose only conflicts were bead bookkeeping files — stash, fast-forward, hand-renumber bead event
  IDs, re-run the full `just check` gate (during which master moved again), recreate the message file, retry, then clean
  up leftover stashes.
- Retry storms in the wrapper log: identical-argument invocations repeated 2–4× minutes apart (e.g. four attempts
  07:44→07:50 on 07-06; paired bead-file retries at 14:05/14:07 and 14:30/14:32 on 07-07 across parallel sase-5h
  workers).
- `sdd/research/202606/sase_agent_qol_chat_patterns_consolidated_20260620.md` Recommendation 1 ("Make `sase commit`
  survive common bead-store races and preserve message files") describes the same failure shape; it is still the top
  recurring cost three weeks later.

### Root causes (verified in code)

1. **The sync step fails on any upstream movement of staged files, not just real conflicts.** `_merge_with_master()`
   (`src/sase/vcs_provider/plugins/_git_commit_dispatch.py`) stashes with `--keep-index` and then runs
   `git merge origin/<default>`. Because the staged copies stay in the index/worktree, git refuses the merge whenever an
   incoming commit touches _any_ staged file — even when a rebase would auto-merge cleanly. Parallel bead workers always
   touch `sdd/beads/issues.jsonl` + `sdd/beads/events/streams/*.jsonl`, so sibling-phase commits collide almost
   deterministically.
2. **Failure consumes the only copy of the commit message.** `handle_commit_command()`
   (`src/sase/main/commit_handler.py`) reads and deletes the `-M/--message-file` _before_ `CommitWorkflow.run()`. Every
   failed attempt forces the agent to re-author the message file.
3. **The documented recovery flow is unreachable.** The `/sase_git_commit` skill's "On Merge Conflict" section documents
   exit code 2 → paused rebase → resolve → `sase_git_commit --resume`. But the create_commit conflict path aborts the
   merge, pops the stash, exits 1, and deletes the checkpoint, so `--resume` finds nothing. July chats show agents
   dutifully trying `--resume`, getting "no resumable checkpoint", and falling back to hand-rolled recovery.
4. **Bead-store conflicts are mechanical yet unautomated.** Event streams are per-epic append-only JSONL with dense
   ordinals (`sase-5h:000049:...`, assigned as `len+1` in sase-core `bead/mutation.rs::append_issue_event`). Two agents
   appending on divergent bases always produce colliding event IDs. Agents resolve this by hand the same way every time:
   keep upstream's events, re-append local events with fresh IDs, regenerate the projection.
5. **Retries create duplicate bead events.** `close_issues()`/`close_one()` in sase-core append an `issue_closed` event
   even when the issue is already closed, so each retry of `handle_beads()` pollutes the stream and forces cleanup
   detours.
6. **Precommit failures are opaque.** `run_precommit()` (`src/sase/workflows/commit/precommit_hooks.py`) captures the
   precommit command's stdout/stderr and discards them; agents only see "Precommit command failed (exit 1): just fix" (9
   July chat files show this class) and must re-run the gate blind to diagnose.

## Goal

An agent that finishes its work and runs `/sase_git_commit` once should end with a pushed commit, with zero manual
recovery, in the presence of:

- concurrent commits from sibling agents that touch bead bookkeeping files, and
- unrelated upstream movement of files the agent staged.

When first-try success is genuinely impossible (real semantic conflict in non-bead files), the command must leave a
_resumable_ state that matches what the skill documents, name the conflicted files and incoming commits, and never
destroy the commit message.

## Design

### Phase 1 — Preserve the commit message on failure

`src/sase/main/commit_handler.py`:

- Stop deleting the `-M` message file before running the workflow. Delete it only when the workflow returns
  `RunResult.OK`.
- On `FAILED`/`CONFLICT`, keep the file and print a clear line, e.g.
  `Commit message preserved at commit_message.md — re-run with the same -M flag after fixing.`

Tests: handler-level tests asserting the file survives failure and is removed on success.

### Phase 2 — Actionable failure output and structured failure reasons

- `run_precommit()`: on failure, print the tail (~50 lines) of the command's stdout/stderr so the agent can fix the
  issue without re-running the gate blind.
- `CommitWorkflow.run()`: classify failures (`precommit_failed`, `sync_conflict`, `push_failed`, `no_staged_changes`,
  `other`) and emit `log_event(event="commit_failed", method=..., reason=...)` alongside the existing
  `commit_created`/`commit_conflict` events, so future reliability audits can be done from logs instead of chat mining.

### Phase 3 — Commit-first sync: rebase instead of stash-and-merge

Redesign `vcs_create_commit` in `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`:

1. Stage files, stage bead state/plan paths, validate staged changes (unchanged).
2. **Commit locally first** (before any sync). The commit now durably holds both the changes and the message — nothing
   to recreate on any later failure.
3. Run the post-commit bead note/amend step (as today).
4. Fetch and `git rebase --autostash origin/<default>` (skip when detached HEAD / no remote, as today).
   - Clean rebase → push. On push rejection (another agent won the race), re-fetch + re-rebase + re-push a bounded
     number of times instead of today's `git pull --no-edit`.
   - Rebase conflict → attempt bead-store auto-resolution (Phase 4). If unresolved non-bead conflicts remain, leave the
     rebase paused and return a structured conflict error naming the conflicted files and the incoming commits
     (`git log --oneline HEAD..origin/<default> -- <files>`). The workflow already returns `RunResult.CONFLICT` (exit 2)
     and _retains the checkpoint_ in this case, so the existing `--resume` path (resolve → `git rebase --continue` →
     `sase commit --resume`) finally becomes the real, reachable recovery flow — exactly what the skill already
     documents. The resume-path HEAD-subject check already validates this shape.
5. Remove `_merge_with_master()` (create_commit is its only caller) and the stash bookkeeping that leaves stray stash
   entries behind.

`create_pull_request` and `create_proposal` are unchanged (branch-suffix race handling already exists for PRs). The hg
provider and all agent runtimes are unaffected; exit-code semantics (0/1/2) are unchanged.

Tests: pytest fixtures building a temp origin plus two clones, covering: upstream movement of a staged file with no
textual conflict (must succeed first try — the dominant failure today); genuine non-bead conflict (exit 2, paused
rebase, `--resume` completes after manual resolution); push race (bounded rebase+push retry succeeds); detached HEAD and
no-remote skips.

### Phase 4 — Bead-store conflict auto-resolution + idempotent close

This is core domain behavior, so per the Rust core backend boundary the merge/idempotency logic lands in the sase-core
linked repo (open it via `sase workspace open`), exposed through `sase_core_rs`, with thin Python callers here.

sase-core (`crates/sase_core/src/bead/`):

- New API `merge_bead_event_streams(base, ours, theirs)`: three-way union merge of one stream — result = theirs'
  events + (ours-minus-base events, appended in their original relative order with freshly renumbered ordinals/event IDs
  after theirs' max). This is precisely the manual resolution agents perform today. Reuse `reduce_event_streams()` to
  regenerate the `issues.jsonl` projection and `BeadEventStoreManifestWire::from_streams()` for the manifest.
- Idempotent close: `close_issues()`/`close_one()` skip already-closed issues without appending a duplicate
  `issue_closed` event, reporting them as already-closed in the outcome. This makes `handle_beads()` retries and
  finalizer re-runs event-clean.
- Wire types, `sase_core_rs` binding exposure, and Rust-side tests per the linked-repo workflow.

This repo:

- New `sase bead resolve-conflicts` subcommand (follow `memory/cli_rules.md`: alphabetical listing, short aliases,
  quality `--help`): detect git-conflicted files under `sdd/beads/`, extract base/ours/theirs via
  `git show :1:/:2:/:3:`, call the core merge for each stream, regenerate `issues.jsonl` + `events/manifest.json`,
  rebuild the SQLite cache (`rebuild_from_jsonl` already exists; `beads.db` is gitignored), and `git add` the results.
  Non-zero exit if any conflicted bead file cannot be auto-merged (e.g. `config.json`).
- Integrate into Phase 3's rebase-conflict handler: when every conflicted file is under `sdd/beads/`, run the resolver,
  `git -c core.editor=true rebase --continue`, and proceed to push — the agent never sees the conflict. Fall through to
  the exit-2 path only when non-bead conflicts remain or resolution fails.

Tests: two clones closing sibling phase beads of the same epic and committing concurrently — both succeed first-try and
the merged stream validates + reduces to a projection with both phases closed; a retried close produces no duplicate
`issue_closed` events; a conflicted non-mergeable bead file falls back to exit 2.

### Phase 5 — Align the `/sase_git_commit` skill with the new reality

Update the source template `src/sase/xprompts/skills/sase_git_commit.md` (never the generated copies; regenerate with
`sase skill init --force` and deploy with `chezmoi apply` per `memory/generated_skills.md`):

- `-M` semantics: file is deleted only on success; on failure it is preserved — retry with the same flag, do not
  re-author it.
- Failure semantics: exit 1 = failed with a printed reason (fix the cause, re-run the same command; bead close is
  idempotent so re-runs are safe); exit 2 = paused rebase (keep the existing resolve → `git rebase --continue` →
  `sase_git_commit --resume` instructions, which are now truthful).
- State explicitly that bead-store conflicts and benign upstream movement are handled automatically: agents must NOT
  preemptively stash/fast-forward/hand-sync before committing, and must NOT re-run the original command while a rebase
  is paused.
- Per the CLI/skill contract sync rule, update in-repo callers/wrappers and the tests that validate skill invocation
  examples in the same change.

Also review the commit-instruction text used by the post-completion finalizer (`src/sase/commit_instructions.py`,
`src/sase/llm_provider/commit_finalizer_prompting.py`) so its guidance matches the updated skill (no contradictory
recovery advice).

### Phase 6 — End-to-end race verification

A slow-marked integration test simulating N (≥3) parallel workers, each closing a sibling bead of one epic and running
the full `sase commit` flow against a shared origin: all N commits land without manual intervention, event streams
validate, and the reduced projection shows every phase closed exactly once. This is the regression gate for the whole
feature.

## Sequencing and compatibility

- Phases 1–2 are independent quick wins and can land immediately.
- Phase 3 lands before Phase 4 integration but is already a large reliability win on its own (benign upstream movement —
  the dominant case — stops failing).
- Phase 4's sase-core API + binding must land in the linked repo first, then the Python caller here.
- Phase 5 lands last so the skill documents shipped behavior.
- Out of scope: `memory/*.md` edits (require explicit user approval), workspace self-healing and bead-context
  propagation (recommendations 2–3 of the research note), hg provider changes.

## Success metrics

- First-try success rate in `~/.sase_git_commit.jsonl` rises from ~85–90% to >98%; retry storms (identical-args reruns
  within minutes) disappear.
- New `commit_failed` run-log events show remaining failures classified, with `sync_conflict` near zero.
- No new July-style chat narrations of "recreate the commit message" / hand-renumbering bead event IDs.
