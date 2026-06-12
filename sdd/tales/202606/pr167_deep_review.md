---
create_time: 2026-06-12 08:09:25
status: done
---
# Deep Review of PR #167 — Verify and Improve the 11 Claimed Bug Fixes

## Context

PR #167 (`sase_recent_bug_audit_sase_690d4a3bee64_1`, single commit `0a9e49058` on top of master) claims to fix 11 bugs
found in an audit of 203 commits (`cb7a4a556..690d4a3be`). Each fix ships with a regression test.

Goal of this task (a review, not a feature):

1. **Verify legitimacy** — for each of the 11 claims, confirm the bug actually existed in pre-fix code (`master` /
   merge-base) by tracing the code path and confirming the claimed failure mode.
2. **Verify the fix** — confirm each fix is correct _and complete_ (no missed call sites, no new bugs, no regressions in
   adjacent behavior), and that the regression test genuinely fails without the src fix.
3. **Improve** — apply only _objective_ improvements found during the review (bug in the fix, missed call site,
   wrong/incomplete edge case, factually wrong error message). No stylistic churn. Each improvement gets or extends a
   test.

Deliverable: a per-bug verdict report (legitimate? fix correct? improvement applied?) plus any improvement commits-worth
of changes left on this branch with `just check` passing.

## The 11 claims and how each will be verified

### Race / data-loss fixes (TUI task queue)

**1. Dismissed-agents persistence race** (`dismissed_agents.py` + 5 TUI call sites) Claim: concurrent kill/dismiss
workers each blind-wrote a full-set snapshot of `dismissed_agents.json`, so a slow older worker could erase a later
dismissal. Fix: generation-stamped snapshots (`snapshot_dismissed_agents`) captured on the mutating thread;
`save_dismissed_agents` skips superseded snapshots and call sites gate the artifact-index sync on the save result.

- Verify pre-fix call sites passed plain `set(self._dismissed_agents)` to background persistence workers and that worker
  completion order is not guaranteed (i.e. the lost-update interleaving is real).
- **Audit every `save_dismissed_agents` call site in the repo** for remaining _unstamped_ saves from background threads.
  This is the highest-risk part of the fix: under the new scheme an unstamped save takes a fresh generation and
  supersedes _all_ pending snapshots, so a stale plain-set save from a worker would now be strictly worse than before.
  Confirm all unstamped saves happen on the owning (UI) thread with live data.
- Review new concurrency properties: the module-global lock is now held _across the file write_
  (`_save_dismissed_agents_impl` inside the lock) — check this cannot stall the UI thread noticeably and that the
  generation bookkeeping (`dict[Path, int]` keyed by resolved target file) is correct when the target path changes
  between saves (e.g. tests patching `_DISMISSED_AGENTS_FILE`).
- Check the semantics change where a _failed write_ now also skips the artifact-index sync (previously synced
  unconditionally) — confirm that is desired/harmless.

**2. `TaskQueue.get_running_for_cl` over-matching** (`task_queue.py`) Claim: launch/cleanup tasks carry a real `cl_name`
for display but a custom `dedup_key`; matching on `cl_name` alone spuriously blocked ChangeSpec actions
(sync/status/rebase) while a launch or cleanup ran.

- Already confirmed `submit()` defaults `dedup_key` to `cl_name`, so `dedup_key == cl_name` is the correct "opted into
  per-CL dedup" predicate.
- Verify the claimed pre-fix symptom: find the ChangeSpec-action paths that consult `get_running_for_cl`
  (`task_actions.py`, `_cleanup_tasks.py`) and confirm launch/cleanup submissions use custom dedup keys with a real CL
  name.
- Check no caller _relied_ on the old broader matching (e.g. UI status display of "something running for this CL"), and
  check the corner case of a custom dedup key that _equals_ the CL name.

