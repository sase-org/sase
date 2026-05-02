---
create_time: 2026-04-29 17:30:09
status: done
bead_id: sase-1c
prompt: sdd/prompts/202604/temporary_llm_override.md
---
# Plan: Temporary Default LLM Provider/Model Override

## Goal

Add a leader-mode ACE action that temporarily changes SASE's default LLM provider/model for new agent launches. The user
chooses a provider/model and an expiry duration, and can also clear the current temporary override from the same action.

This should feel like a deliberate session-level control, not a permanent config editor:

- It does not edit `~/.config/sase/sase.yml`.
- It applies to future LLM invocations and agent launches while active.
- Explicit prompt directives such as `%model:codex/o3` still win.
- Expired overrides are ignored automatically, even if no TUI instance is running to clean them up.
- The clear action works across TUI restarts and across processes, not only for an override set earlier by the same
  modal.

Recommended default leader chord: `,P` (`leader_mode.keys.temporary_llm_override: "P"`), using "P" as provider/model.

## Product Design

### User Flow

Pressing `,P` opens a compact modal titled **Temporary Model Override**.

If no override is active:

- The first row shows the current default, for example `Default: CLAUDE(opus)` or
  `Default: auto -> CODEX(gpt-5.3-codex)`.
- The primary action is **Set override**.
- The model picker lists known models grouped by provider, with a **Custom...** option for freeform `provider/model`.
- After selecting a model, the user chooses a duration from quick options (`15m`, `30m`, `1h`, `2h`, `4h`,
  `Until cleared`) or enters a custom duration (`45m`, `1h30m`, `90m`).
- Confirm writes the override and shows a notification like `Temporary LLM override: CODEX(o3) for 1h`.

If an override is active:

- The top line becomes an active badge, for example `Active: CODEX(o3) expires in 47m`.
- The modal offers **Change override** and **Clear override**.
- **Clear override** removes the shared override state immediately. It must work even if the active override was created
  by another ACE instance, a previous session, or a future CLI helper.

### Behavior Rules

- Temporary overrides affect defaults only. A prompt-level `%model` directive or an explicit backend `provider_name`
  argument remains higher precedence.
- Provider/model resolution should reuse existing `resolve_model_provider()` rules:
  - `provider/model` selects the provider explicitly.
  - Known model names infer the provider from plugin metadata.
  - Unknown bare model names are accepted but run on the current default provider, matching current `%model` behavior.
- The state file is best-effort self-cleaning: reading an expired override returns `None` and attempts to remove the
  file.
- An `Until cleared` duration is allowed, but the modal should label it plainly as persistent temporary state, not a
  permanent config change.
- Existing `SASE_MODEL_TIER_OVERRIDE` behavior remains independent. A temporary model override takes the concrete model
  path; tier override still applies only when no concrete model override is active.

## Technical Design

Use a new core module, tentatively `src/sase/llm_provider/temporary_override.py`, with a small JSON state file:

```json
{
  "provider": "codex",
  "model": "o3",
  "raw_model": "codex/o3",
  "created_at": 1777470000.0,
  "expires_at": 1777473600.0,
  "source": "ace"
}
```

Suggested public API:

- `TemporaryLLMOverride` dataclass.
- `get_active_temporary_override(now: float | None = None) -> TemporaryLLMOverride | None`.
- `set_temporary_override(raw_model: str, duration_seconds: float | None, *, source: str) -> TemporaryLLMOverride`.
- `clear_temporary_override() -> bool`.
- `parse_override_duration(value: str) -> float | None`.
- `resolve_effective_default_provider_model(model_tier: ModelTier = "large") -> tuple[str, str]`.

State path should live under the existing user SASE state directory convention, preferably `~/.sase/llm_override.json`.
Writes should be atomic: write a temp file next to the target, `fsync`, then `replace`.

## Phases

### Phase 1: Shared Override State

Owner: core LLM provider state only.

Files likely touched:

- `src/sase/llm_provider/temporary_override.py`
- `src/sase/llm_provider/__init__.py`
- new or existing LLM provider tests

Tasks:

1. Add the temporary override dataclass and state-file helpers.
2. Add robust duration parsing for `15m`, `1h`, `1h30m`, `90m`, `2h15m30s`, and `until cleared`.
3. Resolve model input through existing `resolve_model_provider()` and registered provider names.
4. Ignore and best-effort delete expired, malformed, or unreadable override files.
5. Unit test parsing, set/get/clear, expiry, malformed JSON, explicit `provider/model`, known bare models, and unknown
   bare models.

Acceptance:

- Core tests can create temporary override files in an isolated home/state path without touching real user state.
- No invocation path changes yet; this phase only provides the reliable shared primitive.

### Phase 2: Apply Overrides to Provider Resolution and Agent Metadata

Owner: LLM invocation and metadata resolution.

Files likely touched:

- `src/sase/llm_provider/registry.py`
- `src/sase/llm_provider/_invoke.py`
- `src/sase/axe/run_agent_phases.py`
- `src/sase/main/query_handler/_query.py`
- `src/sase/xprompt/workflow_executor_steps_prompt.py`
- focused tests around provider/model metadata and invocation

