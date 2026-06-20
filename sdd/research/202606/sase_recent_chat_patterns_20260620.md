# Recent SASE Chat Pattern Research - 2026-06-20

## Scope

This note reviews recent saved SASE chat transcripts to identify recurring agent pain points that can be addressed with
code changes. The goal is not to judge individual agents, but to find system behaviors that make agents spend extra
tokens, miss relevant state, leave work unfinished, or loop on known recovery procedures.

Primary index command:

```bash
sase chat list -j -l 200
```

The 200-row sample is not 200 independent tasks. SASE often records wrapper rows for the same underlying run
(`ace-run`, workflow child, `main`, and error records). I treated the list as a recent activity index, then read the
representative transcripts below with `sase chat show`.

## Sampled transcripts

| Transcript basename | Why sampled |
| --- | --- |
| `sase-tmp_260620_135238-workflow_tmp_260620_135238_main_ERROR-260620_135242` | Commit finalizer missed dirty `bob-plugins_11` linked-repo changes. |
| `sase-tmp_260620_135239-workflow_tmp_260620_135239_main_ERROR-260620_135244` | Same finalizer miss, with a different diagnostic path. |
| `sase-ace_run-260620_144314` | Compared two proposed fixes for the linked-repo finalizer miss. |
| `sase-tmp_260620_151033-workflow_tmp_260620_151033_main_ERROR-260620_151051` | Commit finalizer failed after two passes with dirty linked workspaces. |
| `sase-tmp_260620_152136-main-260620_161109` | Bead implementation plus finalizer commit under heavy `issues.jsonl` races. |
| `sase-tmp_260620_161218-main-260620_163729` | Bead worker had to rediscover an empty child-bead description/design. |
| `sase-tmp_260620_153621-main-260620_160205` | Cross-repo bead work in `sase-core` and `sase-nvim`, then commit reconciliation. |
| `sase-tmp_260620_160222-main-260620_163046` | Bead close duplicated once during commit race, then had to be re-closed cleanly. |
| `sase-tmp_260620_163127-main-260620_170239` | Final phase docs/verification plus repeated commit races on bead files. |
| `sase-tmp_260620_165748-main-260620_170842` | Epic closeout found a real finalizer acceptance regression after children were closed. |
| `sase-tmp_260620_170317-main-260620_170701` | Epic closeout found a real `%{...}` predicate gap after children were closed. |
| `sase-tmp_260620_172151-main-260620_172745` | Later closeout still found unresolved verification failures. |
| `sase-tmp_260620_171132-workflow_tmp_260620_171132_main_ERROR-260620_171135` | Repeated provider 401 auth failure classified as generic transient/context resume. |
| `sase-gh-workflow_gh_main_ERROR-260620_170348` | Provider failed after a long file-reading preamble, wasting context. |
| `sase-tmp_260620_172753-main-260620_173013` | Direct investigation of finalizer subprocess/session behavior. |
| `sase-tmp_260620_172759-main-260620_172914` | Same finalizer question answered by another model. |

Approximate categories in the last 200 rows:

| Category | Rows | Notes |
| --- | ---: | --- |
| Bead implementation work | 39 | Many rows are duplicate wrappers, but this is the dominant task class. |
| Error transcripts | 19 | Includes exit 143 interruptions, 401 auth failures, and finalizer failures. |
| Plan submissions | 17 | Usually short, but often followed by implementation/commit runs. |
| Commit/finalizer-focused prompts | 13 | Includes both diagnosis and direct behavior questions. |
| Epic/bead closeout verification | 6 | Small count but high value: these found real unfinished work. |

## Pattern 1: linked-repo finalization is still too easy to miss

Several chats were about changes left in linked repositories after an agent appeared to finish.

Evidence:

- `sase-tmp_260620_135238...` and `sase-tmp_260620_135239...` both diagnosed the same `bob-cli` / `bob-plugins`
  incident. The finalizer result said `clean / no_changes`, while the linked workspace still had dirty files. The
  agents found that `opened_siblings.json` had recorded the correct linked workspace, but the finalizer was still
  recomputing or losing the linked target under config/env drift.
- `sase-ace_run-260620_144314` compared two fixes for a later example where an agent left uncommitted
  `bob-plugins_11` changes. The approved direction was a run-start git baseline rather than relying on tool telemetry
  or opened markers alone.
- `sase-tmp_260620_151033...` ended with `Commit finalizer failed: uncommitted changes remain after 2 finalizer
  pass(es)` across `main`, `sase-core`, and `sase-nvim`, including stray `commit_message.md` files.
- `sase-tmp_260620_172753...` and `sase-tmp_260620_172759...` show that even understanding finalizer behavior required
  code archaeology. Both agents confirmed that each pass launches a fresh provider subprocess and carries context by
  reinjecting prompt text, not by talking to the previous live process.