**3. Delta-refresh drops pending full-history (Tier-2) requests** (`_loading_refresh.py`) Claim: the artifact-delta
refresh's `finally` block cleared `_agents_refresh_pending_full_history`(+reason) without forwarding them into the
rescheduled refresh, downgrading a queued Tier-2 refresh to Tier-1.

- Verify pre-fix code cleared the flags without forwarding, and that the broad-refresh path (which this fix "mirrors")
  does forward them — confirm the two paths are now symmetric.
- Review the asymmetry that `on_complete` is forwarded only when `needs_broad_fallback` while the full-history flags are
  forwarded unconditionally — confirm that is correct, not an oversight.

### Correctness fixes

**4. Per-segment xprompt expansion resets the invocation counter** (`launch_cwd.py`, `multi_agent_xprompt.py`) Claim:
the `segment_extra_env` launch path expands one segment per call; each call created a fresh `count()`, so two
invocations of the same xprompt collided on `xprompt:<name>:0` (one template group, shared name namespace). Fix:
optional `group_counter` param shared across the per-segment calls.

- Verify pre-fix counter reset and what a template-group collision actually breaks downstream (name namespace, grouping
  in the TUI).
- Confirm the single-call branch (no `segment_extra_env`) already produced distinct groups, and that no other caller of
  `expand_multi_agent_xprompts_with_metadata` needs the shared counter.

**5. Rust source-root probe adopts unrelated ancestor `Cargo.toml`** (`version/_sources.py`) Claim: for _wheel_ installs
the ancestor climb from site-packages could find an unrelated Rust project's `Cargo.toml` (venv nested in someone else's
Rust repo) and report its version/git state. Fix: only editable installs may climb from import/distribution locations;
wheels rely on `direct_url` only.

- Verify the claimed "mirrors the python branch" — read the python-source branch and confirm the same gating.
- Enumerate `install_type` values (editable / wheel / anything else such as unknown) and confirm the gate doesn't break
  legitimate resolution for non-wheel non-editable cases.

**6. `sase version` crashes on non-executable git** (`version/_git.py`) Claim: only `FileNotFoundError` was caught; a
git on PATH without exec permission raises `PermissionError`.

- Verify exception ordering correctness (`FileNotFoundError` before `OSError`; `TimeoutExpired` / `CalledProcessError`
  are not `OSError` subclasses so they remain reachable) — this looks right; confirm.

**7. `sase run <single-word>` dead-ends** (`special_cases.py`, `entry.py`) Claim: a sole non-flag token fell through
`handle_run_special_cases` (which required a space in the token) into an argparse `run` namespace nobody dispatched →
"Unknown command: run". Fix: special-case handler accepts a sole non-flag token; `entry.py` gains a real `run` branch
(`run_parsed_prompt`) for anything that still falls through (e.g. a sole token that _is_ a known xprompt name).

- Verify the pre-fix dead end (no `run` branch in `entry.py` main()).
- Verify the parser defines the `run` subcommand with a `prompt` positional and `daemon` flag so `run_parsed_prompt`'s
  `getattr`s are real; verify the no-prompt editor path doesn't duplicate or conflict with an existing editor path in
  the special-case handler.
- Check option-flag shapes still fall through to argparse errors (covered by the new test) and that a known xprompt name
  as the sole token actually reaches `run_parsed_prompt` and dispatches it correctly (the refactored `_dispatch_query`
  handles multi-prompt/alt-split detection identically — confirm pure refactor).

**8. `sase doctor -C <deep-check>` says "unknown check"** (`doctor_handler.py`) Claim: checks listed by `-L` (deep-only
ones) were rejected as unknown when selected without `-D`. Fix: detect deep-only selections and emit a targeted "rerun
with -D/--deep" error.

- Verify `registry.list_deep_checks()` / `list_default_checks()` exist with the assumed semantics and that
  `UnknownCheckSelection` is raised for deep-only selections pre-fix.
- Candidate improvement: a mixed selection (`-C bogus -C tools.optional`) now reports _only_ the deep-only message and
  hides the genuinely-unknown `bogus`. Decide whether reporting both is the objectively better behavior and, if so,
  implement + test.

