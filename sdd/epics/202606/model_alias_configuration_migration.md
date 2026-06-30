---
create_time: 2026-06-30 09:22:59
status: done
prompt: sdd/prompts/202606/model_alias_configuration_migration.md
bead_id: sase-5d
tier: epic
---
# Model Alias Configuration Migration Plan

## Goal

Replace the old model-default and worker-lane configuration surfaces with model aliases:

- `llm_provider.model_aliases.default` becomes the configured default model target used when a prompt has no explicit
  `%model` / `%m` directive.
- `@<provider>_coder` becomes the model directive emitted for coder follow-ups from plans created by that provider.
- `@coder`, `@epic_creator`, `@epic_lander`, and `@phase_worker` are special implicit aliases with documented fallback
  behavior.
- `worker_models`, `@worker`, and reserved `@other` behavior are removed.
- Alias values can reference other aliases with `@<alias_name>`.

This is a breaking configuration migration. Each phase below is intended to be implemented by a distinct agent.

## Current State

The current implementation has these relevant seams:

- `sase.llm_provider.config` owns configured model aliases, the reserved `worker` / `other` aliases, and `worker_models`
  matching.
- `sase.llm_provider.temporary_override` owns primary and worker "lanes" and exposes
  `resolve_effective_default_provider_model()` plus worker-specific resolver APIs.
- Default model metadata is resolved in several launch/display paths, including `run_agent_directives`,
  `main/query_handler/_query.py`, `workflow_executor_steps_prompt.py`, and `invoke_agent`.
- Accepted plan follow-ups prepend a `%model` directive in `run_agent_exec_plan_accept.py`.
- `sase bead work` emits `%model:@worker` for phase agents without explicit bead models and omits a model directive for
  land agents without explicit land models.
- Model completions currently include reserved `@worker` and `@other`.
- The public config schema still accepts `llm_provider.worker_models`.
- Bryan's chezmoi SASE config currently uses `worker_models` and `model_aliases.other`.

There is no live `default_model` field in the current schema or Python code, but the migration should still reject and
document it as obsolete if any stale user config contains it.

## Design

### Alias Semantics

Keep `llm_provider.model_aliases` as the single user-configurable model indirection map. Values remain strings and may
be:

- a known bare model name, such as `opus`;
- an explicit provider/model path, such as `codex/gpt-5.5`;
- a nested provider-local path, such as `opencode/anthropic/claude-sonnet-4-5`;
- another alias reference, such as `@default` or `@coder`.

Alias resolution should follow chains, detect cycles, and keep the existing "bad config cannot crash launches" behavior.
Unknown `@alias` references should be surfaced by doctor/config validation diagnostics; runtime should fail closed
rather than recurse forever.

Implicit special aliases:

- `default`: if configured, resolves through that configured target; otherwise resolves to the current configured or
  autodetected provider's tier default. An active primary temporary override should still win for "new launch default"
  behavior unless the prompt has an explicit `%model` directive.
- `coder`: defaults to `@default`.
- `<provider>_coder`: defaults to `@coder` for every registered LLM provider name.
- `epic_creator`: defaults to `@default`.
- `epic_lander`: defaults to `@default`.
- `phase_worker`: defaults to `@default`.

`worker` and `other` should stop being implicit or reserved. If a user explicitly defines aliases with those names, they
can behave like ordinary configured aliases, but SASE should no longer ship, document, complete, or special-case them.

### Launch Semantics

Precedence for normal launches:

1. explicit `%model` / `%m` directive;
2. explicit caller `provider_name` / model override arguments where those exist;
3. active primary temporary override;
4. `@default`;
5. existing provider/tier default fallback.

Coder follow-up prompts:

- If approval selected an explicit follow-up model, keep using it.
- If the custom coder prompt contains its own `%model` / `%m`, keep letting that win.
- Otherwise prepend `%model:@<planner_provider>_coder` when planner provider metadata exists.
- If planner provider metadata is missing, prepend `%model:@coder`.

Epic/bead role prompts:

- Plan approval with kind `epic` should default its `#bd/new_epic` follow-up to `%model:@epic_creator`.
- Phase agents created by `sase bead work` without explicit per-bead models should use `%model:@phase_worker`.
- Epic land agents without explicit land models should use `%model:@epic_lander`.
- Existing explicit model choices and per-bead/land model metadata still win.
- Legend paths should be audited carefully. Do not invent a `legend_*` alias unless a path is actually launching one of
  the requested roles.

### UI Semantics

The primary temporary override remains: it is still useful as a temporary override of default launch behavior.

The worker lane should be retired from the UI and public API unless a phase proves a compatibility reason to keep a
hidden reader. Remove or de-emphasize:

- worker row in the ACE Model Overrides modal;
- worker override top-bar chip;
- worker override state writes;
- docs for `~/.sase/llm_worker_override.json`.

The plan approval model picker should rename "Worker model (default)" to language that matches the new role default,
such as "Follow-up default", and its display should resolve through the alias that will actually be emitted.

## Phase 1 - Core Alias Resolver and Default Launch Semantics

Owner focus: `sase.llm_provider` plus the launch metadata call sites.

Tasks:

1. Replace `RESERVED_MODEL_ALIASES` with a centralized alias policy that exposes:
   - configured alias names;
   - fixed special aliases;
   - provider-specific `<provider>_coder` aliases from registered provider names;
   - formatting helpers for `%model:@alias`.
2. Update `resolve_model_alias()` so alias values can reference `@alias` targets, with cycle/depth protection.
3. Add helpers for role aliases, for example:
   - `default_model_alias_name() -> "default"`;
   - `coder_model_alias_for_provider(provider) -> "<provider>_coder"`;
   - `role_model_directive_value("phase_worker") -> "@phase_worker"`.
4. Make no-directive launches resolve through `@default` consistently in:
   - `invoke_agent`;
   - `run_agent_directives`;
   - `main/query_handler/_query.py`;
   - `workflow_executor_steps_prompt.py`;
   - any other metadata resolver found by search.
5. Preserve active primary temporary override behavior for no-directive launches.
6. Remove `worker_models` lookup helpers and worker-resolver exports from the core path, or leave thin deprecated stubs
   only if needed temporarily by later phases.
7. Add focused tests for:
   - `default` configured to explicit provider/model;
   - absent `default` falling back to existing provider tier default;
   - `coder -> @default` and `<provider>_coder -> @coder` fallback chains;
   - alias-to-alias references using `@`;
   - cycles and unknown `@alias` references;
   - `worker` / `other` no longer being implicit alias names.

Exit criteria:

- No prompt with no `%model` can bypass the new default alias resolver.
- `@worker` and `@other` are invalid unless explicitly configured as normal aliases.
- Focused LLM provider and directive tests pass.

## Phase 2 - Parser, Completion, Doctor, and Schema Migration

Owner focus: user-facing config/directive surfaces.

Tasks:

1. Update directive validation to use the new implicit/configured alias policy.
2. Update `%model` completion catalogs:
   - include `@default`, `@coder`, all registered `@<provider>_coder` aliases, `@epic_creator`, `@epic_lander`, and
     `@phase_worker`;
   - keep matching bare typed hints such as `codex_coder` while inserting `@codex_coder`;
   - remove reserved `@worker` and `@other` entries.
3. Update doctor config checks so:
   - stale `llm_provider.worker_models` and `llm_provider.default_model` get actionable migration diagnostics;
   - alias values that reference unknown `@alias` names are reported;
   - configured xprompt model directives using removed implicit aliases are reported with replacements.
4. Update `config/sase.schema.json`:
   - remove `worker_models`;
   - ensure `default_model` is rejected and covered by a regression test;
   - keep `model_aliases` as a string map because `@alias` references are still strings.
5. Update parser, completion, doctor, and schema tests.
6. Check the Rust xprompt LSP/core behavior:
   - the existing catalog format should still work;
   - add or update a regression only if new alias entries expose a Rust completion gap.

Exit criteria:

- `worker_models` is no longer accepted by the public schema.
- `%model:` completion advertises the new aliases and no reserved worker/other aliases.
- Doctor provides migration guidance instead of silent fallback.

## Phase 3 - Plan Follow-up and Coder Routing

Owner focus: accepted-plan follow-ups and approval UI.

Tasks:

1. Update `run_agent_exec_plan_accept.py` so default coder follow-ups emit:
   - `%model:@claude_coder` for planner provider `claude`;
   - `%model:@codex_coder` for planner provider `codex`;
   - `%model:@agy_coder` for planner provider `agy`;
   - equivalent aliases for all other registered providers;
   - `%model:@coder` only when planner provider metadata is missing.
2. Keep explicit approval picker models and custom coder prompt `%model` directives as higher precedence.
3. Update follow-up metadata recording so it resolves and records the alias target actually used.
4. Rename approval modal/model picker wording away from "Worker model (default)" to alias-driven follow-up/default
   wording.
5. Update CLI and TUI plan approval tests:
   - default coder prompt includes provider-specific coder alias;
   - explicit picker model still wins;
   - custom prompt model still suppresses the generated prefix;
   - metadata reflects the resolved alias target;
   - question/retry continuation prompts keep the follow-up prompt's model directive.