Relevant code shape:

- `src/sase/llm_provider/commit_finalizer_state.py` discovers dirty repos in `collect_dirty_state()`.
- `src/sase/linked_repos.py` records opened linked repos and already stores `workspace_dir` in the marker files.
- `src/sase/llm_provider/commit_finalizer.py` invokes bounded follow-up provider calls after the initial run.

Interpretation: the linked-repo finalizer has improved, but the recent chats show the system still relies on brittle
runtime reconstruction. If reconstruction is wrong, the finalizer can report clean while real agent work remains dirty.
If reconstruction is partly right but cleanup is hard, agents burn extra passes and still fail.

## Pattern 2: `sase commit` makes agents manually resolve predictable bead-store races

The sampled implementation transcripts repeatedly hit the same commit failure mode: another agent pushed while the
current agent had bead-store changes staged, usually touching `sdd/beads/issues.jsonl`.

Evidence:

- `sase-tmp_260620_152136...` includes a long finalizer commit sequence for `sase-51.3`: stash, fast-forward, pop,
  inspect incoming commits, resolve overlapping docs/memory conflicts, regenerate memory with the correct workspace
  binary, rerun checks, then retry as `origin/master` advanced again.
- `sase-tmp_260620_161218...` hit a sync conflict because incoming work touched `sdd/beads/issues.jsonl`; it had to
  stash, fast-forward, pop, verify both bead closures, and retry.
- `sase-tmp_260620_153621...`, `sase-tmp_260620_160222...`, and `sase-tmp_260620_163127...` all describe variants of
  the same loop: commit attempt fails with "Merge conflict syncing with origin/master", the agent inspects whether the
  overlap is only bead state, manually reconciles, recreates a consumed commit message file, and retries.
- `sase-tmp_260620_160222...` also found duplicate `issue_closed` events created during the session. The agent fixed
  this by discarding stale bead JSONL edits, fast-forwarding, and re-closing once on the fresh base.

Relevant code shape:

- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py` stages requested files and bead state, then `_merge_with_master()`
  runs `git stash --keep-index`, merges, and returns a manual conflict message on failure.
- The bead projection file `sdd/beads/issues.jsonl` is a hot generated file. Many unrelated bead closes touch it.

Interpretation: the current behavior is technically recoverable, but the recovery is expensive and repetitive. Agents
are doing the same safe sequence by hand: preserve work, fast-forward, regenerate or reapply bead state on top, verify,
and retry. This is exactly the sort of deterministic recovery the command should own.

## Pattern 3: bead prompts often force agents to rediscover task context

Many bead workers begin by reading the bead, then realizing the child bead has an empty description or design field and
that the real design lives in the parent epic file.

Evidence:

- `sase-tmp_260620_161218...`: "The `show` output doesn't include the description or design file" followed by direct
  bead-store inspection; then "The bead itself has an empty description and design" and parent-epic lookup.
- `sase-tmp_260620_152136...`: "The bead description is empty - the design lives in the epic file."
- `sase-tmp_260620_153621...`: "No design file is linked directly. Let me find the design/plan file for the sase-52
  epic."
- `sase-tmp_260620_165748...` and `sase-tmp_260620_172151...`: closeout agents had to use event streams because child
  notes displayed by the current bead view had been reduced to commit pointers.

Relevant code shape:

- `sase bead show` takes only an ID (`src/sase/main/parser_bead.py`) and prints fields if present
  (`src/sase/bead/cli_query.py`). It has no JSON/full/context flag in this checkout.
- Child beads can have empty `description` and `design` fields even when the parent epic has a concrete plan file and
  phase section.

Interpretation: the agent eventually finds the right context, but only after exploratory commands. This cost repeats on
every child bead. Worse, closeout agents sometimes need historical event-stream notes because visible notes are no
longer rich enough to verify the claims that previous agents made.

## Pattern 4: closeout agents are catching real unfinished work

The closeout prompts are doing useful work: they caught actual gaps after child beads were already closed.

Evidence:

- `sase-tmp_260620_165748...` found that static `workspace.strategy: none` linked repos from a legacy
  `sibling_repos` config fallback were not reported as advisory in the finalizer path. It produced a remaining-work
  plan instead of closing `sase-51`.
- `sase-tmp_260620_170317...` found a real gap in the `%{...}` alt directive path: `has_alt_directive()` returned false
  in contexts where the launch parser accepted the shorthand.
- `sase-tmp_260620_172151...` found remaining verification failures and created a short plan rather than closing the
  epic.

Interpretation: closeout is valuable, but it is currently ad hoc. The agent has to assemble commits, child bead notes,
plan frontmatter, source diffs, cross-repo state, and verification commands manually. Since closeout is where hidden
quality gaps are found, a first-class closeout helper would likely pay for itself.

## Pattern 5: provider failures are treated too much like resumable task failures

Several rows show immediate provider failures, especially 401 auth failures, being wrapped in the same "previous
attempt hit a model context limit or transient provider failure" resume prompt.

Evidence:

- `sase-tmp_260620_171132...`, `sase-tmp_260620_171123...`, and `sase-tmp_260620_171120...` are repeated 401 invalid
  authentication failures.
- `sase-gh-workflow_gh_main_ERROR-260620_170348` shows the provider produced a long exploration preamble and then ended
  with the same 401. That consumed useful context before the run failed.
- Several exit-143 rows also preserve partial reasoning, which is useful, but they are mixed with non-retryable auth
  failures in the recent index.

Interpretation: SASE should distinguish non-retryable provider health failures from task/context failures. A 401 should
fail fast, mark the agent as an environment/provider problem, and avoid launching sibling or follow-up attempts with the
same broken credentials.

## Follow-up candidates

- Add a `sase finalizer explain <artifact-dir>` command that summarizes why each repo was or was not considered dirty,
  including linked-repo target source: baseline, opened marker, env, or config fallback.
- Add duplicate-close/idempotency guardrails to the bead event store so a second close attempt does not create redundant
  `issue_closed` events.
- Track provider failure classes in the agent list/TUI so auth failures, context limits, and user-killed exits do not
  look identical.

## Recommendation: top three changes

### 1. Make linked-repo finalization baseline-based and path-authoritative

At agent launch, record a per-linked-repo baseline artifact for every resolved linked repo, not just those opened with
`sase workspace open`.

Recommended shape:

- Write a `linked_repo_baseline.json` artifact containing repo name, resolved workspace path, workspace strategy, HEAD,
  tracked dirty file state, and enough per-path stat/blob data to detect "already dirty, then changed again."
- Use recorded paths from the baseline and opened-linked markers as authoritative finalizer targets. Avoid recomputing
  workspace paths from possibly drifted config unless the artifact is missing.
- Split finalizer output into required dirty repos, advisory dirty repos, and unattributed pre-existing dirt. Put this
  directly into `commit_finalizer_result.json`.
- Update finalizer prompts to tell agents exactly which repo/path/files must be committed and why.

Why this is highest impact: missed linked-repo commits are the most dangerous failure mode in the sample. They leave
real user work behind while SASE reports completion. Baselines also reduce diagnostic ambiguity and follow-up prompt
size because the finalizer can say precisely what changed during the run.

### 2. Teach `sase commit` to auto-reconcile predictable bead-store races

The commit path should own the common "origin advanced while bead files are staged" workflow.

Recommended shape:

- Replace the current `stash --keep-index` merge strategy with an autostash/full-stash flow that can fast-forward first,
  then reapply staged user changes and restage the requested files.
- Add a bead-aware recovery path: if the only overlap is `sdd/beads/issues.jsonl` and event-stream files, rebase by
  reloading/regenerating the bead projection or reapplying the intended bead mutation on the new HEAD.
- Preserve commit-message content across failed attempts instead of consuming `commit_message.md` before a sync succeeds.
- Surface a structured error when a real semantic conflict remains: incoming commit(s), overlapping files, and the
  smallest safe next command.

Why this is high impact: the current manual recovery sequence is repeated in many recent chats and costs hundreds of
lines of reasoning per occurrence. It is deterministic enough to automate for the common bead-store case, and it would
make finalizers terminate faster with fewer retries.

### 3. Generate a run-context packet for bead and closeout agents, with provider fail-fast checks

Before launching a bead worker or closeout agent, SASE should produce a compact, structured context packet and validate
that the selected provider/model can actually run.

Recommended shape:

- Add a `sase bead show --full -j`-style data source or internal equivalent that includes child bead fields, parent
  epic/design path, phase section, dependencies, historical notes from the event stream, related commit hashes, and
  linked-repo workspace paths.
- Inject the resolved packet into bead-work and closeout prompts so agents do not spend their first turns rediscovering
  empty child descriptions, parent epic files, or overwritten notes.
- Add a closeout helper that enumerates child beads, commit messages by bead ID, plan status, notes requiring
  verification, and recommended validation commands.
- Run a cheap provider/model/auth preflight before launching expensive workflows. Classify 401/auth errors as
  non-retryable environment failures rather than generic transient/context failures.

Why this is high impact: it improves both correctness and cost. Agents reach the relevant design and verification
surface sooner, and SASE avoids launching doomed provider runs. The closeout transcripts show that this workflow finds
real hidden defects; making it structured should improve closeout quality while reducing exploratory token spend.
