---
create_time: 2026-06-30 08:49:43
status: done
prompt: sdd/prompts/202606/model_alias_at_prefix.md
---
# Plan: Require `@` in front of model aliases (`%m:@other`, not `%m:other`)

## Goal

Make a model **alias** illegal in a `%model`/`%m` directive unless it is written with a leading `@`. `%m:other`,
`%m:worker`, `%m:#agy` must become `%m:@other`, `%m:@worker`, `%m:@#agy`. Bare _non-alias_ tokens (known models like
`opus`/`sonnet`/`gpt-5.5`, explicit `provider/model` like `claude/opus`, backtick-literal model ids) stay **bare**. This
is a **hard, breaking cutover** — no deprecation window, no back-compat — mirroring the recent breaking keymap change.
The user's chezmoi config is migrated in the same change.

### Confirmed decisions (from Q&A)

- **Q1** Bare alias (no `@`) that matches a real alias → **hard `DirectiveError`** with a migration hint: _"Model
  aliases must be prefixed with @ — did you mean @other?"_.
- **Q2** `@` is required **only** for aliases. The alias set = keys of `llm_provider.model_aliases` **plus** the two
  reserved aliases `worker` and `other`. Everything else stays bare.
- **Q3** For aliases reached through an xprompt ref, the `@` sits **on the directive**: `%model:@#agy`. xprompt _values_
  stay bare alias names (`agy: "agy_flash"`), so `#agy`/`#gem`/`#pro` remain reusable as prose.
- **Q4** Hard breaking cutover. Update all sase tests/docs/internal emitters **and** chezmoi in one change.
- **Q5** The `agy_*` family (`agy_flash`, `agy_pro`, `agy_sonnet`, …) becomes **real aliases**: add them to
  `llm_provider.model_aliases` (in chezmoi) mapping to `agy/<exact display name>`, **and** write the directives as
  `%model:@#agy*`. This also fixes the latent routing bug the `config.model_xprompts` doctor check warns about today.
- **Q6** `@` in front of a **non-alias** (e.g. `%m:@opus`, `%m:@claude/opus`) → **hard `DirectiveError`**. `@` is valid
  _only_ in front of a real alias.

## Core design: `@` is a surface-syntax marker, never part of the resolved token

The cleanest mental model — and the one this plan adopts — is:

> `@` is a **presentation/spelling marker** that means _"the following token is an alias."_ It is **never** part of the
> stored/resolved model string. Internally, model values are always bare (`worker`, `other`, `agy_flash`, `opus`,
> `claude/opus`).

This yields three symmetric boundaries:

1. **Parse boundary** (`extract_prompt_directives`) — _strict_: enforce the `@` rule (Q1/Q6), strip the `@`, store the
   bare token. Existing resolution (`resolve_model_alias` / `resolve_model_provider`) is **unchanged** and keeps
   operating on bare tokens.
2. **Resolution-adjacent consumers** (fan-out naming, runtime-label, suffix, doctor routing) — _lenient_: strip a
   leading `@` before resolving, because the value can still carry `@` when it comes straight from raw branch text or
   the Rust fan-out plan.
3. **Emit boundary** (`format_model_directive_value`) — re-add `@` for aliases (idempotent) so any
   round-tripped/internally-rendered `%model:` directive is spelled correctly and re-parses.

Keeping `@` out of the resolved token means **`resolve_model_alias`/`resolve_model_provider` and the alias-chaining
logic need no changes**, and internal chain steps (`a → b → claude/opus`) are never subject to the `@` rule (only the
user-facing token is checked, once, at the parse boundary).

### Single source of truth for the alias set

