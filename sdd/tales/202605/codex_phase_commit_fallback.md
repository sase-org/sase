---
create_time: 2026-05-11 22:46:45
status: done
prompt: sdd/prompts/202605/codex_phase_commit_fallback.md
---
# Codex Phase-Agent Commit Stop-Hook Fallback

## Symptom

Phase agents in three recent epics — `sase-30`, `sase-31`, `sase-32` — made file changes, reported success in their bead
notes (and in some cases got their bead closed), but did not produce a commit. The `sase_commit_stop_hook` warning never
reached those agents and the change set is still sitting in their ephemeral workspaces.

## Evidence

- `git -C ../sase_106 status` shows the uncommitted `_axe_dashboard_helpers.py` split + companion test files — exactly
  the work that `sase-31.2 · Phase 2: Fix Pylimit Without Behavioral Changes` describes in its bead `NOTES` field. The
  bead is marked `[CLOSED]` but the work was never committed and never landed in `master`.
- Similar uncommitted phase work survives in `../sase_101`, `../sase_104`, `../sase_105`, `../sase_110`.
- `~/.sase_commit_stop_hook.jsonl` contains **no `script_start` event for runtime `codex` in `sase_106` after 2026-05-11
  11:15** (a `sase-2u.1` run). The sase-31.2 phase agent that produced those file diffs ran later and never reached the
  hook script at all.
- `git log --grep "sase-31.[234]"` returns no results: none of the three closed sase-31 phases produced a commit.
- A previous diagnosis on this same failure mode already exists in this repo at
  `sdd/tales/202605/codex_commit_stop_hook_fallback.md` (status: `wip`, never implemented). It identified the same root
  cause for a different agent on the same day (workspace `sase_106`, again).

The recent `021dc596 fix: dedupe sibling/commit stop hooks across interactive sessions` is a real fix but addresses a
**different** problem: interactive runs without `SASE_AGENT_TIMESTAMP` re-warning every turn. It does not regress phase
agents, and it cannot be the cause here because the hook script is never being invoked for the codex phase agents in
question.

## Root Cause

SASE-launched Codex `exec` sessions do not reliably trigger the user-side Codex `Stop` hook configured in
`~/.codex/hooks.json`. The hook script is the **only** mechanism currently telling Codex to commit; when delivery fails,
Codex sees nothing about its uncommitted changes, returns its final reply, and the bead workflow proceeds to close the
bead.

Why Codex specifically, and why now:

- Claude Code and Gemini deliver Stop hooks in-process; SASE controls and observes them. Both runtimes appear
  consistently in `~/.sase_commit_stop_hook.jsonl` for the same workspaces.
- Codex `exec` (`codex exec --json --dangerously-bypass-approvals-and-sandbox -`), which is what `CodexProvider.invoke`
  in `src/sase/llm_provider/codex.py:239-250` shells out to, relies on the Codex CLI itself to fire the configured
  `Stop` hook. Empirically, that fires inconsistently for non-interactive `exec` invocations — especially after the
  shadow-home setup that SASE uses (`_create_shadow_codex_home` copies `config.toml` but symlinks the rest of
  `~/.codex`, which includes the trust-state for `hooks.json`).
- The closed phase beads above all ran under `codex exec`, and none left a hook-log footprint, while their workspaces
  still hold the uncommitted diffs.

This is the same diagnosis the `codex_commit_stop_hook_fallback` tale reached earlier on 2026-05-11. That tale was
written but never implemented, so the failure mode recurred in `sase-30`, `sase-31`, and `sase-32`.

## Goal

Guarantee that every SASE-launched Codex agent receives the commit-stop-hook message in-band when it returns with
uncommitted changes — without relying on Codex CLI's external Stop hook delivery. Treat the existing Codex CLI hook as a
best-effort path and add a SASE-managed fallback that detects the failure mode and runs one additional Codex turn with
the same commit instruction.

Out of scope:

