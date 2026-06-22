---
create_time: 2026-06-22
updated_time: 2026-06-22
status: research
---

# Specifying a Thinking Level (e.g. `xhigh`) Alongside a Model in xprompts

## Question

Today an xprompt (or any agent prompt) can pin the model/provider with the `%model` directive
(`%model:claude/opus`, `%m:codex/gpt-5.5`, `%m(opus,sonnet)`). Bryan wants to *also* specify a
**thinking level** (a.k.a. reasoning effort — e.g. `xhigh`) when he names that model. How could that
work, given the current directive + provider architecture, and what is the cleanest way to add it?

## Bottom Line

"Thinking level" already has a canonical name across the stack: **effort**, with the level vocabulary
`low | medium | high | xhigh | max`. This is Anthropic's `output_config.effort` parameter, it is what
the verified `claude --help` exposes as `--effort <level>`, and it is the same vocabulary this very
harness uses.

The recommended solution is a **single provider-agnostic `effort` concept, attached to the model spec,
translated per-runtime at the CLI boundary**:

1. **Syntax:** extend the existing `%model` argument with an optional `@<effort>` suffix —
   `%model:claude/opus@xhigh`, `%m:codex/gpt-5.5@high`, fan-out `%m(opus@xhigh,sonnet@low)`. The `@`
   character is *already* permitted by the directive grammar, so **no regex/grammar change is needed**.
   (Optionally add a sibling `%effort` directive for setting effort without re-stating the model.)
2. **Parsing:** split the `@<effort>` suffix off the model token inside `extract_prompt_directives`,
   storing it as a new structured field `PromptDirectives.effort` (and keeping `directives.model`
   clean for display/telemetry/aliasing).
3. **Plumbing:** thread `effort` through `invoke_agent()` into `provider.invoke(..., effort=...)`, and
   give the provider base class a uniform `effort_args(effort) -> list[str]` hook that each provider
   overrides to map the canonical token onto its own CLI surface:
   - **Claude Code:** `--effort <level>` (verified flag).
   - **Codex:** `-c model_reasoning_effort=<level>` (clamp `xhigh`/`max` → `high`).
   - **Antigravity (agy):** no per-call dial — map to a "(Thinking)" model variant, or no-op.
   - Others (qwen, opencode): nearest equivalent, else no-op.

This binds effort to the model exactly as the request is phrased, requires no grammar change, rides the
existing model-resolution + multi-model fan-out + mobile plumbing, and respects the **uniform agent
runtimes** rule (one `effort_args` contract; no `if provider == ...` branching).

A **zero-code interim workaround exists today**: `SASE_LLM_LARGE_ARGS="--effort xhigh"` (or
`SASE_CLAUDE_LARGE_ARGS` / `SASE_CODEX_LARGE_ARGS`) appends arbitrary args to the runtime CLI. But it is
*global* — not per-prompt and not per-model — so it does not satisfy the request.

## How a Model/Provider Is Specified Today

The `%model` directive (alias `%m`) is the only model-selection surface in a prompt.

**1. Parse → `PromptDirectives.model` (a plain string).**
`src/sase/xprompt/_directive_types.py:52` defines the dataclass; `model: str | None` is at line 66.
`%model`/`%m` is a recognized directive (`_KNOWN_DIRECTIVES` line 20, alias `m → model` line 44).
`extract_prompt_directives()` (`src/sase/xprompt/directives.py:164`) collects the argument and stores it
at `directives.model` (built at line 475: `model=expanded_args.get("model") or None`).

**2. Resolve string → `(provider, model)`.**
`invoke_agent()` (`src/sase/llm_provider/_invoke.py:139`) reads `model_override = result_directives.model`,
then calls `resolve_model_provider(model_override)` (`src/sase/llm_provider/registry.py:225`), which:
- runs `resolve_model_alias()` first (so `flash → agy/flash35h`, configured in `sase.yml`
  `llm_provider.model_aliases`),
- splits explicit `provider/model` syntax,
- else maps a bare model name to a provider via plugin metadata,
- else falls back to the default provider.

