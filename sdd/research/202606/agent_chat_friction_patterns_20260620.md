# SASE agent chat friction patterns - 2026-06-20

## Scope

This note digs through SASE's most recent agent chat transcripts (all from 2026-06-20, via `sase chat list -j`)
to find recurring friction that makes agents slower, more expensive, or less likely to reach the right answer. The
goal is actionable code changes — to `sase commit` and elsewhere — that improve agent quality-of-life (QoL).

Method: ~27 unique conversations were analyzed (each is recorded ~3× under different workflow/agent aliases —
`ace-run`, `tmp_*-main`, `tmp_*-workflow_*_main`, `gh-*` — so the raw `chat list` count is inflated). The set
covers the full lifecycle seen that day: bead-completion workers (`sase-51.3`–`51.6`, `sase-52.5`–`52.7`),
plan-and-implement runs (`sase_context_workspaces_lane`, `complete_sase_52_alt_directive_predicate`), epic
verification runs (`sase-51`, `sase-52` closeout checks), planning/design runs, two investigative Q&A runs about
the commit finalizer, three empty audit-dispatcher runs, and 8 ERROR transcripts (6× auth-401, 2× context-limit).
Every claimed pattern below is grounded in (a) verbatim transcript evidence and (b) the implementing code, cited by
`file:line`.

## Summary

The transcripts show that agents spend a large and repeatable fraction of every run on **bookkeeping and environment
friction that has nothing to do with the engineering task**. The three highest-frequency, highest-cost, and most
fixable patterns are:

1. **`sase commit` loses the race against `origin/master` over the bead-store JSONL, and throws away the commit
   message on every failed attempt.** This hit essentially every commit in the dataset and forced manual
   `stash → fast-forward → pop` recovery cycles (up to 3× in a single run) plus message-file re-creation, note
   re-derivation, and duplicate-close cleanup.
2. **Ephemeral workspaces ship a stale/mismatched build (especially the `sase_core_rs` Rust binding) and the
   commit-finalizer tests leak live environment state**, so agents burn turns on rebuilds and on a recurring
   "stash and re-run on a clean tree to prove this failure is pre-existing" ritual.
3. **Child/phase beads carry empty `description`/`design`, so every worker and verifier re-derives intent** by
   hunting up to the parent epic (`sdd/epics/202606/*.md`) or reconstructing it from the event stream and bare,
   sometimes-stale commit hashes.

Three strong runner-ups (transient-failure retry, gate cost, finalizer re-litigation) are listed after the top 3.

---

## Patterns (evidence + code)

### Pattern 1 — The bead-store commit race + consumed message file (the #1 recurring time sink)

Nearly every commit in the dataset failed its first (and often second) attempt with a merge conflict while syncing
with `origin/master`, because parallel agents in the same epic all close sibling beads, which rewrites the same
bead-store files.

Transcript evidence:
- `sase-ace_run-260620_140203.md` (sase-51.3): the stash → fast-forward → pop dance ran **3 separate times** —
  "Origin/master advanced again ... The sync keeps racing"; "the branch is behind by 1 more commit (the race
  continues)".
- `sase-ace_run-260620_145512.md` (sase-52.7): two failed attempts — "Same error despite syncing ... `origin/master`
  advanced again — another agent just pushed `sase-51.6`'s close".
- `sase-ace_run-260620_145510.md` (sase-52.6): conflict + **duplicate close event** — "There are two duplicate close
  events (000042 and 000043) — the bead was closed twice during the session."
- `sase-ace_run-260620_153543.md` (sase-52.5): conflict forced recovery of hand-written notes — "let me recover the
  notes I added so I can re-apply them" before discarding and re-closing.
- The same shape appears in `sase-ace_run-260620_140209.md` (51.4) and the `155731 ERROR` design-lead transcript.

Compounding: **the commit message file is deleted the instant it is read, before the commit runs.** Agents reported
"the message file was consumed by the failed run — I'll recreate it" in *every* multi-attempt commit.

