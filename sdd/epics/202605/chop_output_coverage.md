---
create_time: 2026-05-12 13:49:40
status: done
prompt: sdd/prompts/202605/chop_output_coverage.md
bead_id: sase-36
tier: epic
---
# Plan: Make every Athena AXE chop produce useful output

## Context

Recent AXE work added per-chop run history and a chop-focused view in the AXE tab. The remaining gap is content quality:
many chops either emit nothing on ordinary no-op cycles or emit only an agent PID, so the AXE tab cannot answer the
operator questions that matter: what did this chop inspect, why did it skip, what did it launch, and what state did it
change?

The Athena config lives in chezmoi at:

- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`

That overlay adds these chop groups on top of the default SASE lumberjacks:

- `run_every`: `sase_pylimit_split`, `sase_fix_just`
- `code_quality`: `sase_recent_bug_audit`, `sase_recent_improvement_audit`
- `refresh_docs`: `sase_refresh_docs`, `sase_core_refresh_docs`, `sase_github_refresh_docs`, `sase_nvim_refresh_docs`,
  `sase_telegram_refresh_docs`
- `github_actions`: `gh_actions_fix`
- `telegram`: `tg_inbound`, `tg_outbound`

Default SASE built-in script chops are still in scope because they are also visible in the same AXE tab and currently
have the same silent-no-op problem:

- `hook_checks`, `mentor_checks`, `workflow_checks`, `pending_checks_poll`, `comment_zombie_checks`,
  `suffix_transforms`, `orphan_cleanup`, `wait_checks`, `cl_submitted_checks`, `stale_running_cleanup`,
  `comment_checks`, `error_digest`, and `pushgateway_cleanup`

## Output contract

Every actual chop run should emit a concise, human-readable operational summary to stdout/stderr, because that is what
AXE persists and renders. The output should be useful for no-op, action, and error paths.

Minimum useful output for every chop:

- chop identity and run scope when the chop starts or completes
- counts of inputs inspected, filtered, skipped, updated, launched, cleaned, sent, or failed
- explicit no-op reason when nothing happens
- names or stable identifiers for the first few affected items, with a cap to avoid log spam
- state marker paths or dedupe keys when those explain future skips
- child agent prompt/agent names or launched PIDs for agent-launching chops

Keep output compact. These chops run often, especially `waits` and `telegram`, so the target is a few lines per no-op
run and a bounded summary plus item details when action occurs.

## Phase 1: SASE core output helpers and built-in script chops

Owner: one SASE repo agent.

Scope:

- Add a small shared helper for chop output formatting in the SASE repo, likely under `src/sase/axe/` or
  `src/sase/scripts/`.
- Update built-in chop scripts and their runner helpers so every default script chop reports no-op and action summaries.
- Prefer returning structured stats from helper functions where practical instead of scraping log text after the fact.
- Preserve current behavior and exit codes; this phase changes observability only.

Likely files:

- `src/sase/scripts/sase_chop_*.py`
- `src/sase/axe/hook_jobs.py`
- `src/sase/axe/check_cycles.py`
- cleanup/check helper modules called by those runners, if they need to return counts
- focused tests under `tests/`

Acceptance criteria:

- Each built-in script chop emits at least one useful line on a no-op run.
- Existing action paths still include item-level details, but now end with a summary.
- Tests cover representative no-op and action output for hook/check/wait/cleanup/digest chops.
- `just install` and focused tests pass, then `just check` before handoff.

## Phase 2: Agent chop launch records and local SASE xprompt workflows

Owner: one SASE repo agent.

Scope:

- Improve the generic agent-chop run log written by `src/sase/axe/chop_runner.py` so an `agent:` chop entry in AXE shows
  more than `Launched agent chop ...`.
- Include the configured chop name, lumberjack, source (`scheduled`/`manual`/`oneshot`), prompt hash, launched PID, and
  a bounded prompt preview.
- If available from launch metadata, include the agent name/workflow label or artifact path so the AXE view can lead
  directly to the visible agent run.
- Update SASE-local xprompt workflows used by Athena agent chops to print meaningful decisions from their internal
  Python/bash steps:
  - `xprompts/pylimit_split.yml`: scanned limits, file count, launched child names, no-offender reason.
  - `xprompts/fix_just.yml`: `fmt-check`, `lint`, and `test` outcomes plus which fixer branches were launched.
  - `xprompts/audit_recent_bugs.yml`: marker path, base selection, commit count, threshold decision, launched agent
    name, marker update.
  - `xprompts/audit_recent_improvements.yml`: same shape as bug audit.
  - `xprompts/refresh_docs.yml`: project, marker path, commit count, threshold decision, launched child names, marker
    update.

Acceptance criteria:

- Manual `sase axe chop run <agent-chop>` produces a useful run log even if the child workflow itself has not finished.
- Each listed xprompt workflow has useful step output for no-op and launch paths.
- Tests cover the generic agent-chop log and at least the xprompt decision logic that can be tested without launching
  real agents.
- `just install` and focused tests pass, then `just check` before handoff.

## Phase 3: Chezmoi `gh_actions_fix` chop output

Owner: one chezmoi repo agent.

Scope:

- Update `~/.local/share/chezmoi/home/bin/executable_sase_chop_gh_actions_fix`.
- Keep the current behavior: inspect configured repos, dedupe by run id/attempt, fetch failed logs, and launch a SASE
  fixer agent.
- Add an end-of-run summary that reports repos configured, repos checked, actionable failures, dedupe skips, non-action
  skips, launch successes, and launch failures.
- For each repo, log a compact line with latest run status/conclusion, run id/attempt, workflow/title when available,
  and the reason for skipping or launching.
- Keep failed-log fallback diagnostics, but cap any printed detail to avoid flooding the AXE tab.
- Extend `tests/bash/gh_actions_fix_chop_test.sh` to assert the new summaries.

Acceptance criteria:

- No repos configured, success latest run, duplicate failed run, new failed attempt, and `gh` command failure each
  produce clear output.
- Existing tests still pass and new output assertions pass.
- `just check` passes in `~/.local/share/chezmoi/`.
- Do not run `chezmoi apply` in this phase unless this phase is explicitly landing the chezmoi change.

## Phase 4: Telegram chop output

Owner: one `../sase-telegram` repo agent.

Scope:

- Update `tg_outbound` and `tg_inbound` to produce concise no-op and action summaries.
- `tg_outbound` should report inactive-user skip, lock-held skip, unsent notification count, sent count, failed count,
  pending action writes, attachment/send failures, and high-water updates.
- `tg_inbound` should report update count, callbacks handled, text/photo/document messages handled, unsupported messages
  skipped, ready-update completions sent, pending actions cleaned, and offset advancement.
- Keep existing `httpx` noise suppressed.
- Avoid logging secrets, full Telegram message bodies, or full notification text. Truncate identifiers and free text.
- Add focused tests around the script-level summary behavior.

Acceptance criteria:

- Both Telegram chops emit a meaningful line on ordinary idle/no-update cycles.
- Action cycles include bounded counts and identifiers without leaking tokens or large message bodies.
- Existing Telegram tests pass, focused new tests pass, and `just check` passes in `../sase-telegram`.

## Phase 5: Config, documentation, and end-to-end verification

Owner: one integration agent. Prerequisites: Phases 1-4 merged or otherwise available in the workspace.

Scope:

- Re-read the effective Athena config and verify every configured chop has a corresponding output-producing path.
- Update SASE docs if the expected chop output contract should be documented for future script/plugin authors.
- Add or update any config comments in `sase_athena.yml` only if needed; avoid churn in unrelated chezmoi config.
- Run the relevant full checks for every touched repo:
  - SASE repo: `just install`, then `just check`
  - chezmoi repo if touched: `just check`
  - `../sase-telegram` if touched: `just check`
- After committed/applied chezmoi changes, run `chezmoi apply --force` as required by repo memory.
- Do a manual smoke pass with selected chops:
  - one built-in no-op script chop
  - one Athena agent chop
  - `gh_actions_fix` with a harmless/faked no-op path if live repos should not be touched
  - `tg_inbound` or `tg_outbound` in a no-op path

Acceptance criteria:

- The AXE tab has useful output for all Athena-visible chops after at least one run.
- No chop produces unbounded output during ordinary no-op cycles.
- No runtime-specific agent logic is introduced; Claude/Gemini/Codex/Qwen/OpenCode remain treated uniformly.
- Documentation and tests make the output contract hard to regress.

## Rollout notes

- Restart AXE after applying config or installed-script changes so the daemon uses the updated code and environment.
- Treat local live state under `~/.sase/axe/lumberjacks/.../chops/...` as runtime output, not source; do not edit it as
  part of implementation.
- Do not modify SASE memory files.