Add one helper, e.g. `model_alias_names() -> set[str]` in `src/sase/llm_provider/config.py`, returning
`set(get_model_aliases()) | {"worker", "other"}`. The two reserved names already live in
`src/sase/xprompt/model_completion.py::_RESERVED_MODEL_ALIASES`; promote those names to a shared constant (e.g.
`RESERVED_MODEL_ALIASES` in `config.py`) so the parser, emitter, completion catalog, and doctor check all read one list
and cannot drift (matches the codebase's existing "cannot drift" convention for vocab/keymaps).

## Critical gotcha: the xprompt pattern shields `#` behind `@`

`_XPROMPT_PATTERN` (`src/sase/xprompt/processor.py:56`) only matches `#name` at start-of-string, after whitespace, or
after one of `([{"'`. **`@` is not an allowed preceding character.** So `process_xprompt_references("@#agy")` does
**not** expand `#agy`; it returns `@#agy` verbatim. If left unaddressed, `%model:@#agy` would strip to `#agy` (not an
alias) and Q6 would hard-error — the exact spelling Q3 mandates would be broken.

**Resolution (recommended): strip `@` _before_ xprompt expansion.** In the model-value path, peel the trailing
`@<effort>` (existing `split_model_effort`), then **strip the leading `@`** (recording that it was present), **then**
run xprompt expansion on the now-bare `#agy` so it expands to `agy_flash` normally, **then** validate. This keeps the
global xprompt pattern (and its Rust mirror) untouched — lowest blast radius on unrelated features (`@file` references,
agent mentions).

The lenient consumers must follow the same order: **strip leading `@` → expand `#` → resolve.**

> Alternative considered (not recommended): add `@` to the `_XPROMPT_PATTERN` lookbehind so `@#agy` expands everywhere
> uniformly. Rejected because it perturbs global xprompt/file-ref matching and would need mirroring in the Rust core
> grammar; the localized strip-before-expand is safer.

## Rust Core Backend Boundary

Model-alias resolution is **Python-resident today** (the Rust core only provides editor completion/hover metadata and
fan-out _structural_ splitting; it does not resolve aliases). The `@`-rule is **semantic** validation that requires
knowing the alias set, which is Python config + plugin metadata. Therefore enforcement belongs in Python, alongside the
existing resolution. The Rust core only needs to **tolerate** a leading `@` in a `%model` value syntactically (it
already allows `@` for the `@<effort>` suffix). Boundary tasks are **verify-only** (see Rust section); change Rust only
if a hardcoded bare-alias example or an `@`-intolerant grammar is found.

---

## sase repo changes

### A. Shared helpers (`src/sase/llm_provider/config.py`)

- `RESERVED_MODEL_ALIASES` shared constant (names + descriptions) — single source of truth.
- `model_alias_names() -> set[str]` — `model_aliases` keys ∪ reserved names.
- Keep `resolve_model_alias` / `resolve_model_provider` **unchanged**.

### B. Parse boundary — strict enforcement (`src/sase/xprompt/directives.py`)

In `extract_prompt_directives`, for the `%model` directive only and **not** for backtick-literal model values
(`"model" not in literal_directives`, consistent with how effort-split/expansion are already skipped for literals):

1. After the existing `split_model_effort` (around lines 494–496), **strip a single leading `@`** from the model value,
   recording `model_had_at: bool`, and write the bare value back so the existing generic xprompt-arg expansion (lines
   498–504) expands `#agy → agy_flash` normally.
2. After expansion, before building `PromptDirectives` (the `model=expanded_args.get("model")` at line 625), validate
   against `model_alias_names()`:
   - `model_had_at and token not in aliases` → `DirectiveError` (_"'@{token}' is not a known model alias; @ may only
     prefix a configured alias or the reserved 'worker'/'other'."_) — Q6.
   - `not model_had_at and token in aliases` → `DirectiveError` (_"Model aliases must be prefixed with @ — did you mean
     @{token}?"_) — Q1.
   - otherwise pass through the bare token unchanged.
   - Note ordering with effort: `@other@xhigh` → `split_model_effort` yields (`@other`, `xhigh`), then strip `@` →
     `other` + effort `xhigh`. A lone leading `@` (e.g. `@other`) is **not** treated as an effort delimiter
     (`split_model_effort` returns early when the only `@` is at index 0). Verify these orderings with tests.

Consider extracting the full model-value normalization (effort-split → strip-`@` → expand → validate) into one dedicated
helper used here, so the model directive is handled cohesively rather than interleaved with the generic per-directive
expansion.

### C. Lenient consumers — strip `@` before resolving

These resolve a model value for **naming/labelling/diagnostics**, not as the strict parse boundary, and can receive a
value that still carries `@`. Strip a single leading `@` (then expand `#`, then resolve). Add a tiny shared lenient
helper (e.g. `strip_model_alias_prefix(value)`).

- `src/sase/xprompt/_directive_alt.py`:
  - `_extract_first_model_value` — strip leading `@` from the returned value.
  - `_slot_model_value` — strip leading `@` from `slot.model` (Rust plan may carry it).
  - `_model_value_for_naming` — strip leading `@` **before** `process_xprompt_references` (so `@#agy` → `#agy` →
    `agy_flash`).
  - `_runtime_label_for_model`, `_model_suffix_value` — operate on the stripped value.
  - Net effect: `%{%m:@agy_pro | %m:@agy_flash}` fans out and names correctly.

### D. Emit boundary (`format_model_directive_value`)

Add `format_model_directive_value(value: str) -> str` (in `config.py` or a small emit helper module): returns
`f"@{value}"` when `value` (sans an already-present leading `@`) is in `model_alias_names()`, else returns `value`
unchanged. **Idempotent** (don't double-prefix a value already starting with `@`). Route every internal `%model:`
emitter through it so re-rendered directives re-parse correctly (internal values are stored bare, so re-emission must
re-add `@`):

- `src/sase/bead/work.py`:
  - line 344 hardcoded `"%model:worker"` → `f"%model:{format_model_directive_value('worker')}"` (i.e. `%model:@worker`).
  - lines 342, 355, 418 dynamic `%model:{assignment.model}` / `{plan.land_model}` → wrap value in the helper.
- `src/sase/axe/run_agent_exec_plan_accept.py`:
  - line 143 hardcoded worker fallback → `%model:@worker`.
  - line 121 `f"%model:{coder_model}\n"` → wrap value in the helper.
  - line 138 `%model:{provider}/{model}` is always explicit `provider/model` → no change (helper would no-op anyway).
- `src/sase/integrations/_mobile_agent_launch.py`:
  - line 133 `f"%model:{model_value}"` → wrap value in the helper.

### E. Completion catalog (`src/sase/xprompt/model_completion.py`)

Aliases must be **offered with the `@`** so users insert the correct spelling; bare known models and `provider/model`
stay bare.

- In `_append_alias_entry` (used for both reserved and user aliases), set `value` and `display` to `@{alias}` and keep
  the bare `alias` in the entry's `aliases` match-hint tuple so typing `oth` still matches `@other`.
  `_INLINE_MODEL_VALUE_RE` / `_is_inline_completable` already allow `@`.
- `filter_model_completion_entries` already matches on value-prefix **or** alias-hint-prefix, so both `@o…` and `o…`
  match after the change.
- This payload is what the Rust xprompt LSP materializes, so the editor automatically shows `@other`/`@<alias>` with no
  Rust change.

### F. Doctor check (`src/sase/doctor/checks_config.py::config.model_xprompts`)

Today it warns when a model-preset xprompt expands to an unroutable token, and `_model_preset_tokens` **swallows
`DirectiveError` → `None`** (silently skipping). Under the hard cutover a bare-alias directive now _raises_ at parse
time, so:

- `_model_preset_tokens` should still extract the **now-bare** token for routing (after `@`-strip, `agy_flash` routes
  via the new `model_aliases` entries → check goes green for the migrated chezmoi config).
- **Enhancement (recommended):** instead of silently skipping a preset that raises the new bare-alias `DirectiveError`,
  surface it as a problem with the migration hint ("uses a bare alias; prefix with `@`"). This turns `sase doctor` into
  a migration aid. Keep it provider-neutral.
- Update the doctor tests (see test matrix) so the "routes OK" fixtures use `@` and add a bare-alias-flagged case.

### G. Default xprompts / shipped config / docs (sase repo)

- `src/sase/default_xprompts/old_research_swarm.md:13` `%m:other` → `%m:@other` (`other` is the one reserved alias
  referenced in shipped xprompts). Line 17 `%m:gpt-5.5` is a bare known model → no change. `research_swarm.md` uses
  explicit `provider/model` only → no change.
- Grep `default_config.yml`, `default_xprompts/`, docstrings, and memory/docs for any remaining bare-alias directive
  examples (`%model:worker`, `%m:other`, etc.) and update to `@`. The `directives.py` docstring example
  `%model:agy/flash35l` is `provider/model` → no change.

### H. Tests (sase repo)

New / updated coverage:

- **Parse/resolve** (`tests/test_directives_extract.py`, `tests/test_llm_provider_providers.py`, a new focused test
  module):
  - `%m:@other` resolves identically to the old `%m:other`.
  - `%m:other` (bare alias) raises `DirectiveError` with the Q1 hint.
  - `%m:@worker` resolves to the worker lane; `%m:worker` raises (Q1).
  - `%m:@opus` and `%m:@claude/opus` raise `DirectiveError` (Q6).
  - `%m:opus`, `%m:claude/opus`, backtick-literal `%model:`lit@id`` still work bare.
  - `%m:@other@xhigh` → model `other`, effort `xhigh`.
  - `%m:@#agy` (with an `agy_flash` alias + `#agy → agy_flash` xprompt fixture) resolves to the agy provider — the
    regression guard for the strip-before-expand ordering.
- **Emit** (`format_model_directive_value`): `worker→@worker`, `other→@other`, `opus→opus`, `claude/opus→claude/opus`,
  idempotent on `@worker`.
- **Completion** (`tests/test_xprompt_model_completion.py`): catalog presents `@worker`/`@other`/ `@<user alias>`;
  filter matches both `@oth` and `oth`.
- **Fan-out naming** (`tests/test_directives_split_models*.py`): `%{%m:@agy_pro | %m:@agy_flash}` splits and names
  correctly.
- **Doctor** (`tests/doctor/test_checks_config.py`): "routes OK" fixtures switch to `@` syntax; add a case asserting a
  bare-alias preset is flagged with the migration hint.
- **Mechanical fixture sweep:** every existing test asserting rendered `%model:worker` output now expects
  `%model:@worker`. Known affected files (non-exhaustive; grep `%model:worker`/`%m:worker`/`%m:other` across `tests/` to
  finalize): `tests/test_axe_run_agent_exec_plan_followup_approvals.py`,
  `tests/test_axe_run_agent_exec_plan_followup_model_selection.py`, `tests/test_bead/test_work_rendering.py`,
  `tests/test_bead/test_work_epic_plan.py`, `tests/test_bead/test_cli_work_epic_launch.py`,
  `tests/test_launch_planned_bead_work.py`, `tests/test_axe_run_agent_phases_tags.py`, plus any input fixtures that
  _feed_ bare aliases into the parser (those inputs must also gain `@`).

### I. Rust core (`../sase-core/crates/sase_core`) — verify-only

Open the linked repo via `sase workspace open -p sase-core -r "<reason>" <workspace_num>` and use the printed path.
Verify (change only if a problem is found):

- `editor/directive.rs` (and any model hover/example text): no hardcoded bare-alias example like
  `%model:worker`/`%model:other`; if present, update to the `@` spelling. Alias completion _values_ come from the Python
  catalog payload, so no value change is needed here.
- Fan-out / directive grammar (`alt_directive_re` and the `%model` arg grammar mirrored from Python): confirm a leading
  `@` in a `%model` value parses as an opaque value (it already allows `@` for effort suffixes). The Python lenient
  consumers strip `@` regardless, but the Rust grammar must not reject the token.

---

## chezmoi repo changes (`~/.local/share/chezmoi/`)

All edits in `home/dot_config/sase/sase.yml` unless noted.

### 1. Add the `agy_*` family to `model_aliases` (fixes routing + enables `@`)

Under `llm_provider.model_aliases` (currently only `other: claude/opus`), add an entry per `agy_*` base token referenced
by the `%model` preset xprompts, each mapping to `agy/<exact display name>`:

```yaml
model_aliases:
  other: claude/opus
  agy_flash: agy/Gemini 3.5 Flash (High) # confirmed by existing sase test
  agy_flash_low: agy/<display name>
  agy_flash_mid: agy/<display name>
  agy_flash_high: agy/<display name>
  agy_gptoss: agy/<display name>
  agy_opus: agy/<display name>
  agy_pro: agy/<display name>
  agy_pro_low: agy/<display name>
  agy_sonnet: agy/<display name>
```

The exact `agy` display names are not on disk in an ephemeral workspace — they come from the installed `agy` provider
plugin's runtime metadata. **At implementation time, source them** from the provider metadata (e.g. the
`known_model_names` for provider `agy` in `get_llm_metadata_payload()`, or the `agy` CLI) and map each `agy_*` base
xprompt token to its display name. The `agy_flash → agy/Gemini 3.5 Flash (High)` mapping is confirmed by
`tests/test_llm_provider_providers.py::test_resolve_model_provider_resolves_agy_display_name_alias` and is the anchor
pattern (spaces/parens preserved verbatim). Map exactly the base tokens the config defines (`sase.yml` lines ~103–112).

### 2. Add `@` to every `%model`/`%m` directive whose final token is an alias

`#agy*` tokens now resolve to the new `agy_*` aliases, so their directives need `@`. `#jet`/`#codex` resolve to explicit
`provider/model` and stay bare. Concrete edits in `sase.yml` (lines ~129–153):

| xprompt           | from                                         | to                                             |
| ----------------- | -------------------------------------------- | ---------------------------------------------- |
| `m_agy`           | `%model:#agy`                                | `%model:@#agy`                                 |
| `m_agy_flash`     | `%model:#agy_flash`                          | `%model:@#agy_flash`                           |
| `m_agy_flash_low` | `%model:#agy_flash_low`                      | `%model:@#agy_flash_low`                       |
| `m_agy_flash_mid` | `%model:#agy_flash_mid`                      | `%model:@#agy_flash_mid`                       |
| `m_agy_gptoss`    | `%model:#agy_gptoss`                         | `%model:@#agy_gptoss`                          |
| `m_agy_opus`      | `%model:#agy_opus`                           | `%model:@#agy_opus`                            |
| `m_agy_pro`       | `%model:#agy_pro`                            | `%model:@#agy_pro`                             |
| `m_agy_pro_flash` | `%{%m:#agy_pro \| %m:#agy_flash}`            | `%{%m:@#agy_pro \| %m:@#agy_flash}`            |
| `m_agy_pro_low`   | `%model:#agy_pro_low`                        | `%model:@#agy_pro_low`                         |
| `m_agy_sonnet`    | `%model:#agy_sonnet`                         | `%model:@#agy_sonnet`                          |
| `m_jet_agy`       | `%{%m:#jet \| %m:#agy_pro \| %m:#agy_flash}` | `%{%m:#jet \| %m:@#agy_pro \| %m:@#agy_flash}` |
| `m_swarm`         | `%{%m:opus \| %m:#codex \| %m:#agy}`         | `%{%m:opus \| %m:#codex \| %m:@#agy}`          |

**No change** (final token is a bare known model or explicit `provider/model`): `m_fable` (`claude/claude-fable-5`),
`m_jet` (`#jet → jetski/...`), `m_opus` (`opus`), `m_opus_codex` (`opus`/`#codex`), `m_opus_sonnet` (`opus`/`sonnet`),
`m_qwen` (`qwen3.6-plus`), `m_sonnet` (`sonnet`), `m_spark` (`codex/gpt-5.3-codex-spark`).

The base xprompts (`agy: "agy_flash"`, `agy_flash: "agy_flash"`, …) and the prose shortcuts (`flash: "#agy_flash"`,
`gem: "#agy"`, `gemini: "#agy"`, `pro: "#agy_pro"`) **keep their bare values** — `@` lives only on the `%model`
directive, per Q3. No chezmoi directive references `other`/`worker`, so those need no directive edits.

### 3. Other chezmoi references

Grep the whole chezmoi repo for `%model`/`%m` directives and any alias tokens to confirm nothing else (skills, prompts,
`*.tmpl`, other `sase*.yml`) references a bare alias. The proposed/scratch `sase_plan_fable_xprompt.md` in chezmoi uses
only bare known models → no change.

---

## Edge cases / invariants

- Internal representation of a model is **always bare**; `@` exists only in `%model:` surface text.
- Alias **chaining** is unaffected: only the user-facing token is `@`-checked, once, at parse.
- Backtick-literal models bypass the `@` rule (like they bypass effort-split/expansion).
- `@<effort>` suffix composes: leading `@alias` + trailing `@effort` both work.
- An undefined `#xyz` after `@` (`@#xyz` with no xprompt) will, after strip-before-expand, attempt to expand `#xyz`,
  fail to expand, and then Q6-error on `#xyz` not being an alias — acceptable (misconfiguration surfaced loudly).

## Verification

- `just install` (ephemeral workspace) then `just check` (ruff + mypy + tests + `sase validate`). This change touches
  the model-completion catalog payload and config, which the `sase validate` freshness gate and the doctor check
  exercise — expect to regenerate/verify those.
- Run the directive, completion, doctor, and bead-render test subsets directly for fast iteration.
- Be aware of environment-specific pre-existing failures unrelated to this change: some `llm_provider` `invoke_agent`
  tests can fail purely due to a local dev `default_effort` config, and the full suite can be killed by the sandbox;
  confirm any failure reproduces on a clean checkout before attributing it to this work.
- Manual smoke: `%m:@other`, `%m:other` (expect error), `%m:@opus` (expect error), `#m_agy`/`#m_agy_pro` from chezmoi
  (expect agy routing), `%{%m:@agy_pro | %m:@agy_flash}` naming; `sase doctor -C config.model_xprompts` green after
  chezmoi migration.

## Out of scope

- Moving model-alias resolution into the Rust core (it stays Python; only `@`-tolerance is verified).
- Any deprecation window or back-compat shim (explicitly a hard cutover per Q4).
- Changing the `@<effort>` suffix or `@file` reference syntax.