**3. Invoke the provider with a model *string*.**
`_invoke.py:212` calls `provider.invoke(query, model_tier=..., suppress_output=..., model_override=model_override)`.
**Crucially, only `model_override` (a string) reaches the provider — the full `PromptDirectives` object
does not.** The abstract signature is fixed in `src/sase/llm_provider/base.py:16`.

**4. Provider builds the CLI command.**
- Claude: `src/sase/llm_provider/claude.py:202` builds `base_args = ["claude", "-p", ..., "--model", model_alias, ...]`.
- Codex: `src/sase/llm_provider/codex.py:322` builds `[codex, "exec", "--model", model, ...]`.
Both then append whitespace-split args from `SASE_LLM_*_ARGS` / `SASE_<RUNTIME>_*_ARGS`
(claude.py:215, codex.py:345).

There is **no `%thinking`/`%effort`/`%reasoning` directive anywhere today**, and `PromptDirectives` has
no effort field. The Rust core (`../sase-core`) has no LLM-provider or thinking logic — the provider
abstraction is entirely Python here.

## What "Thinking Level" Means Per Runtime (verified)

This is the asymmetry that shapes the design. "Reasoning effort" is **not** expressed the same way by
every CLI:

| Runtime | Mechanism (verified in this workspace) | Notes |
|---|---|---|
| **Claude Code** | `claude --effort <level>` — *"Effort level for the current session"* | Direct flag. Anthropic's effort vocabulary is `low\|medium\|high\|xhigh\|max`; `xhigh` is Claude Code's own default. |
| **Codex** | `codex -c model_reasoning_effort=<level>` (generic `-c key=value` config override; `codex --help` shows `-c model="o3"` as the example shape) | GPT-5-family efforts are `minimal\|low\|medium\|high`. No `xhigh`/`max` — clamp upward to `high`. |
| **Antigravity (agy)** | No per-call effort flag. Thinking is a **separate model name** — `src/sase/llm_provider/agy.py:274` exposes `"Claude Opus 4.6 (Thinking)" → opus46t`, `"…Sonnet 4.6 (Thinking)" → sonnet46t` | "Effort" here means *which model variant you pick*, not a dial. |
| **qwen / opencode** | Not verified; likely none or model-variant-based | Treat via the uniform mapping (nearest equivalent, else no-op). |

Implication: the SASE layer needs **one canonical effort token** and a **per-provider translation**, not
a single flag passed through verbatim. The `agy` case is the reason translation must be a provider
responsibility — a provider that cannot dial effort maps the request to its closest equivalent (a
thinking model variant) instead of the core branching on runtime.

## Design Options

### Option A — Encode effort in the model token (`@` suffix)
`%model:claude/opus@xhigh`. The grammar already allows `@` in a colon-argument (the colon-arg character
class in `_directive_types.py:16` is `[!a-zA-Z0-9_#/.,()@-]`), so this parses **with no regex change**,
and the paren/fan-out form `%m(opus@xhigh,sonnet@low)` works through the existing comma splitter.

- ✅ Binds effort to the model exactly as the user phrases it; matches the request literally.
- ✅ Zero grammar change; rides multi-model fan-out and the mobile path (`_mobile_agent_launch.py`
  builds `%model:` directives) for free.
- ⚠️ A second `:` is *not* in the char class, so `%model:opus:xhigh` would **not** parse — `@` (or `/`,
  `.`) is the viable in-arg separator. `@` is clearest and unused elsewhere in a model token.

### Option B — Dedicated `%effort` directive (alias e.g. `%think`)
`%model:opus %effort:xhigh`. Add `effort` to `_KNOWN_DIRECTIVES` + an alias.

- ✅ Discoverable, composable (set effort without restating the model; reuse across a multi-model prompt).
- ⚠️ Slightly more surface to document; needs precedence rules if both forms appear.

### Option C — Structured `effort` field threaded to the provider
Independent of A/B: add `PromptDirectives.effort: str | None`, thread it through `invoke_agent()` into a
new `provider.invoke(..., effort=...)` kwarg, and translate per provider. This is the *plumbing* half and
is needed by both A and B.

### Option D — Status quo escape hatch (already works, insufficient)
`SASE_LLM_LARGE_ARGS="--effort xhigh"` appends to the Claude CLI; `SASE_CODEX_LARGE_ARGS="-c model_reasoning_effort=high"`
to Codex. Global only — not per-prompt, not per-model, not in the prompt text. Good for a one-off today;
not a real feature.

