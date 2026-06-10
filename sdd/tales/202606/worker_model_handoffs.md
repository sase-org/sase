---
create_time: 2026-06-10 09:22:21
status: done
prompt: sdd/prompts/202606/worker_model_handoffs.md
---
# Plan: Route Plan-Implementation Handoffs Through the Worker Model Lane

## Background

The recently added worker-model lane (`llm_provider.worker_model` config + the reserved `worker` model alias +
worker-role temporary overrides) currently drives only the **phase agents** launched by `sase bead work <epic_id>`. The
plan-approval handoff in `handle_plan_marker` (`src/sase/axe/run_agent_exec_plan.py:393-405`) still inherits the
**planner's** concrete launch model for every follow-up agent (coder, `bd/new_epic`, `bd/new_legend`):

```python
if plan_result.coder_model:
    model_prefix = f"%model:{plan_result.coder_model}\n"
elif ctx.agent_model:
    inherited_model = ctx.agent_model
    if ctx.agent_llm_provider and not inherited_model.startswith(f"{ctx.agent_llm_provider}/"):
        inherited_model = f"{ctx.agent_llm_provider}/{inherited_model}"
    model_prefix = f"%model:{inherited_model}\n"
else:
    model_prefix = ""
```

Because `extract_directives_and_write_meta` (`src/sase/axe/run_agent_directives.py:122-127`) **always** resolves a
concrete `(provider, model)` at launch (explicit directive or the effective default), the `elif ctx.agent_model:` branch
is effectively always taken — every coder/epic/legend follow-up today runs on the planner's model.

The provider-qualification in that branch was added by `~/.sase/plans/202606/plan_handoff_provider_drop.md`. That plan
is now **obsolete**: instead of preserving the planner's provider+model pair, the handoff should hand both the provider
AND the model over to the worker lane. (The orthogonal `_invoke.py` fallback `logger.warning` from that plan stays — it
remains useful diagnostics for any unresolvable `%model` override.)

The target model-lane design after this change:

| Agent                                                                                                                        | Lane                                                                                                |
| ---------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Planner agents (interactive, legend epic-planning `%epic` segments)                                                          | default lane (or explicit user `%model`)                                                            |
| Coder agents implementing an approved plan                                                                                   | **worker lane** (approval-dialog picker wins)                                                       |
| `bd/new_epic` / `bd/new_legend` follow-up (creates the epic bead + phase beads and runs `sase bead work` to launch the epic) | **worker lane** (picker wins)                                                                       |
| Phase agents working a phase bead                                                                                            | worker lane, **phase bead `model` field wins** (already implemented)                                |
| Land agents (`bd/land_epic` / `bd/land_legend`)                                                                              | default lane (incl. temporary overrides); epic/legend bead `model` field wins (already implemented) |

## Goals

1. Coder follow-up agents spawned on plan approval use the worker model — both provider and model.
2. The `bd/new_epic`/`bd/new_legend` follow-up agent (epic/legend bead creation + `sase bead work` kickoff) also uses
   the worker model.
3. Verify (no behavior change): phase agents keep using `%model:worker` with the phase bead's `model` field taking
   priority; the epic/legend **land** agent keeps using the default/overridden-default model (no `%model` directive)
   with the epic/legend bead's `model` field taking priority.
4. Follow-up agent metadata (TUI display + final chat metadata) reflects the model the follow-up actually runs with,
   instead of the inherited planner model.
5. TUI approval surfaces stop advertising "Same as planner" for the default coder model.

## Non-Goals

- No changes to `sase bead work` rendering (`src/sase/bead/work.py`) or the Rust epic/legend work-plan builder
  (`../sase-core/crates/sase_core/src/bead/work.rs`): phase-model priority (`assignment.model` ← phase bead `model`) and
  land-model behavior (`land_model` ← epic/legend bead `model`, otherwise no directive ⇒ default lane) are already
  correct and covered by `tests/test_bead/test_work_rendering.py` and Rust test
  `epic_work_plan_copies_phase_and_land_models`.
- No changes to worker-lane resolution itself (`resolve_effective_worker_provider_model`, the `worker` alias
  short-circuit in `src/sase/llm_provider/config.py:77-83`).
- No model registration / picker-inventory changes; no new CLI options.

## Changes

### 1. `src/sase/axe/run_agent_exec_plan.py` — worker-lane handoff (the core fix)

Replace the planner-model inheritance in `handle_plan_marker` with the worker alias:

```python
# Use coder_model override from plan approval if provided,
# otherwise hand the implementation off to the worker lane.
if plan_result.coder_model:
    model_prefix = f"%model:{plan_result.coder_model}\n"
else:
    model_prefix = "%model:worker\n"
```

- `%model:worker` is late-binding: the reserved alias resolves at follow-up invoke time via `resolve_model_provider()` →
  `resolve_model_alias("worker")` → the provider-qualified `"<provider>/<model>"` string
  (`src/sase/llm_provider/config.py:77-83`), so **both provider and model** route to the worker lane and pick up any
  worker override active when the coder actually starts. This is the same mechanism phase agents already use, and the
  explicit `provider/model` syntax is the proven-correct resolution path.
- Worker-lane fallback semantics apply: with no `worker_model` configured and no worker override, the lane falls through
  to the effective default (`resolve_effective_worker_provider_model`), NOT to the planner's model.
- The same `model_prefix` feeds the `bd/new_epic` / `bd/new_legend` follow-up prompt (line 494), satisfying Goal 2.
- Unchanged precedence: an explicit approval-dialog coder model (`plan_result.coder_model`) wins, and a custom coder
  prompt carrying its own `%model`/`%m` directive still suppresses the prefix via the existing `has_model_directive`
  guard (lines 541-547).