- Changing Claude or Gemini behavior; their in-process hook delivery already works.
- Changing `sase_commit_stop_hook.py`'s logic. The script is fine. The problem is upstream of it.
- Reworking how bead state transitions ("close") interact with commits. Keep bead lifecycle separate; the fix is purely
  about ensuring the commit warning reaches Codex.

## Design

### Where the fix lives

`src/sase/llm_provider/codex.py`, inside `CodexProvider.invoke` (file currently returns from its inner `while True` loop
at line 314). After a successful subprocess turn finishes — i.e. the agent has produced its final reply, has **not**
been user-interrupted, and `return_code == 0` — add a single SASE-managed commit check before returning `InvokeResult`.

### Behavior

1. Skip the fallback if `SASE_DISABLE_COMMIT_STOP_HOOK` is set, mirroring `sase_commit_stop_hook.main`'s early return.
2. Skip the fallback if the SASE-side dedup marker already exists for this session
   (`/tmp/sase_commit_hook_done_<session_id>`). This means the upstream Codex Stop hook DID fire this session — let it
   own the conversation, do not double-warn.
3. Reuse `sase_commit_stop_hook._get_changed_files(project_dir)` to detect uncommitted changes. If `has_changes` is
   false, return as today.
4. If changes remain, reuse `sase_commit_stop_hook._resolve_commit_skill`,
   `sase_commit_stop_hook._build_commit_instruction_message`, and `sase_commit_stop_hook._build_name_instruction` to
   compose the _exact same_ message the upstream hook would have sent. This avoids drift between hook-delivered and
   fallback-delivered messages.
5. Touch the same dedup marker the hook script uses, so any later Codex Stop hook firing this session won't re-warn.
6. Run **one** more Codex `exec` turn with that instruction appended to the working transcript (the same accumulated
   prompt assembly already used for interrupts in `codex.py:294-300`).
7. Return after that second turn unconditionally. No loop — if the agent still doesn't commit, the next bead-level step
   (or the user) is responsible. We intentionally do not chase the agent indefinitely.

### Why this is safe

- The fallback only runs when the upstream hook didn't, so it cannot double-warn the agent. The dedup-marker check is
  the gate.
- It is a no-op when the worktree is clean, which is the common case.
- It honors the existing kill-switch (`SASE_DISABLE_COMMIT_STOP_HOOK`).
- It does not change Claude/Gemini code paths, and it respects the "uniform runtimes" rule in `memory/short/gotchas.md`
  — Claude/Gemini already get their warning; Codex needs the same guarantee, just delivered differently because its CLI
  hook plumbing is unreliable. The behavior the agent sees is identical.
- It does not depend on Codex hook config trust state, shadow-home symlinks, or `codex exec` internals.

### Helpers to extract

The three helpers above (`_get_changed_files`, `_resolve_commit_skill`, `_build_commit_instruction_message`,
`_build_name_instruction`) live in `src/sase/scripts/sase_commit_stop_hook.py` as private functions. Re-import them from
`sase.scripts.sase_commit_stop_hook` directly rather than duplicating. Promote them to public names (drop the leading
underscore) only if mypy or lint complains — otherwise leave the module shape alone.

The `SASE_BEAD_ID` env var that the hook reads for the "close the bead first" instruction is set by the bead worker
(`sase bead work`) and is already propagated to the Codex subprocess env, so the fallback's message will include the
correct bead ID without any extra plumbing.

### Logging

Append a structured entry to `~/.sase_commit_stop_hook.jsonl` from the fallback path so the diagnostic story is
self-contained. Reuse `sase.scripts.sase_commit_stop_hook._jlog` with `event="codex_fallback_block_emitted"` (and a
matching `event="codex_fallback_skip"` for the no-changes / disabled / dedup paths). This is the same log file the
existing hook writes to, so the user has one place to look.

## Implementation Steps

