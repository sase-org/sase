---
create_time: 2026-06-23 11:20:08
bead_id: sase-55
tier: epic
status: done
prompt: sdd/prompts/202606/xprompt_effort_levels.md
---
# Plan: Reasoning-Effort Levels for XPrompt Model/Provider Selection

## Context

Users want to attach a reasoning-effort level (e.g. `xhigh`) when they pick a model / LLM provider in a prompt, plus a
configurable default effort. Today model selection is a string-only path: `PromptDirectives` carries `model` but no
effort field, `invoke_agent()` forwards only `model_override`, and each provider's CLI builder only knows about model
tier and model override. Effort can currently be forced only through process-wide env escape hatches
(`SASE_CLAUDE_LARGE_ARGS='--effort xhigh'`, `SASE_CODEX_LARGE_ARGS='-c model_reasoning_effort="xhigh"'`) or per-provider
CLI config files — neither is per-prompt, per-fan-out-branch, or visible in the TUI.

Prior research lives in `sdd/research/202606/xprompt_thinking_level_consolidated.md` and informs this plan. This work
delivers four user-facing capabilities:

1. A canonical `%effort:<level>` directive.
2. A `%model:<model>@<level>` (and `%m:opus@xhigh`) suffix shorthand, including per-branch fan-out
   (`%{%m:opus@xhigh | %m:sonnet@low}`).
3. A new `llm_provider.default_effort` config field (honored across all SASE config files).
4. Uniform effort display in the agent metadata panel on the "Agents" tab, as a suffix on the `Model:` field, identical
   across every provider.

It also migrates the user's chezmoi dotfiles off per-provider effort settings onto the new SASE default.

## Design Decisions (apply uniformly across all phases)

- **Public surface = `effort`; internal field = `reasoning_effort`.** The directive, suffix, and config field all spell
  it `effort`; the stored/threaded field is `reasoning_effort` everywhere (`PromptDirectives`, the new
  invocation-options object, `agent_meta.json`, the TUI `Agent` model).
- **Canonical vocabulary** (spelling validated globally; per-provider support decided in the adapter):
  `none, minimal, low, medium, high, xhigh, max`. Define this once as a shared constant and a
  `split_model_effort(model) -> (clean_model, effort | None)` helper that the directive parser, fan-out naming, and
  (mirrored) Rust core all use.
- **No `%e` alias** for `%effort` — `%e` already means `%edit`. `%effort` is the only spelling.
- **Resolution precedence:** explicit per-branch `%effort` / `@effort` **>** `llm_provider.default_effort` config **>**
  nothing (let the runtime use its own default). Centralize this in one helper
  (`resolve_effective_effort(directives) -> (effort | None, explicit: bool)`) reused by invocation and metadata so
  display and behavior never disagree.
- **Explicit vs. default semantics on unsupported providers:** an _explicitly requested_ effort that a provider can't
  honor must raise a clear error (never silently launch at default effort). An effort coming only from the config
  default is best-effort: silently skipped (with a warning) for providers/levels that don't support it, so a global
  default never breaks agy/qwen runs. This is why the resolver tracks an `explicit` flag.
- **Conflict rule:** if both `%model:...@x` and `%effort:y` survive into the same final prompt branch and `x != y`,
  raise `DirectiveError`; equal values are allowed.