**9. Coder follow-up `agent_meta.json` records the wrong model when the custom prompt has `%model`/`%m`**
(`run_agent_exec_plan_accept.py`) Claim: when the coder prompt carries its own model directive, the directive supersedes
both picker model and worker lane at launch, but the meta recorded the worker-lane (or picker) model. Fix: extract the
directive's model and pass it as `model_override` to `_update_coder_model_meta`.

- Verify the launch path: the directive in `coder_extra` really does win at launch time (model_prefix is blanked), so
  recording the directive's resolution is correct.
- Already confirmed `model_prefix` is always non-empty at this point, so the directive check is reachable; flag the
  fragile nesting (`model_override` only computed inside `if model_prefix:`) for a possible hardening.
- Candidate improvement: the `except Exception: coder_prompt_model = None` silently reverts to recording the wrong model
  — exactly the original bug — when directive extraction fails even though `has_model_directive` was true. Consider
  tightening (narrow exception, or extract once and reuse for both the prefix-blanking decision and the meta).

**10. Shipped `research_swarm` xprompt references private `#m_codex`/`#m_fable` aliases**
(`default_xprompts/research_swarm.md`) Claim: those aliases exist only in a private user config; on every other install
the tokens leak literally into the prompt and model routing is lost. Fix: inline `%model:codex/gpt-5.5` /
`%m:claude/claude-fable-5`.

- Verify shipped defaults indeed have no `m_codex`/`m_fable` definitions anywhere in-repo, and that the inlined
  directive syntax/model ids resolve in the provider registry.
- Minor consistency check: the file now mixes `%model:` and `%m:` spellings — if these are exact synonyms, consider
  unifying for readability (only if genuinely objective; otherwise leave).

**11. Live Diff drops the legacy `workspace_num=1` → primary mapping** (`file_panel/_diff.py`) Claim: legacy metadata
uses 0 and 1 interchangeably for the primary checkout; runner-side resolvers normalize 1 → 0 but the Live Diff resolver
lost that mapping, so `resolve(1)` returned a managed-clone path.

- Already grounded: the workspace-migration research doc documents `ensure_workspace_checkout` mapping
  `workspace_num == 1` → 0. Verify against the actual runner-side resolver code (not just the doc), and confirm managed
  workspace numbering can never legitimately assign 1 to a non-primary checkout.

## Methodology

1. **Setup**: `just install` (fresh ephemeral workspace), then run the PR's new/changed test files once to establish a
   green baseline.
2. **Parallel verification fan-out**: spawn read-only subagents per bug cluster (1–3 race fixes; 4; 5–6; 7–8; 9–10; 11)
   to trace the _pre-fix_ code at the merge-base and answer each bug's verification questions above, including the
   call-site audits.
3. **Falsification spot-checks** for the highest-risk claims (1, 2, 3, 4, 5, 7): temporarily restore the pre-fix src
   file(s) from `master` in the working tree, run the new regression test to confirm it fails, then restore the branch
   state. This proves the tests actually pin the bugs.
4. **Improvements**: implement only the changes that survive the "objective improvement" bar (candidates flagged inline
   above; the fan-out may surface more, e.g. a missed unstamped `save_dismissed_agents` call site). Each comes with a
   focused test.
5. **Final gate**: run the affected test suites plus `just check`. Leave changes on this branch for the standard sase
   commit flow.

## Out of scope

- Re-running the original 203-commit audit to find _new_ bugs beyond the 11 claims.
- Behavioral redesigns of the touched subsystems (e.g. replacing the snapshot-generation scheme with a different
  persistence model) — only correctness fixes to what the PR ships.

## Report format

Final response: one verdict per bug — **Legitimate?** (bug real pre-fix), **Fix correct?**, **Test pins it?**
(falsification check result where performed), **Improvement applied?** (with file/line refs) — plus the overall
`just check` result.
