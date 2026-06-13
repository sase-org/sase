---
create_time: 2026-06-13 14:41:19
status: done
prompt: sdd/prompts/202606/worker_models.md
---
# Worker Models Plan

## Goal

Make `llm_provider.worker_models` consistently choose worker-lane models from the effective primary provider/model that
actually launched the planning agent, including explicit `%model` directives and temporary primary overrides. Improve
ACE model override and approval UI so users can see and reset the worker default confidently.

## Current Behavior

- `llm_provider.config.get_configured_worker_model_for_primary(primary_provider, primary_model)` already supports exact
  `provider/model`, bare model, and provider fallback.
- `resolve_effective_worker_provider_model()` uses the current effective primary lane, so active primary temporary
  overrides already affect generic `%model:worker` launches when resolved immediately.
- Approved plans currently build follow-up prompts with `%model:worker` when approval does not choose `coder_model`.
  That prompt is reprocessed later by the workflow executor, so `worker` is resolved from the current global primary
  lane, not from the planner agent's recorded provider/model. This loses context for planners launched with an explicit
  `%model` directive and can also drift if overrides change before approval.
- Plan approval notifications already carry the planner's concrete `model` and `llm_provider`; the runner also has the
  same values in `AgentExecContext`.
- The ACE Model Overrides modal shows primary and worker lanes, but the worker config source is only a coarse `config`
  label. The custom approval model picker uses a "Worker model (default)" row that does not display the resolved worker
  model, and selecting it is indistinguishable from canceling, so it cannot reset a previously selected custom coder
  model.

## Implementation Plan

1. Add a shared worker-resolution helper in the Python LLM provider layer.
   - Introduce a small result object such as
     `WorkerModelResolution(provider, model, source, primary_provider, primary_model, matched_key, configured_target)`.
   - Add `resolve_worker_provider_model_for_primary(primary_provider, primary_model, model_tier="large")`.
   - Preserve existing precedence: active worker override, matching `worker_models` entry, then fallback to the supplied
     primary lane.
   - Keep `resolve_effective_worker_provider_model()` as the public current-default helper by having it call the new
     helper with `resolve_effective_default_provider_model()`.
   - Keep the existing `worker` alias behavior for ordinary prompts, but use the new contextual helper where a known
     planner primary context exists.

2. Fix approved-plan handoff model selection.
   - In `run_agent_exec_plan_accept`, derive the default follow-up worker target from `ctx.agent_llm_provider` and
     `ctx.agent_model`.
   - When approval does not specify `coder_model`, build the follow-up prompt with a concrete `%model:<provider/model>`
     prefix from that contextual worker resolution instead of a bare `%model:worker`.
   - Treat an explicit approval `coder_model == "worker"` as the same contextual worker default, so CLI
     `sase plan approve --model worker` behaves predictably.
   - Preserve precedence for custom approval prompt directives: if `coder_prompt` contains `%model` / `%m`, keep
     omitting the generated prefix and record that directive's resolved model.
   - Apply this to normal coder handoffs and the epic/legend follow-up prompts, since they share the same worker-lane
     default path.

3. Keep metadata and display in sync with the actual follow-up model.
   - Update `_update_coder_model_meta` or replace it with a helper that accepts the already-resolved contextual default.
   - Ensure follow-up `agent_meta.json`, prompt-step markers, chat metadata, and final transcript metadata agree with
     the concrete model in the generated prompt.
   - Preserve the existing optimization for explicit `coder_model` equal to the planner model where appropriate, but do
     not skip metadata when contextual worker resolution chooses a different provider/model.

4. Improve ACE Model Overrides support.
   - Use the new resolution result in `TemporaryLLMOverrideModal._lane_state("worker")`.
   - Show a more informative worker source label, for example `config claude/opus` or `config codex`, while keeping
     labels compact.
   - Add coverage that changing the primary temporary override changes the worker row through `worker_models` when no
     worker override is active.
   - Keep this work modal-local and user-initiated; do not add synchronous config/provider work to hot navigation or
     refresh paths.

5. Improve plan approval model picker support.
   - Pass the planner `llm_provider`/`model` from `PlanApprovalModal` into `ApproveOptionsModal`.
   - Render the default coder model as the contextual worker target for that planner, not the current global worker
     default.
   - Make the model picker able to distinguish "choose worker default" from cancel for callers that need it, so users
     can reset from a selected coder model back to the worker default.
   - Keep existing model picker behavior for other callers unless they opt into the distinct default sentinel.

6. Update docs and stale wording.
   - Replace remaining `llm_provider.worker_model` references in `docs/xprompt.md` and `docs/ace.md`.
   - Document that plan follow-up defaults are resolved from the planner agent's concrete provider/model at handoff
     time, while ordinary `%model:worker` prompts still resolve from the current effective worker lane.

## Tests

- Provider resolution:
  - Exact `provider/model`, bare model, and provider key precedence for `resolve_worker_provider_model_for_primary`.
  - Active worker override still wins.
  - Fallback returns the supplied primary lane when no config matches.
  - `resolve_effective_worker_provider_model()` still responds to primary temporary overrides.

- Plan handoff:
  - Planner `ctx=(claude, opus)` plus `worker_models: {"claude/opus": "codex/gpt-5.5"}` produces a coder prompt
    beginning with `%model:codex/gpt-5.5`.
  - Planner `ctx=(codex, o3)` plus provider-level `worker_models: {"codex": "claude/opus"}` produces
    `%model:claude/opus`.
  - No matching config falls back to the planner provider/model.
  - Explicit approval `coder_model` wins.
  - Explicit `coder_model="worker"` uses contextual worker resolution.
  - Custom coder prompt `%model` still wins and suppresses the generated prefix.
  - Epic and legend follow-ups use the same contextual worker default.

- TUI:
  - Model Overrides worker row shows config provenance and changes when primary override changes.
  - Approve Options displays the contextual worker model from the plan notification's planner model.
  - The model picker can reset a previously selected coder model back to worker default.

- Docs/schema:
  - Existing schema test continues to accept `worker_models` and reject legacy `worker_model`.
  - Stale documentation search for `worker_model` is clean except intentional schema rejection tests.

## Verification

After implementation, run focused pytest targets first:

```bash
pytest tests/test_llm_provider_providers.py tests/llm_provider/test_temporary_override.py
pytest tests/test_axe_run_agent_exec_plan_followup_metadata.py tests/test_axe_run_agent_exec_plan_followup_approvals.py tests/test_axe_run_agent_exec_plan_followup_prompt_construction.py
pytest tests/test_approve_options_modal_model.py tests/test_temporary_llm_override_rendering.py tests/test_temporary_llm_override_modal.py tests/test_temporary_llm_override_modal_flows.py
pytest tests/test_config_schema.py
```

Then run the repository-required final check:

```bash
just install
just check
```

## Risks

- Prompt expectations currently assert `%model:worker`; those tests and docs should be updated intentionally because
  concrete contextual prefixes are what preserve the planner primary context.
- Provider metadata/config lookups must stay out of TUI hot paths. The new UI work should run only during modal
  construction or explicit modal actions.
- If a planner has missing provider/model metadata, the implementation should fall back to the existing current
  effective worker helper rather than failing approval.
