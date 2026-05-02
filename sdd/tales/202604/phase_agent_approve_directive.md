---
create_time: 2026-04-26 01:29:27
status: done
prompt: sdd/prompts/202604/phase_agent_approve_directive.md
---
# Plan: Auto-Approve Directive on Phase Agent Prompts

## Motivation

`sase bead work <epic_id>` automatically launches a wave-partitioned multi-prompt of phase agents (one per open
`IssueType.PHASE` child) followed by a final land agent. These agents run unattended — there is no human at a terminal
to approve their plan-review gates, mentor sign-offs, or other interactive approvals.

Today, `render_multi_prompt()` (`src/sase/bead/work.py:159`) emits per-phase segments of the form:

```
%name:<phase_bead_id>
%w:<dep1>,<dep2>          # optional, only if dependencies exist
#bd/work_phase_bead:<phase_bead_id>
```

Without `%approve`, each phase agent stalls at its first approval gate, defeating the point of `sase bead work`
automation. We want phase agents to skip those gates.

## What `%approve` Already Does

The directive is already wired end-to-end:

- Parsed by `extract_prompt_directives()` (`src/sase/xprompt/directives.py:317`), populating `PromptDirectives.approve`
  (`src/sase/xprompt/_directive_types.py:51`; short alias `%a`).
- `run_agent_phases.py:132` writes `agent_meta["approve"] = True` when the directive is present.
- `run_agent_runner.py:479` sets `SASE_AGENT_AUTO_APPROVE=1` for the agent process.
- `is_auto_approve_active()` (`src/sase/main/plan_approve_handler.py:16`) consults both the env var and
  `agent_meta.json`, so plan-review utilities and other gates bypass user prompting.
- The Agents-tab toggle in `src/sase/ace/tui/actions/agents/_approve.py` already rewrites the same
  `agent_meta["approve"]` field, so the rendered indicator and per-agent toggle stay coherent.

So this is purely an injection change in the multi-prompt renderer — no parser, no runner, no TUI work.

## Change

Update `render_multi_prompt()` in `src/sase/bead/work.py:159-187` to emit `%approve` on every phase segment, immediately
after `%name` (and before any `%w` line, to keep the snapshot stable and read top-down):

```
%name:<phase_bead_id>
%approve
%w:<deps>                # if dependencies exist
#bd/work_phase_bead:<phase_bead_id>
```

The land segment is a separate question (see Open Questions); default plan is **also emit `%approve` on the land
segment**, since the land agent is no more attended than the phase agents are, and it issues commits/PRs that
historically need plan-review acceptance.

## Files

| File                           | Change                                                                                                                                                                                                                                                                          |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/bead/work.py`        | In `render_multi_prompt()`, append `%approve` line in each phase loop iteration (and the land segment, pending the Open Questions decision).                                                                                                                                    |
| `tests/test_bead/test_work.py` | Update the two `render_multi_prompt` snapshots (`TestDiamondPlan.test_diamond_render_snapshot` at line ~132, and the snapshot in `TestIndependentFanOut` at line ~289) to include the new `%approve` line for every phase segment (and for the land segment if we go that way). |

No new tests are required — the existing snapshots are the right level of coverage since the directive parser, runtime,
and TUI behavior already have their own test suites.

## Behavior Verification

- `just check` (lint + tests) covers the snapshot delta.
- Manual: `sase bead work <some_test_epic> --dry-run` and confirm the printed multi-prompt contains `%approve` on every
  phase segment.

## Open Questions / Judgment Calls

1. **Land segment**: include `%approve` or not? Argues _for_: the land agent is equally unattended and runs the
   auto-merge / cleanup. Argues _against_: landing is the riskier step and a human may want a final review gate.
   **Default recommendation: include it.** The user can flip this in one line if they disagree before implementation.
2. **Configurability**: should this be a CLI flag on `sase bead work` (e.g. `--no-approve`) rather than hard-coded?
   Probably not yet — YAGNI. Add only when a user actually wants the opposite behavior.
3. **Does `%approve` interact with `%plan`?** No — phase agents do not get `%plan` today, and we are not adding it.
   Independent flags.

## Out of Scope

- Adding any new directive or extending `PromptDirectives`.
- Changing what `%approve` does at runtime.
- Updating the `bd/work_phase_bead` or `bd/land_epic` xprompt bodies in `src/sase/default_config.yml`.
- Configurability of the directive emission (see Open Question #2).