Code:
- Sync/conflict path: `src/sase/vcs_provider/plugins/_git_commit_dispatch.py:76-115` (`_merge_with_master`) fetches
  `origin/<default>`, `git stash --keep-index`, merges, and on conflict does `git merge --abort` + `stash pop` and
  returns a failure that becomes exit code 2 / `RunResult.CONFLICT`
  (`src/sase/workflows/commit/workflow.py:200-215`, `EXIT_CODE_CONFLICT = 2` at `workflow.py:49`). The skill then
  tells the agent: "Do NOT re-run the original `sase_git_commit` command ... resolve the conflict ... Run
  `sase_git_commit --resume`" (`~/.claude/skills/sase_git_commit/SKILL.md:97-119`).
- The colliding files: bead close/sync runs inside the precommit hook
  (`src/sase/workflows/commit/precommit_hooks.py:84-99` → `sase bead close` then `sase bead sync`), which rewrites
  `sdd/beads/issues.jsonl` and `sdd/beads/events/**` (`src/sase/bead/project.py:39,422`). `issues.jsonl` is a
  "generated compatibility projection" of the event store (`src/sase/bead/cli_admin.py:45-46`). The dispatcher then
  auto-stages everything under `sdd/beads/` (`_git_commit_dispatch.py:33-61`, called both before and after the merge
  at `:241` and `:255`).
- **The message-file bug:** `src/sase/main/cl_handler.py:48-58` reads `-M/--message-file` and immediately
  `os.remove(path)` — *before* `CommitWorkflow(...).run()` is invoked at `cl_handler.py:104-105`. So any
  conflict/failure inside `run()` leaves no message file behind. (`--resume` replays from a saved checkpoint and does
  not need the file, but the agent has usually already destroyed it on the first attempt.)

Why it matters: this is the single most frequent multi-step detour in the dataset, and it is pure bookkeeping. Both
sub-problems are confined to Python and are low-risk to fix.

### Pattern 2 — Stale ephemeral-workspace build + leaky finalizer tests

Multiple agents independently named environment setup as their biggest time sink. The ephemeral `sase_<N>` workspaces
(see `memory/sase.md`) frequently ship a stale compiled Rust binding or mismatched toolchain, and the recovery is
zero product value.

Transcript evidence:
- Stale `sase_core_rs` not recognizing `%{}`: `sase-ace_run-260620_171701.md` — "the installed Rust core binding in
  this workspace is not recognizing `%{...}` yet" → full `cargo` rebuild before a one-line Python fix could be tested.
  Same root cause in `sase-ace_run-260620_140203.md`, and in both `verify-51`/`verify-52` runs.
- pyo3 picked the wrong Python: `sase-ace_run-260620_145512.md` (52.7) — "pyo3 picked up Python 3.10 from PATH instead
  of 3.12 (the `| tail` masked the real exit code)".
- Stale `pytest` console-script shebang: `sase-tmp_260620_165748-main-260620_170842.md` — "the `pytest` script itself
  has an old shebang pointing at a sibling workspace"; fix was `.venv/bin/python -m pytest`.
- Wrong `sase` binary for memory regen: `sase-ace_run-260620_140203.md` — "the `sase memory init` I ran used a
  stale/global `sase` binary, not this workspace's editable install" (silently wrote wrong output to two locations).
- `uv` lockfile breakage: `sase-ace_run-260620_151638.md` — "`uv run` is blocked by a lockfile parse issue for
  `sase-core-rs` in this workspace, so I'm switching to the installed virtualenv's Python".
- `just install` failing on a missing adjacent core: `verify-51` — "`just install` failed because the linked
  `sase-core` checkout is not present at the expected adjacent path".

The "prove it isn't mine" ritual: because the **commit-finalizer tests read live linked/sibling-repo state**, the
same ~5 failures recur for every agent, who each independently stashes and re-runs on a clean tree to prove they are
pre-existing:
- `sase-ace_run-260620_171701.md` — "`just check` failed only in existing commit-finalizer tests, after 12,758 tests
  had passed ... consistent with the live SASE agent environment leaking linked/sibling repo state into
  commit-finalizer tests" (`test_config_fallback_reports_none_strategy_absolute_sibling_as_advisory`).