6. Update docs for `sase plan approve`, plan approval modals, and `#coder` handoff behavior.

Exit criteria:

- A Claude-authored plan launches its coder with `%model:@claude_coder` unless the user picked a model explicitly.
- No accepted-plan coder path emits `%model:@worker`.

## Phase 4 - Bead/Epic Role Aliases and Worker-Lane Retirement

Owner focus: bead work rendering, epic follow-ups, and temporary override UI cleanup.

Tasks:

1. Update epic approval follow-ups:
   - `#bd/new_epic` defaults to `%model:@epic_creator`;
   - explicit approval picker model still wins;
   - legend-related launch paths are audited and only changed when they launch one of the requested roles.
2. Update `sase bead work` rendering:
   - phase agents without explicit model metadata emit `%model:@phase_worker`;
   - epic land agents without explicit land model metadata emit `%model:@epic_lander`;
   - explicit phase and land model metadata still wins;
   - legend land behavior is left unchanged unless it is intentionally mapped by design during this phase.
3. Remove worker-lane resolver usage from bead and epic code.
4. Retire worker temporary override UX:
   - remove worker row and `w` / `W` actions from the ACE Model Overrides modal;
   - remove worker chip rendering from the top-bar indicator;
   - remove or quarantine tests for `llm_worker_override.json` depending on the chosen compatibility stance.
5. Update bead, epic, temporary override, and rendering tests.
6. Update bead/epic docs.

Exit criteria:

- No shipped prompt renderer emits `%model:@worker`.
- Phase and land agents use the new role aliases when no explicit model is set.
- User-facing UI no longer describes a worker lane as a supported model-selection concept.

## Phase 5 - Documentation, Chezmoi Config, and Final Cleanup

Owner focus: global docs, examples, config migration, and broad validation.

Tasks:

1. Update docs and examples:
   - `docs/llms.md`;
   - `docs/configuration.md`;
   - `docs/xprompt.md`;
   - `docs/ace.md`;
   - `docs/beads.md`;
   - CLI references and blog/examples that mention `worker_models`, `@worker`, or reserved `@other`.
2. Update `src/sase/default_config.yml`:
   - remove commented `worker_models`;
   - document alias-based defaults and role aliases in comments.
3. Update Bryan's chezmoi `sase.yml`:
   - remove `llm_provider.worker_models`;
   - remove `model_aliases.other`;
   - preserve existing `agy_*` aliases;
   - migrate current worker routing to provider coder aliases:
     - `claude_coder: codex/gpt-5.5`;
     - `codex_coder: claude/opus`;
   - add explicit role aliases only where useful for readability, for example `coder: "@default"`,
     `epic_creator: "@default"`, `epic_lander: "@default"`, and `phase_worker: "@default"`.
   - if an actual `default_model` value is discovered in any layered config, move that value to `model_aliases.default`;
     otherwise leave `default` implicit.
4. Run repository-wide searches to ensure remaining `worker_models`, `%model:@worker`, `%model:@other`, and
   reserved-alias references are either removed or intentionally historical.
5. Regenerate generated skill files only if a changed source file under `src/sase/xprompts/skills/` requires it.
6. Run final validation:
   - `just install` if the workspace was not freshly installed;
   - focused tests from phases 1-4;
   - `just check`;
   - `cargo fmt --check` / focused Rust tests only if Rust core changed;
   - `git diff --check` in every touched repo.

Exit criteria:

- Main repo tests and checks pass.
- Chezmoi config no longer uses removed fields or removed implicit aliases.
- No active docs advertise `worker_models`, reserved `@worker`, or reserved `@other`.

## Cross-Phase Risks

- Alias default resolution touches runtime behavior and metadata display. Phase 1 must keep actual invocation and
  recorded metadata in sync.
- Removing the worker lane affects many tests and docs. Avoid mixing that UI cleanup into Phase 1 so core alias behavior
  can stabilize first.
- Provider-specific aliases depend on provider names from plugin metadata. Use lazy imports or adapter helpers to avoid
  import cycles in `llm_provider.config`.
- Alias references such as `@default` in config values must not be confused with `%model:<model>@<effort>` suffixes.
- Historical SDD files can retain old text. Active docs, default xprompts, tests, and config should be migrated.

## Suggested Agent Assignment

1. Agent A: Phase 1, commit core alias resolver/default launch behavior.
2. Agent B: Phase 2, commit parser/completion/doctor/schema migration.
3. Agent C: Phase 3, commit plan approval coder routing and approval UI wording.
4. Agent D: Phase 4, commit bead/epic aliases and worker-lane UI retirement.
5. Agent E: Phase 5, commit docs, chezmoi config, searches, and final validation.