1. Extract or re-export the four helpers from `src/sase/scripts/sase_commit_stop_hook.py` so they can be imported from
   `src/sase/llm_provider/codex.py` without circular imports. The script module already imports from
   `sase.vcs_provider`, which is fine; codex.py should not import the script's `main` — only the helpers.
2. In `CodexProvider.invoke`, factor the "successful return" branch (currently `lines 311-314`) into a small private
   method or block so the fallback can run before the final `return InvokeResult(...)`.
3. Add `_maybe_run_commit_fallback_turn(self, accumulated_response: str, prompt: str)` that:
   - Returns `None` if disabled, deduped, or worktree clean.
   - Otherwise composes the follow-up prompt (`prompt` + `--- Work So Far ---` + `accumulated_response` + commit
     instruction), invokes `self._run_subprocess` once more, and returns the appended response.
   - Touches the dedup marker before re-invoking subprocess so a racing upstream Codex Stop hook is suppressed.
   - Always logs to `~/.sase_commit_stop_hook.jsonl` via `_jlog`.
4. Add unit tests in `tests/test_llm_provider_codex.py`:
   - **clean worktree**: provider invokes Codex once; no fallback.
   - **dirty worktree, no marker, hook enabled**: provider invokes Codex twice; second prompt contains the changed file
     list and `/sase_git_commit`; dedup marker is created.
   - **dirty worktree, marker already present**: provider invokes Codex once; no fallback (upstream hook already handled
     it).
   - **`SASE_DISABLE_COMMIT_STOP_HOOK=1`**: provider invokes Codex once even with dirty worktree.
   - **one-shot**: if files remain dirty after the second turn, provider returns; it does not invoke a third turn.
   - **bead id propagation**: with `SASE_BEAD_ID=sase-31.2` set, the fallback prompt contains "run
     `sase bead close sase-31.2`".
5. Add a smoke test that imports the helpers from `sase.scripts.sase_commit_stop_hook` so renaming/moving them in the
   future breaks loudly (rather than silently degrading the fallback).
6. Update the existing tale at `sdd/tales/202605/codex_commit_stop_hook_fallback.md` from `wip` to `done` and link this
   plan from it (or close the tale entirely as superseded by this plan).
7. Run `just install && just check`. The visual-snapshot suite is the main flake source; if it fails for unrelated
   reasons, capture and exclude in the report rather than masking.

## Validation

- `pytest tests/test_llm_provider_codex.py tests/test_commit_stop_hook.py -x`.
- `just check`.
- Manual: revive one of the stale phase workspaces (e.g. `../sase_106` for `sase-31.2`) and re-run that phase agent
  under codex; confirm a new entry appears in `~/.sase_commit_stop_hook.jsonl` tagged
  `event="codex_fallback_block_emitted"`, and the agent produces a commit before exiting.

## Implementation Correction

Implemented per `codex_commit_stop_guard.md`. Two corrections to the design in this tale:

- Native hook marker presence (`/tmp/sase_commit_hook_done_<session>`) is diagnostic
  data, NOT a final-clean guarantee. Some Codex runs emit `block_emitted` yet still
  leave dirty worktrees. The shipped fallback therefore does not skip on the native
  marker; it logs whether one was present and runs another commit turn whenever the
  worktree is dirty at provider return.
- One-shot behavior is enforced via a separate per-session fallback marker
  (`sase_codex_commit_fallback_done_<session>`) so the SASE-managed retry never runs
  twice in the same provider invocation. The native marker is touched before the
  follow-up subprocess only when it was absent, to suppress a redundant external
  hook prompt.

## Recovery For The Stale Phase Workspaces

Out of scope for the code fix, but worth noting so it isn't lost: the uncommitted phase work currently sitting in
`sase_101`, `sase_104`, `sase_105`, `sase_106`, `sase_110` should be reviewed and either committed manually or
discarded. Most concerning is `sase_106`, which contains the only existing artifact of `sase-31.2`. Recovery is a
separate task from this plan.