- **`model` string stays clean.** Effort is split off before alias/provider resolution; backtick literals
  (`%model:`literal@id`` `) bypass the `@` split for any future ambiguous model id.
- **Rust boundary:** provider CLI translation stays in Python (Python owns the `claude`/`codex`/etc. subprocess
  commands). The directive vocabulary, `@effort` split rule, and `%effort` directive metadata are editor/cross-frontend
  concerns and must be mirrored in `../sase-core` with golden vectors (Phase 5).

## Provider Support Matrix (Phase 3)

| Provider            | Mechanism                                        | Supported levels                  | Reject                             |
| ------------------- | ------------------------------------------------ | --------------------------------- | ---------------------------------- |
| Claude              | `--effort <level>`                               | low, medium, high, xhigh, max     | none, minimal                      |
| Codex               | `-c model_reasoning_effort="<level>"`            | minimal, low, medium, high, xhigh | none, max                          |
| OpenCode            | `--variant <level>` (verify installed CLI first) | verify locally                    | per verification                   |
| Antigravity (`agy`) | none today                                       | —                                 | all (explicit→error, default→skip) |
| Qwen                | none today                                       | —                                 | all (explicit→error, default→skip) |

Each provider appends effort args alongside the existing `SASE_LLM_*_ARGS` / `SASE_<P>_LARGE_ARGS` env escape hatches
(do not remove those).

---

## Phases

Each phase is implemented by a distinct agent and must independently pass `just install` then `just check` (sase repo).
Dependencies are noted; the orchestrator should respect them.

### Phase 1 — Effort vocabulary + directive parsing (xprompt layer)

**Goal:** populate `PromptDirectives.reasoning_effort` from both surfaces while keeping `model` clean. No effect yet on
the actual CLI invocation.

**Scope (`src/sase/xprompt/`):**

- Add a shared effort module/constants: the canonical vocabulary frozenset, a validator, and
  `split_model_effort(model) -> (clean_model, effort | None)` (split only a trailing `@<known-effort>` token; never
  split inside backtick literals).
- `_directive_types.py`: add `reasoning_effort: str | None = None` to `PromptDirectives`; add `"effort"` to
  `_KNOWN_DIRECTIVES` (no alias).
- `directives.py` `extract_prompt_directives()`: read `%effort:<level>` into `reasoning_effort`; apply
  `split_model_effort` to the `%model`/`%m` value, storing the clean model in `directives.model` and the effort in
  `directives.reasoning_effort`; validate spelling (`DirectiveError` on unknown level); enforce the conflict rule
  between `@effort` and `%effort`.
- `_directive_alt.py`: ensure fan-out naming strips `@effort` so generated agent-name suffixes do not include the effort
  token (`_extract_first_model_value`, `_model_value_for_naming`, and the suffix helpers should operate on the clean
  model).
- Because `"effort"` joins `_KNOWN_DIRECTIVES`, `strip_known_directives` and `src/sase/history/prompt_metadata.py` pick
  it up automatically — verify they treat `%effort` like other known directives (stripped from chat history / previews).

**Tests:** `%effort:xhigh` extraction + stripping; `%model:codex/gpt-5.5@xhigh` split into clean model + effort;
`%m(opus@xhigh,...)`/`%{%m:opus@xhigh | %m:sonnet@low}` per-branch effort and clean fan-out names; conflict
(`%model:...@low` + `%effort:xhigh`) raises; unknown level raises; backtick literal bypasses the split.

**Dependencies:** none.

### Phase 2 — `default_effort` config field

**Goal:** a configurable default effort honored across every SASE config file.

**Scope:**

- `config/sase.schema.json`: add `llm_provider.default_effort` (string, `enum` = canonical vocabulary, default `""`
  meaning "no override"). Keep `additionalProperties: false` satisfied.
- `src/sase/default_config.yml`: add `default_effort: ""` under `llm_provider` (shipped default is _unset_ so we impose
  no effort on the general population).
- `src/sase/llm_provider/config.py`: add `get_default_effort() -> str | None` that reads `llm_provider.default_effort`,
  normalizes/validates against the Phase 1 vocabulary, and returns `None` when unset/invalid. Reuse the Phase 1
  vocabulary constant (single source of truth).
- No new merge logic needed — the existing layered merge (`default_config.yml` → plugin defaults →
  `~/.config/sase/sase.yml` → `~/.config/sase/sase_*.yml` overlays → local `./sase.yml`) already covers "all
  configuration files supported by sase."

**Tests:** getter returns the configured value for each config layer; invalid/empty → `None`; mirror the existing
`tests/test_llm_provider_retry_config.py` mocking pattern.

**Dependencies:** Phase 1 (shares the vocabulary constant). Can otherwise proceed in parallel.

### Phase 3 — Invocation threading + provider translation

**Goal:** turn a resolved effort into the right per-run CLI args for each provider.

**Scope (`src/sase/llm_provider/`):**

- `types.py`: add
  `@dataclass(frozen=True) LLMInvocationOptions(reasoning_effort: str | None = None, explicit: bool = False)`.
- Add `resolve_effective_effort(directives) -> (effort | None, explicit)` (explicit from directive, else
  `get_default_effort()` with `explicit=False`, else `None`).
- Thread an `options: LLMInvocationOptions | None = None` keyword param through the full chain:
  `_invoke.py invoke_agent()` → `base.py LLMProvider.invoke()` → `_hookspec.py llm_invoke()` →
  `_plugin_manager.py invoke()` → every provider's `llm_invoke` hookimpl, and through
  `commit_finalizer.py run_commit_finalizer()` so commit/fix follow-ups keep the same effort. Add as keyword-only with a
  `None` default; grep for _all_ `provider.invoke(`/`.invoke(` call sites and pass through (default `None`) so nothing
  breaks.
- Base helper `invocation_option_args(self, options) -> list[str]` (default `[]`); each provider overrides per the
  support matrix and appends the args next to the `SASE_LLM_*_ARGS` handling. Unsupported level: raise when
  `options.explicit`, else skip + warn.
- `invoke_agent()` builds `options` from `resolve_effective_effort(result_directives)` and passes it to
  `provider.invoke()` and `run_commit_finalizer()`.

**Tests:** per-provider command construction (Claude `--effort xhigh`, Codex `-c model_reasoning_effort="xhigh"`,
OpenCode `--variant` once verified); explicit-unsupported raises, default-unsupported skips; effort resolution
precedence (directive beats config default); commit-finalizer preserves effort.

**Dependencies:** Phase 1 (`directives.reasoning_effort`), Phase 2 (`get_default_effort`).

### Phase 4 — Metadata persistence + uniform TUI display

**Goal:** show the effective effort as a uniform suffix on the `Model:` field and persist it.

**Scope:**

- Persist effective effort (reuse `resolve_effective_effort`):
  - `src/sase/axe/run_agent_directives.py` — add `reasoning_effort` to the `agent_meta` dict (alongside
    `model`/`llm_provider`, ~line 221).
  - `src/sase/xprompt/workflow_executor_steps_prompt.py` + `workflow_executor.py` — add `reasoning_effort` to the step
    marker (alongside `model`/`llm_provider`).
- Read it back: `src/sase/ace/tui/models/agent.py` `Agent` dataclass gains `reasoning_effort: str | None = None`;
  `src/sase/ace/tui/models/_loaders/_meta_enrichment_filesystem.py` reads it from `agent_meta.json`.
- Display: `src/sase/ace/tui/widgets/prompt_panel/_helpers.py` `append_model_field()` gains a `reasoning_effort` param
  and appends a uniform suffix after the model (e.g. `Model: CLAUDE(opus) @ xhigh`) regardless of provider; update its
  call sites (`_agent_display_parts.py`, `agent_run_log_modal.py`). Show the suffix only when an effective effort
  exists.

**Tests:** metadata round-trip (`agent_meta.json` write/read, step markers); `append_model_field` suffix rendering for
several providers and the no-effort case; update Agents-tab PNG snapshots via `just test-visual` /
`--sase-update-visual-snapshots` for the intentional `Model:` suffix change.

**Dependencies:** Phase 1, Phase 2, Phase 3 (`resolve_effective_effort`).

### Phase 5 — Rust core parity + editor completion

**Goal:** keep the directive grammar and editor experience consistent across frontends (nvim LSP).

**Scope (linked repo `sase-core` — open it with
`sase workspace open -p sase-core -r "mirror xprompt effort directive/suffix" <N>` and use the printed path; also update
Python wire if a slot field is added):**

- Add `effort` to the Rust directive metadata registry (`crates/sase_core/src/editor/directive.rs`) so `%effort` is a
  recognized directive with completion; add the vocabulary as its argument candidates.
- Add `@effort` completion when the cursor follows a `%model` value (`crates/sase_core/src/editor/completion.rs`).
- Reconcile the directive-argument regex parity: Python's colon-arg class includes `@` but Rust's
  (`agent_launch/mod.rs`) does not. Mirror the canonical vocabulary + `split_model_effort` rule in Rust so the model
  directive value is parsed and effort-stripped identically (clean model used for slot naming). Add a per-slot
  `reasoning_effort` field to `LaunchFanoutSlotWire` (Rust + the Python mirror in `src/sase/core/agent_launch_wire.py`)
  only if needed for naming/display parity — it is optional under `#[serde(default)]` so schema version 1 stays
  compatible.
- Golden-vector parity tests covering `%effort`, `%model:...@effort`, and per-branch fan-out.

**Tests:** Rust unit + parity/golden tests; Python `tests/test_core_agent_launch_wire.py` cases for `%model:opus@xhigh`.
Note: execution already works without this phase (Python parses everything); this phase is grammar/editor parity only.

**Dependencies:** Phase 1 (defines the canonical vocabulary + split rule to mirror). Independent of Phases 3–4.

### Phase 6 — chezmoi migration + docs

**Goal:** move the user off per-provider effort settings onto the SASE default, and document the feature.

**Scope (chezmoi linked repo at `~/.local/share/chezmoi`, edited directly — `workspace.strategy: none`):**

- `home/dot_codex/config.toml`: remove `model_reasoning_effort = "xhigh"`.
- `home/dot_claude/settings.json`: remove the `"CLAUDE_CODE_EFFORT_LEVEL": "xhigh"` env entry.
- `home/dot_config/sase/sase.yml`: add `llm_provider.default_effort: xhigh`.

**Scope (sase repo docs):**

- `docs/xprompt.md`: add `%effort` to the Supported Directives table (~line 968) and document the
  `%model:<model>@<effort>` suffix + per-branch fan-out.
- `docs/llms.md`: document `llm_provider.default_effort`, the provider support matrix, and the resolution precedence.

**Tests/verification:** run `just check` for the sase-repo doc changes; `chezmoi diff`/`chezmoi apply --dry-run` for the
dotfiles. Do **not** edit protected `memory/*.md` files without explicit user approval; if `memory/cli_rules.md` needs
updating, flag it for the user instead.

**Dependencies:** Phases 2 + 3 merged and working (removing the per-provider `xhigh` settings before SASE can inject
effort would temporarily lose the behavior). Independent of Phases 4–5.

## Risks and Mitigations

- **Losing `xhigh` during migration.** Phase 6 strictly after Phases 2+3; verify a real Claude/Codex run injects
  `--effort xhigh` / `-c model_reasoning_effort="xhigh"` from `default_effort: xhigh` before deleting the per-provider
  settings.
- **Hookspec signature break.** Changing the pluggy `llm_invoke` spec requires every hookimpl to add the `options` param
  — update all five providers (and any test/mock provider) together; keyword-only with a `None` default keeps
  non-provider callers safe.
- **Silent no-ops vs. hard errors.** The explicit/default distinction is the mitigation: explicit unsupported → error;
  default unsupported → skip+warn. Keep this logic in one resolver + the base helper, not scattered per provider.
- **Python/Rust grammar drift.** The `@` arg-class divergence already exists; Phase 5 closes it with shared golden
  vectors so editor completion and slot naming match Python parsing.
- **PNG snapshot churn.** The `Model:` suffix shifts cell widths; use the visual suite and update goldens only for the
  intentional change.
- **Backtick-literal models.** `split_model_effort` must not split inside `%model:`...`` ` literals, preserving the
  escape hatch for any future model id containing `@`.