- `sase-ace_run-260620_151638.md`, `sase-ace_run-260620_140209.md`, `sase-ace_run-260620_145512.md`
  (`test_commit_finalizer_siblings_advisory.py`) all run the same triage.

Code: AGENTS.md / `memory/build_and_run.md` already warns "you need to run `just install` before running other
commands ... package dependencies may have changed" — but it is left to each agent to remember and to also rebuild
the Rust binding (`just rust-install`) and resolve the right linked checkout. There is no automatic
prepare-the-workspace step. The finalizer tests are Python-side under `src/sase/llm_provider/` and are not hermetic.

### Pattern 3 — Empty bead context forces re-derivation every run

Every bead-completion and every verification run opened by discovering the bead had no usable description or design,
then hunting for it.

Transcript evidence:
- `sase-ace_run-260620_140209.md` (51.4): a 3-hop hunt — "The `show` output doesn't include the description or design
  file" → "Let me look at the bead store files directly" → "Let me look at the parent epic" → "The design file is at
  `sdd/epics/202606/linked_repos_rename_codex.md`."
- `sase-ace_run-260620_140203.md`, `...140216.md`, `...145510.md`, `...153543.md` all start with a variant of "The
  bead description and design are empty. Let me look at the parent epic."
- Verification runs are worse, because child-bead notes are commit-hash-only and some hashes are stale:
  `sase-tmp_260620_172151-main-260620_172745.md` — "The child notes are commit pointers only, so the verification
  needs to come from the actual diffs and tests"; "Two child notes point at hashes that are no longer reachable in
  this checkout". `sase-tmp_260620_170317-main-260620_170701.md` had to find the right linked checkout by trial —
  "The `sase-nvim` work is in `sase-nvim_11`, not `_10`."

Code: the bead already has a `design` field (`src/sase/bead/model.py:35-52`), but it is populated **only for PLAN
beads** — `src/sase/bead/cli_crud.py:90-119` sets `design = storage_plan_path(...)` only when a plan path is given;
PHASE/child beads are created with `design=None` and empty `description`. So the design pointer exists structurally
but is not inherited onto the children the worker agents actually run.

### Secondary patterns (feed the runner-up recommendations)