## Recommended Solution

**Adopt Option A for syntax + Option C for plumbing, with a canonical effort vocabulary translated
per-provider. Optionally layer Option B (`%effort`) later for ergonomics.**

### 1. Syntax (no grammar change)
Accept an optional `@<effort>` suffix on the `%model`/`%m` argument:

```
%model:claude/opus@xhigh      # provider + model + effort
%m:codex/gpt-5.5@high
%m:opus@max                   # bare model + effort
%m(opus@xhigh,sonnet@low)     # per-variant effort in a fan-out
```

`<effort>` ∈ `low | medium | high | xhigh | max` (canonical SASE vocabulary; superset of all runtimes).

### 2. Parse the suffix into a structured field
- Add `effort: str | None = None` to `PromptDirectives` (`_directive_types.py:52`).
- In `extract_prompt_directives()` (`directives.py`), after computing `expanded_args["model"]`, split a
  trailing `@<token>` off the model value: set `directives.effort` to the validated token and
  `directives.model` to the **clean** model string (so aliasing, display label `_invoke.py:168`, and
  `context.metadata_model` stay clean). Do the split **before** alias resolution so `%model:flash@xhigh`
  → effort `xhigh`, model `flash` → `agy/flash35h`.
- Validate against the canonical set; raise `DirectiveError` on an unknown token (consistent with how
  `%repeat`/`%group` validate).
- (Option B add-on) If a dedicated `%effort` directive is also added, define precedence: explicit
  `%effort` overrides a model-suffix effort.

### 3. Thread effort to the provider (uniform contract)
- `invoke_agent()`: read `effort = result_directives.effort` and pass `effort=effort` into
  `provider.invoke(...)` at `_invoke.py:212`. (Also feed the per-step path in
  `workflow_executor_steps_prompt.py`, which already resolves `effective_directives`.)
- `LLMProvider.invoke()` base signature (`base.py:16`) gains `effort: str | None = None`.
- Add a uniform mapping hook on the base class:

  ```python
  def effort_args(self, effort: str | None) -> list[str]:
      """Translate a canonical effort token into provider CLI args. Default: none."""
      return []
  ```

  Each provider overrides it — **no `if provider == ...` branching anywhere**:
  - `ClaudeCodeProvider.effort_args` → `["--effort", effort]` (append in `_invoke_loop` base_args,
    claude.py:202).
  - `CodexProvider.effort_args` → `["-c", f"model_reasoning_effort={_codex_clamp(effort)}"]` where
    `_codex_clamp` maps `xhigh`/`max` → `high` (append at codex.py:322).
  - `AgyProvider.effort_args` → `[]`, and instead resolve the "(Thinking)" model variant when an effort
    is requested (or leave as a documented no-op initially).
  - qwen/opencode → `[]` until a real mapping exists.

This keeps the runtimes uniform: every provider *accepts* an effort level; each maps it to its own
surface (or its closest equivalent), exactly as the **Uniform Agent Runtimes** gotcha requires.

### 4. Optional niceties
- **Config default:** `llm_provider.default_effort` (and/or per-provider) so a level need not be repeated
  per prompt. Apply when neither the directive nor a temporary override sets one.
- **Temporary override:** `temporary_override.py` could carry an effort alongside provider/model so a
  session-wide default effort is possible (mirrors the existing provider/model override).
- **Mobile:** `mobile_model_directive_value` already emits `%model:` — effort rides for free if the model
  token includes `@<effort>`; add an explicit mobile `effort` field later if desired.

## Implementation Surface (file-by-file)