Tasks:

1. Make `get_default_provider_name()` return the active temporary provider before permanent config/autodetect.
2. In `invoke_agent()`, when there is no prompt `%model` and no explicit `provider_name`, apply the active temporary
   concrete model as `model_override`.
3. Update agent metadata pre-resolution paths so `agent_meta.json`, running markers, plan review badges, and agent rows
   show the actual temporary provider/model for new launches.
4. Preserve precedence: explicit `%model` and explicit `provider_name` beat the temporary override.
5. Add tests covering default invocation with active override, explicit prompt directive precedence, expired override
   ignored, and metadata recording.

Acceptance:

- A temporary override changes the provider and concrete model used by new agent launches.
- Existing `%model` behavior is unchanged.
- No TUI keymap exists yet; tests can use the core API or state file directly.

### Phase 3: ACE Leader Action and Modal

Owner: TUI command path.

Files likely touched:

- `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`
- `src/sase/ace/tui/keymaps/types.py`
- `src/sase/default_config.yml`
- `src/sase/ace/tui/modals/model_picker_modal.py`
- `src/sase/ace/tui/modals/custom_model_input_modal.py`
- new `src/sase/ace/tui/modals/temporary_llm_override_modal.py`
- `src/sase/ace/tui/modals/__init__.py`
- `src/sase/ace/tui/styles.tcss`

Tasks:

1. Add `temporary_llm_override: "P"` to leader-mode defaults and typed keymap defaults.
2. Add leader handling that opens the override modal from any ACE tab.
3. Reuse or lightly generalize the existing model picker and custom model input modal so this feature gets provider
   grouping and custom input without duplicating logic.
4. Add a duration picker/input path. Keep the interaction two or three clear steps rather than one dense form.
5. Implement active-state display and clear/change actions.
6. Style the modal with the existing TUI language: compact bordered modal, provider-colored active badge, aligned
   labels, stable dimensions, no nested cards, no decorative gradients.

Acceptance:

- `,P` opens the modal.
- Setting an override writes the shared state and notifies the user.
- Clearing removes any active shared override, including one created before this TUI session.
- Cancelling leaves the state unchanged.

### Phase 4: Visibility, Help, and Documentation

Owner: discoverability and polish.

Files likely touched:

- `src/sase/ace/tui/widgets/keybinding_footer.py`
- `src/sase/ace/tui/modals/help_modal/bindings.py`
- `docs/ace.md`
- `docs/configuration.md`
- possibly `docs/llms.md`

Tasks:

1. Add the leader footer entry: `,P temporary model`.
2. Add the chord to the help modal on all relevant tab pages.
3. Document the temporary override behavior, precedence, expiry, state file, and clear action.
4. Document that this is separate from permanent `llm_provider.provider` config and `SASE_MODEL_TIER_OVERRIDE`.
5. Include examples: `codex/o3 for 1h`, `sonnet for 30m`, and clearing an active override.

Acceptance:

- The action is discoverable from the leader footer and help modal.
- Docs explain what happens to existing running agents: they keep their current provider/model; only future launches use
  the override.

### Phase 5: End-to-End Tests and Hardening

Owner: integration and quality gate.

Files likely touched:

- `tests/test_keymaps.py`
- `tests/test_keybinding_footer_*.py`
- TUI modal tests, likely a new `tests/test_temporary_llm_override_modal.py`
- LLM provider and agent metadata tests from earlier phases

Tasks:

1. Add keymap coverage ensuring `default_config.yml`, typed keymap defaults, and binding/help metadata stay in sync.
2. Add Textual tests for modal set/change/clear/cancel flows.
3. Add tests for model picker reuse with the new caller.
4. Add integration-ish tests that create a temporary override and verify new agent metadata resolves to that
   provider/model.
5. Run `just install && just check`.

Acceptance:

- `just check` passes.
- Tests cover the key reliability risks: expiry, stale state, malformed state, explicit directive precedence, and TUI
  clear from preexisting state.

## Non-Goals

- Do not modify permanent `sase.yml` provider config from the TUI.
- Do not change models for already-running agents.
- Do not add runtime-specific branches for Claude/Gemini/Codex; use the provider registry uniformly.
- Do not make the override project-local in this pass. The requested behavior is a default SASE provider/model override,
  and SASE defaults are currently user-level unless prompt directives override them.

## Risks and Mitigations

- **Stale state file**: always check `expires_at` on read and delete expired state best-effort.
- **Metadata mismatch**: centralize effective provider/model resolution in one helper and use it wherever agent metadata
  is precomputed.
- **Config cache interaction**: keep temporary state outside `load_merged_config()` so expiry is not hidden by config
  caching.
- **Ambiguous model input**: mirror existing `%model` resolution behavior instead of inventing a second model grammar.
- **Keymap drift**: update `default_config.yml`, typed defaults, footer, help modal, docs, and tests in the same feature
  sequence.