- **Expensive, repeated, partly-spurious gates.** `just check` runs the full ~12,700-test suite, sometimes twice
  end-to-end in one run, then again inside `sase commit`'s `just fix` step
  (`sase-ace_run-260620_151638.md`: "I'm rerunning `just check`" after fixing one test; "The wrapper has entered its
  precommit step (`just fix`)"). mypy/prettier errors surface only at the full-gate stage
  (`sase-ace_run-260620_140209.md`).
- **No retry on transient provider failures.** A ~80-second auth outage (17:10:17–17:11:38) killed 6 agents outright
  with "401 Invalid authentication credentials"; 3 of them were *already* retries of prior context-limit (exit 143)
  deaths. One (`sase-gh-workflow_gh_main_ERROR-260620_170815.md`) had a finished-but-untested fix + new tests
  stranded mid-`just install`. Code: `src/sase/llm_provider/claude.py:246-252` raises on any non-zero exit; retry
  fires only on error-text substring match (`src/sase/llm_provider/retry_config.py:233-242`; Claude's patterns are
  just `["Prompt is too long", "socket connection was closed unexpectedly", "API Error"]` at `claude.py:101-110`).
  The exit code itself (143 SIGTERM, 401) is never inspected.
- **Hollow recovery prompt.** The context-limit continuation nudge promises "Any file edits ... are preserved"
  (`src/sase/llm_provider/retry_config.py:92-99`), but the 17:18 retry found a clean tree — "Working tree is clean —
  nothing from the previous attempt persisted" — so it re-did investigation from scratch and died again.
- **Finalizer re-litigates "done" decisions.** The post-commit finalizer re-invokes the provider up to `max_passes`
  as **fresh, context-less subprocesses** (new `--session-id` UUID, no `--resume`:
  `src/sase/llm_provider/commit_finalizer.py:207-226`, `claude.py:188-213`; called from `_invoke.py:218-226`). Agents
  reach "done, didn't commit," then the finalizer forces a second pass that reverses earlier decisions —
  `sase-ace_run-260620_140214.md` (51.5): "my earlier handoff note said 'commit reserved for Phase 6,' but
  re-reading the design, Phase 6 is bob-cli only"; `sase-ace_run-260620_140216.md` (51.6) dual auto-close/explicit-close
  confusion.
- **Context bloat from verbatim replay.** A follow-up turn
  (`sase-tmp_260620_164514-main-260620_165243.md`) prepended ~180 lines of the prior implementation conversation
  before a small planning query.
- **Silent audit dispatchers.** `audit_recent_bugs`, `audit_recent_improvements`, and `pylimit_split`
  (`sase-ace_run-260620_170119.md`, `...165801.md`, `...164357.md`) produced empty transcripts by design (hidden
  python steps that launch separate agents), but the step output (`count=`, `should_launch=`,
  `reason=below_threshold`, `launched=`) is never surfaced, so you cannot tell from the transcript whether they fired
  or skipped.

---

## Recommendation: the 3 highest-impact changes

### 1. Make `sase commit` survive the bead-store race and never throw away the message

This is the highest-leverage change because it fires on essentially every task-ending commit and is pure
bookkeeping. Two parts:

- **Stop consuming the message file on failure.** In `src/sase/main/cl_handler.py:48-58`, defer the `os.remove()`
  until the commit actually succeeds (or simply do not delete it and let `--resume` reuse it). This alone removes the
  universal "the message file was consumed — I'll recreate it" tax from every multi-attempt commit.
- **Auto-resolve conflicts confined to `sdd/beads/`.** `issues.jsonl` and `events/**` are regenerated projections of
  the event store, so a conflict there is not a real content conflict. When `_merge_with_master`
  (`_git_commit_dispatch.py:76-115`) detects that the *only* conflicting paths are under `sdd/beads/`, it should
  resolve them automatically — take `origin/master`'s bead store, fast-forward, re-apply this agent's bead
  close/sync (idempotent via the event store), re-stage, and continue — instead of returning `CONFLICT` and pushing
  the agent through a manual `stash → ff → pop` loop. A `.gitattributes` `merge=union` driver for `sdd/beads/**` is a
  lighter-weight alternative. Also dedupe `issue_closed` events so the double-close seen in `sase-52.6` cannot
  happen.

Expected impact: eliminates the most frequent multi-step detour in the dataset (often 1–3 recovery cycles per run),
plus message re-creation, note re-derivation, and duplicate-close cleanup. Agents terminate the commit phase in one
attempt instead of three.

### 2. Self-heal the workspace build, and make the finalizer tests hermetic

Removes a whole class of zero-value rebuild/rabbit-hole turns that currently block even one-line changes.

- **Prepare the workspace automatically on open/reuse.** Run `just install` + `just rust-install` and resolve/link
  the correct `sase-core`/`sase-nvim` checkout as part of bringing an ephemeral workspace online, so agents never
  hit a stale `sase_core_rs` binding, a wrong-Python pyo3 build, a stale `pytest` shebang, a global-vs-`.venv` `sase`
  binary, or a broken `uv` lock. AGENTS.md already mandates `just install` "before running other commands" — promote
  that from a per-agent instruction to an automated prepare step (and include the Rust binding + linked-repo
  resolution it currently omits).
- **Make commit-finalizer tests hermetic.** Pin `test_commit_finalizer_siblings_advisory.py` and
  `test_config_fallback_reports_none_strategy_absolute_sibling_as_advisory` (and their neighbors) to fixtures so they
  do not read the live agent's linked/sibling-repo state. Today every implementation agent independently rediscovers
  the same ~5 "pre-existing" failures and runs a stash-and-re-run ritual to disprove ownership; hermetic tests make
  `just check` green in a clean workspace and delete that ritual entirely.

Expected impact: one-line tasks stop being gated on toolchain churn; agents stop spending turns proving that
environmental failures are not theirs; far fewer full-gate re-runs.

### 3. Put design + acceptance context on the bead (especially child/phase beads)

Removes ramp-up discovery from every bead run and makes "is this done?" answerable from the bead instead of from the
event stream.

- **Inherit `design` onto child/phase beads at creation.** The field already exists
  (`src/sase/bead/model.py:35-52`) but is set only for PLAN beads (`src/sase/bead/cli_crud.py:90-119`). When creating
  a phase/child under a plan or epic, copy the parent's `design` path down and write a one-line `description` so the
  worker agent does not have to walk up to `sdd/epics/202606/*.md`.
- **Store a short, structured acceptance note** (what "done" means for this bead) so verification runs can confirm
  completion without re-deriving intent from diffs.
- **Use durable pointers in notes, not bare commit hashes.** Verification runs repeatedly hit notes whose short
  hashes were "no longer reachable in this checkout" after rebases/worktrees. Prefer a design/PR/bead-id pointer that
  survives history rewrites.

Expected impact: cuts the 2–3-hop design hunt at the start of every bead run, and removes the expensive
"reconstruct intent from the event stream + stale hashes" pattern that dominated all three verification runs.

---

## Strong runner-ups

4. **Retry transient provider failures by exit code, not error text.** Treat exit 143 (SIGTERM/context kill) and
   401 (auth) as retryable with backoff in `src/sase/llm_provider/claude.py:246-252` /
   `src/sase/axe/run_agent_exec_retry.py`. A single ~80s auth blip killed 6 agents and stranded finished work; a
   short backoff would have salvaged all of them. While here, make the recovery nudge
   (`retry_config.py:92-99`) check `git status` and tell the agent honestly when nothing persisted.
5. **Gate-once / scope-aware `just check`.** Avoid running the full ~12.7k-test suite multiple times per task (and
   again inside `sase commit`'s `just fix`). Skip the Rust/visual suites when no relevant files changed, and cache a
   clean-tree gate result so the "prove it's pre-existing" re-runs become unnecessary.
6. **Reduce finalizer re-litigation and context bloat.** The finalizer's fresh-subprocess passes reverse earlier
   decisions; give it the agent's own handoff note/decision log so it does not re-open settled choices, and stop
   prepending entire prior conversations verbatim to follow-up turns.
7. **Surface audit-dispatcher outcomes.** Emit a one-line summary (`count=`, `launched=`, `reason=`) into the
   transcript for `audit_recent_bugs` / `audit_recent_improvements` / `pylimit_split` so a reader can tell whether the
   dispatcher fired or skipped.

---

## Appendix: data inventory

- Source: `sase chat list -j -l 60` on 2026-06-20; all transcripts dated 2026-06-20.
- ~27 unique conversations (each duplicated ~3× across `ace-run` / `tmp_*-main` / `tmp_*-workflow` / `gh-*` aliases).
- Bead workers: `sase-51.3`–`51.6`, `sase-52.5`–`52.7`. Plan+implement: `sase_context_workspaces_lane`,
  `complete_sase_52_alt_directive_predicate`. Verify/closeout: `sase-51`, `sase-52`. Plans submitted:
  `sase_51_closeout`, `linked_repos_advisory_fallback`, `complete_sase_52`, `workspace_tmux_chooser`,
  `sase_context_workspaces_lane`. Investigative Q&A: commit-finalizer mechanism (claude + codex). Empty
  dispatchers: `audit_recent_bugs`, `audit_recent_improvements`, `pylimit_split`.
- ERRORs: 6× "401 Invalid authentication credentials" (exit 1) in a ~80s burst; 2× exit 143 (context limit). 3 of
  the 401s were retries of prior 143 deaths.
- Code references verified against this workspace (`src/sase/...`) and `~/.claude/skills/sase_git_commit/SKILL.md`.
  Bead-store and commit-sync logic is currently Python-side; per `memory/rust_core_backend_boundary.md`, any change
  to bead-store or commit-sync *semantics* should be evaluated for the `sase-core` boundary before implementation.