| File | Change |
|---|---|
| `src/sase/xprompt/_directive_types.py` | Add `effort: str | None` to `PromptDirectives`; (Option B) add `"effort"` to `_KNOWN_DIRECTIVES` + alias. |
| `src/sase/xprompt/directives.py` | Split `@<effort>` off the model arg; validate; set `directives.effort`; keep `directives.model` clean. |
| `src/sase/xprompt/_directive_alt.py` | Ensure multi-model fan-out (`split_prompt_for_models`, `%m(a@x,b@y)`) carries per-variant effort. |
| `src/sase/llm_provider/_invoke.py` | Read `result_directives.effort`; pass `effort=` to `provider.invoke()`. |
| `src/sase/llm_provider/base.py` | Add `effort` kwarg to `invoke()`; add default `effort_args()`. |
| `src/sase/llm_provider/claude.py` | Override `effort_args` → `--effort`; append in `_invoke_loop`. |
| `src/sase/llm_provider/codex.py` | Override `effort_args` → `-c model_reasoning_effort=...` (clamp). |
| `src/sase/llm_provider/agy.py` (+ qwen/opencode) | Map effort to a thinking model variant or no-op. |
| `src/sase/integrations/_mobile_agent_launch.py` | (Optional) accept/forward an effort field. |
| `docs/xprompt.md`, `docs/llms.md` | Document the `@<effort>` syntax and per-runtime mapping. |
| `src/sase/default_config.yml` | (Optional) `llm_provider.default_effort`. |

Tier-2 memory to consult before implementing: `memory/cli_rules.md` (if any new `sase` option is added —
note the long+short option rule from `memory/gotchas.md`) and `memory/generated_skills.md` (the
CLI/skill contract may need regeneration if a CLI surface changes).

## Rust Core Boundary Considerations

Per `memory/rust_core_backend_boundary.md`, behavior other frontends must match belongs in/near
`../sase-core`. The relevant split here:

- **Provider → CLI translation (`effort_args`)** stays **Python** — the LLM-provider invocation layer is
  Python-only and `sase-core` has no provider logic. ✅
- **The canonical effort vocabulary + the "split `@effort` from a model token" algorithm** is a
  cross-frontend contract (the same way the VCS-project completion algorithm is mirrored in Python and
  Rust per the glossary). If the **nvim xprompt LSP** or the **mobile picker** should validate or
  offer completion for effort tokens, define the token list + parse once and mirror it in `sase-core`
  with a shared golden-vector table, exactly like `editor/completion.rs`. If effort stays prompt-text-only
  with no editor completion, a Python-only helper is acceptable initially.

## Open Questions / Verification Before Building

1. **Effort vocabulary per runtime.** Verified: Claude `--effort` exists; Codex uses
   `-c model_reasoning_effort=`. Confirm the *exact accepted level strings* for the installed `claude`
   and `codex` versions, and the right clamp for `xhigh`/`max` on Codex (assume `high`).
2. **`agy` semantics.** Decide whether requesting an effort on Antigravity auto-selects the
   "(Thinking)" model variant, errors, or is a documented no-op. (Lean: map to the thinking variant when
   one exists, else no-op — never branch in core.)
3. **Precedence** if both `%model:...@x` and a future `%effort:y` appear (recommend explicit `%effort`
   wins).
4. **Telemetry/display.** Whether to surface effort in the `[model]` label (`_invoke.py:168`) and in
   `context.metadata_model` — recommend a separate `metadata_effort` field rather than polluting the
   model string.
5. **Validation UX.** Confirm `DirectiveError` is the right failure mode for an unknown effort token
   (consistent with `%repeat`/`%group`).

## Key Code References

- `src/sase/xprompt/_directive_types.py:16` — colon-arg char class (already allows `@`).
- `src/sase/xprompt/_directive_types.py:52,66` — `PromptDirectives`, `model` field.
- `src/sase/xprompt/directives.py:164,475` — directive extraction; where `model` is assembled.
- `src/sase/llm_provider/registry.py:225` — `resolve_model_provider()` + alias resolution.
- `src/sase/llm_provider/_invoke.py:139,212` — model resolution; the single `provider.invoke()` call.
- `src/sase/llm_provider/base.py:16` — abstract `invoke()` signature (where `effort` kwarg + `effort_args` go).
- `src/sase/llm_provider/claude.py:150,202` — Claude model selection + CLI arg construction.
- `src/sase/llm_provider/codex.py:320,322` — Codex model selection + CLI arg construction.
- `src/sase/llm_provider/agy.py:274` — Antigravity "(Thinking)" model variants (the asymmetry).
- `src/sase/integrations/_mobile_agent_launch.py:128` — mobile path builds `%model:` directives.