- The land agents are launched by `render_multi_prompt`/`render_legend_multi_prompt`, not by `handle_plan_marker`, so
  they are unaffected (Goal 3).

### 2. `src/sase/axe/run_agent_exec_plan.py` — follow-up `agent_meta.json` accuracy

`create_followup_artifacts` inherits `model`/`llm_provider` from the planner's meta, and `_update_coder_model_meta`
(lines 92-107) only patches them when a picker model was chosen. With the worker default, the coder/epic/legend
follow-up meta would keep showing the planner's model while actually running on the worker model (exactly the
meta-vs-routing mismatch the 4w incident exposed).

Extend `_update_coder_model_meta` so that when `plan_result.coder_model` is unset, it resolves the worker lane
(`resolve_model_provider("worker")`) and writes the resolved `model` + `llm_provider` to the follow-up meta. The
existing picker branch is unchanged. This keeps the TUI agent rows AND the final chat metadata
(`_final_transcript_model_provider` reads the follow-up meta first, `src/sase/axe/run_agent_exec_finalize.py:318-326`)
truthful. Update the docstring to describe both branches.

### 3. TUI labels — stop advertising "Same as planner"

- `src/sase/ace/tui/modals/approve_options_modal.py:_model_display_label`: for `coder_model is None`, resolve the worker
  lane (`resolve_effective_worker_provider_model()`) and return a worker-tagged label, e.g. `"Worker — CLAUDE(opus)"`
  (reusing `format_provider_model_label`), instead of `"Same as planner"`.
- `src/sase/ace/tui/modals/model_picker_modal.py:_build_model_rows`: rename the default-sentinel option label from
  `"Same as planner"` to `"Worker model (default)"` (selection semantics unchanged: returns `None` ⇒ no explicit coder
  model ⇒ worker lane). The docstrings referencing the old label are updated too. The temporary-override modal uses
  `include_default_option=False`, so it is unaffected.

### 4. Tests

`tests/test_axe_run_agent_exec_plan_followup_prompt_construction.py` (+ shared helper stays as-is):

- Update the inheritance-era expectations: `test_coder_prompt_includes_model_when_set`,
  `test_coder_prompt_preserves_unregistered_provider_model_pair`,
  `test_coder_prompt_uses_bare_model_when_provider_missing`, `test_coder_prompt_does_not_double_prefix_qualified_model`,
  `test_coder_prompt_no_model_when_none`, `test_epic_prompt_includes_model_when_set`,
  `test_epic_prompt_no_model_when_none`, `test_coder_prompt_without_model_inherits`, and the `%model:anthropic/opus`
  prefix assertions inside the resume-env tests now all expect the prompt to start with `%model:worker\n` (regardless of
  `agent_model`/`agent_llm_provider`).
- New: approval-dialog precedence — `PlanApprovalResult(..., coder_model="sonnet")` ⇒ prompt starts with
  `%model:sonnet\n` (and the worker prefix is absent).
- Keep passing unchanged: `test_coder_prompt_model_override_skips_inherited` (custom coder prompt with its own `%m`).
- New meta assertions (via the already-mocked `update_meta_field`): with no picker model, the follow-up meta gets the
  resolved worker `model` and `llm_provider` (patch `resolve_model_provider` so tests don't read the developer's real
  `~/.config/sase/sase.yml`); with a picker model, existing behavior.

TUI tests:

- `tests/test_approve_options_modal_model.py`: the no-coder-model display test asserts the new worker label (patch
  `resolve_effective_worker_provider_model`).
- `tests/test_model_picker_modal.py`: default-option label assertions updated to the new label; selection still returns
  `None`.

No changes to `tests/test_bead/test_work_rendering.py` — it already pins Goal 3's behavior (phase model priority, worker
default for phases, land segment model-free unless the bead sets one).

## Design Notes / Accepted Edge Cases

- **Planners with explicit models no longer propagate them to coders.** E.g. a planner launched with
  `%m:claude/claude-fable-5` hands off to a worker-lane coder. This is the requested behavior; the approval dialog's
  model picker remains the escape hatch for one-off coder model choices.
- **Phase agents that (atypically) submit a plan**: `bd/work_phase_bead` instructs direct implementation, but if a phase
  agent does run `sase plan`, the `%approve` auto-approval hands its coder to the worker lane even when the phase bead
  set a custom model. The bead `model` field governs the phase agent itself (already enforced at launch); after handoff
  there is no reliable way to distinguish a bead-set model from an already-resolved `worker` alias in `ctx.agent_model`.
  Accepted as consistent with "implementation = worker lane".
- **Land agents that find leftover work**: `bd/land_epic` plans remaining work via `/sase_plan`; the land agent itself
  keeps the default lane, while its auto-approved remaining-work coder now uses the worker lane — consistent with the
  same rule.
- **Meta resolves eagerly, prompt resolves lazily**: the meta written at handoff time could theoretically drift from the
  `%model:worker` resolution at invoke time if a worker override changes in between (seconds); accepted, mirrors the
  phase-agent launch pattern.

## Verification

- `just install`, then `just check` (lint + mypy + full test suite).
- Manual trace: approve a plan without picking a coder model and confirm the follow-up prompt artifact starts with
  `%model:worker`, the coder's `agent_meta.json` records the worker provider/model, and `prompt_step_main.json` shows
  the worker provider doing the routing.
