---
create_time: 2026-06-24 16:56:54
status: done
prompt: sdd/prompts/202606/model_directive_arg_completion.md
---
# Plan: Auto-completion for the `%model` / `%m` directive's argument values

## Goal

Extend the directive-argument completion that already exists for `%effort:` and `%auto:` so that typing the argument of
the **`%model:` / `%m:`** directive pops a menu of the LLM models (and model aliases) that SASE supports. As with the
existing two, the menu opens automatically as you type (gated by the same directive auto-menu setting), filters by
prefix, accepts a selection by replacing the partial token, and works in **both** front-ends:

1. The **ACE TUI prompt input widget** (Python / Textual).
2. **Neovim**, via the **xprompt LSP server** (Rust, in the `sase-core` linked repo).

## Why this is meaningfully different from `%effort:` / `%auto:` (read first — it reshapes the design)

The previous effort/auto work relied on a **small, fixed vocabulary** (`("none", … , "max")`,
`("plan", "tale", "epic")`) that is identical in Python and Rust and mirrored by a shared constant. Models break every
one of those assumptions, and the design must account for it:

- **The model list is dynamic, not static.** Models are discovered at runtime from installed LLM-provider plugins
  (Claude, Codex, Antigravity/Gemini, Qwen, OpenCode, …) plus user-configured aliases in `sase.yml`. There is **no**
  canonical model list compiled into the Rust core, and there should not be one — the Rust core treats model strings as
  opaque values. So the "shared mirrored constant" parity trick used for effort/auto **does not apply** to models.
- **The single source of truth is the Python LLM registry.** `get_llm_metadata_payload()` (in
  `src/sase/llm_provider/registry.py`) returns the full provider/model metadata. It is `@functools.cache`d,
  side-effect-free, and does **not** probe `PATH` or spawn subprocesses, so it is safe to call on every keystroke during
  an interactive completion refresh.
- **"What is a valid `%model:` value" is narrower than "every string in the registry."** A model directive value
  resolves through `resolve_model_provider()`, which accepts: (a) the **canonical model names** that are keys of
  `model_to_provider_map()` (e.g. `opus`, `sonnet`, `haiku`, `o3`, `o4-mini`, `gpt-5.5`, `qwen3-max`,
  `anthropic/claude-sonnet-4-5`), (b) explicit `provider/model` syntax, (c) the reserved aliases `worker` and `other`,
  and (d) user-configured aliases from `sase.yml`'s `llm_provider.model_aliases`. **Short aliases**
  (`model_short_alias_map()` values such as `fable`, `gpt55`, `mini`, `flash35h`) are _agent-name suffixes_, **not**
  resolvable model values — e.g. `%model:fable` would not resolve, the canonical value is `claude-fable-5`. The menu
  must therefore **insert canonical model names** and only **display** short aliases as hints.
- **Some model names cannot be typed inline.** The arg-token extractor only treats `[A-Za-z0-9_\-=]` as part of an
  argument value. Model names containing `.` (`gpt-5.5`, `qwen3.6-plus`), `/` (`anthropic/claude-sonnet-4-5`), or `@`
  (the effort suffix) need the token boundary widened. Antigravity/Gemini model names contain **spaces and parentheses**
  (`Gemini 3.5 Flash (High)`) and can only be expressed via SASE's backtick-literal form (`` %model:`…` ``); these are
  **not inline-completable** and are out of scope for v1 (see "Scope decisions").

## Background / current state

### Rust core / xprompt LSP — partially wired, returns nothing for `model`

- The directive registry (`crates/sase_core/src/editor/directive.rs`) already has `model` (alias `m`,
  `takes_argument: true`).
- Context detection (`editor/completion.rs`) already classifies `%model:` as a `DirectiveArgument` context, and already
  contains the `@<effort>` redirect: when the cursor sits after an `@` in a `%model:` value it re-routes to the `effort`
  vocabulary (there is even a passing test, `model_at_suffix_completes_effort_vocabulary`).
- **The gap:** `directive_argument_candidates("model")` falls through to the `_ => &[]` arm and returns **no
  candidates**. The Rust LSP has no source for the (Python-owned, dynamic) model list.

### Neovim/LSP dynamic-data mechanism — already established (this is the template for models)

The LSP server is a Rust binary launched by `sase` (`src/sase/integrations/xprompt_lsp.py`). Dynamic, Python-sourced
completion data reaches it **not** via a live connection but via files/env vars prepared at launch:

- **VCS projects** (`#+`): Python `_materialize_vcs_project_catalog()` writes a JSON catalog to disk and exports its
  path via `SASE_XPROMPT_VCS_PROJECT_CATALOG`; the Rust server stores that path in `ServerConfig` and **re-reads the
  JSON fresh on every request** (`load_vcs_project_catalog`). This is exactly the shape the model list needs.

### Python ACE TUI — has the generic `directive_arg` pipeline, but no model source

The four-touch-point `directive_arg` completion pipeline (open → refresh → render → accept) already exists and is
directive-name-agnostic. Adding a directive today is mostly "register its value list." But the model value source is
dynamic and its candidates need richer display (provider grouping, alias hints) and a wider token boundary, so `model`
cannot simply be dropped into the static `_DIRECTIVE_ARGUMENT_VALUES` map — it needs a dedicated, registry-backed
builder.

## Single source of truth (parity strategy for a dynamic list)

Because there is no shared Rust constant, parity is achieved by having **both front-ends derive from one Python
function**, mirroring how `vcs_project_catalog_payload()` is the single source for project completion:

- Add **`build_model_completion_catalog()`** (new module, e.g. `src/sase/xprompt/model_completion.py`, alongside the
  existing `vcs_project_completion.py`). It returns an ordered list of model completion entries, each with:
  - `value` — the canonical string to insert (model name, `provider/model`, reserved alias, or user alias).
  - `display` — what the menu shows (usually the same as `value`).
  - `description` — provider name and/or the short alias hint and/or the alias target (for the panel's dim text).
  - `kind`/`provider` — for grouping/sorting and styling.
  - It pulls from `model_to_provider_map()`, `model_short_alias_map()` (hint only), the reserved `worker`/`other`
    aliases, and `_get_model_aliases()` (user `sase.yml` aliases).
- **TUI** calls this function directly (in-process, cached → fast).
- **LSP/Neovim**: Python materializes the same catalog to JSON at LSP launch and the Rust server reads it per request.

This guarantees the TUI menu and the Neovim menu can never drift, because both come from one function.

## Scope decisions (the "use your judgement on what to load" call)

**Offered (v1):**

- All canonical model names from every **registered** provider plugin (no availability/`PATH` filtering — registry
  enumeration is provider-installation-agnostic and fast), grouped by provider and ordered by autodetect priority
  (Claude first, etc.).
- Each model's **short alias shown as a hint** (e.g. `claude-fable-5  (fable)`), matching the existing model-picker
  modal's presentation — but the inserted text is always the canonical name.
- The reserved aliases **`worker`** and **`other`**, with explanatory descriptions.
- **User-configured aliases** from `sase.yml` `llm_provider.model_aliases` (description shows the resolved target).
- Models/aliases that are inline-typeable, i.e. consist of `[A-Za-z0-9_\-=./@]` (so `gpt-5.5`,
  `anthropic/claude-sonnet-4-5`, and `opus@high` all work — see token-boundary change below).

**Filtering:** case-insensitive prefix match against the candidate's canonical value **and** its short-alias hint, so
typing `fa` surfaces `claude-fable-5`; the inserted text remains the canonical value. (Mirrors how directive-_name_
completion already matches on aliases.)

**Deliberately out of scope for v1 (documented as follow-ups):**

- **Models whose names contain spaces/parentheses** (Antigravity/Gemini). They require backtick-literal syntax and have
  no inline-typeable form (their short aliases are not resolvable values). They remain reachable via the ACE
  model-picker modal. Completing _into_ a backtick literal is a separate, larger feature.
- **`%model(value)` paren-form** completion. Like effort/auto, v1 completes the `:`/`%m:` colon form only.
- Provider-prefixed enumeration beyond what `model_to_provider_map()` already yields (we will not synthesize a
  `provider/` typeahead step in v1, though the canonical `provider/model` opencode entries are offered as-is).

## Design — Python ACE TUI

Model the work on the existing `directive_arg` path; the only genuinely new pieces are the dynamic candidate source, the
richer display, the wider token boundary, and the `@effort` suffix redirect.

### 1. Model candidate builder (`directive_completion.py` + new `model_completion.py`)

- In `model_completion.py`: `build_model_completion_catalog()` as described above (the single source).
- In `directive_completion.py`: special-case `model` inside `build_directive_arg_completion_candidates()` so that when
  the canonical directive is `model` it delegates to a new `build_model_arg_completion_candidates(partial)` which
  filters the catalog by prefix (value + alias hint), builds `CompletionCandidate`s carrying the provider/alias
  description in `DirectiveArgCompletionMetadata`, and computes `shared_extension` the same way the existing builder
  does. `effort`/ `auto` keep their existing static path untouched.

### 2. Token-boundary widening (`directive_completion.py`)

`extract_directive_arg_token_around_cursor()` resolves the canonical directive name _before_ it scans the argument
boundary, so make the per-char predicate **directive-aware**: for `model`, accept the extra characters `.`, `/`, and `@`
in addition to the existing set; for every other directive keep today's stricter boundary. This keeps `%effort:` /
`%auto:` behavior byte-for-byte identical while letting `gpt-5.5`, `anthropic/claude-sonnet-4-5`, and `opus@high` be
recognized as single tokens.

### 3. `@<effort>` suffix completion in the TUI (mirror the Rust redirect)

When the cursor sits after an `@` inside a `%model:` value, complete from the **effort vocabulary** and replace only the
token after the `@` — exactly what the Rust LSP already does (`model_at_suffix_completes_effort_vocabulary`). Implement
this as a small redirect in the model arg path (split the model token on a trailing `@`, and if the cursor is in the
suffix region, hand off to the existing effort candidate list). This is a clearly separable sub-step; if review prefers
a smaller first cut, it can land immediately after the base model-name completion.

### 4. Wiring (mostly already in place)

The `directive_arg` kind already flows through open (`_file_completion_open.py`), refresh
(`_file_completion_refresh.py`), render (`_prompt_input_bar_completion.py`), and the shared accept path. The model case
reuses all of it. The only render tweak is making the value row show the model's provider/alias description (the render
branch already prints `metadata.description`, so populating it is enough; optionally style the provider hint
distinctly).

### 5. Gating

Reuse the existing **`auto_directive_menu`** setting (this is conceptually directive completion). No new config surface.

## Design — Neovim / xprompt LSP (Rust, linked repo)

Follow the **VCS-project precedent** exactly — it is the established way to get dynamic Python data into the Rust LSP.

1. **Python (launch-time materialization):** in `src/sase/integrations/xprompt_lsp.py`, add
   `_materialize_model_catalog()` (sibling of `_materialize_vcs_project_catalog()`) that serializes
   `build_model_completion_catalog()` to a JSON file (e.g. `~/.sase/xprompt_lsp/model_catalog.json`, with a
   `schema_version`) and exports its path via a new env var (e.g. `SASE_XPROMPT_MODEL_CATALOG`). Call it from
   `_prepare_xprompt_lsp_environment()`.
2. **Rust (`ServerConfig`):** add a `model_catalog: Option<PathBuf>` field populated from the env var at
   `initialize`-time, mirroring `vcs_project_catalog`.
3. **Rust (dispatch):** in the `DirectiveArgument` completion path, when `directive_name == "model"`, load the JSON
   catalog fresh (a `load_model_catalog()` sibling of `load_vcs_project_catalog()`) and return its entries as
   candidates, instead of the empty `directive_argument_candidates("model")`. Preserve the existing `@<effort>` redirect
   so `%model:opus@` still routes to the effort vocabulary.
4. **Graceful degradation:** if the env var/file is absent or unparsable (e.g. an LSP launched outside `sase`), return
   an empty list (no candidates) rather than erroring — same failure posture as the VCS-project loader.

This keeps the boundary rule satisfied: the cross-frontend behavior is shared, with the dynamic data owned by Python and
consumed identically by both front-ends.

## Testing

**Python — model catalog source (`model_completion.py`):**

- `build_model_completion_catalog()` includes canonical model names from the registered providers, the reserved
  `worker`/`other` entries, and user `sase.yml` aliases; short aliases appear only as hints, never as inserted values;
  space/paren model names are excluded from the inline-completable set. Use a fixture/monkeypatched registry payload so
  the test is deterministic and independent of installed providers.

**Python — TUI provider (pure logic):**

- Arg-token extraction for `model`: recognizes `%model:`/`%m:` with empty and partial values; correctly spans tokens
  containing `.`, `/`, and `@`; resolves the `m` alias to `model`; does not fire for the bare name or non-directive `%`;
  leaves `%effort:`/`%auto:` boundary behavior unchanged (regression assertions).
- Candidate building: empty partial returns the full inline-completable set; prefix filtering on value and on alias hint
  (`%model:fa` → `claude-fable-5`); case-insensitivity; `shared_extension` extends a unique partial; unknown directive
  still yields nothing.
- `@effort` redirect: `%model:opus@` → full effort vocabulary; `%model:opus@xh` → `xhigh`; replacement covers only the
  post-`@` token.
- Acceptance replaces exactly the partial span with the canonical model value.

**Python — TUI integration (widget):** typing `%model:` opens the value menu and selecting inserts the canonical model;
the menu narrows on typing, closes when leaving the arg region, and is gated by `auto_directive_menu`. Refresh PNG
snapshot coverage for the model value row if the visual suite covers the completion panel.

**Python — LSP materialization:** `_materialize_model_catalog()` writes valid JSON matching the agreed schema and sets
the env var; round-trips the catalog.

**Rust (`sase-core`):** a regression test that, given a materialized model-catalog JSON, `%model:` classifies as
`DirectiveArgument` and the LSP returns the catalog's model candidates (and an empty/partial `%model:` returns the
expected set); plus confirmation the `@effort` redirect still returns the effort vocabulary. A "no catalog file → empty
candidates" test for the degradation path.

## Documentation / housekeeping

- Update the ACE `?` help popup / prompt-input completion docs to mention `%model:` value completion (per the ace
  help-popup-sync convention).
- Add a glossary note that `%model` arguments auto-complete from the live model registry in both the TUI and the Neovim
  LSP (and that short aliases are display hints, not inserted values).
- `src/sase/default_config.yml`: only touched if review decides to split gating into a dedicated
  `auto_directive_arg_menu`/`auto_model_menu` setting (recommendation: reuse `auto_directive_menu`).

## Suggested phasing (so value lands incrementally)

1. **Source of truth:** `build_model_completion_catalog()` + tests (no UI yet).
2. **TUI base:** token-boundary widening + model candidate builder + render hint + tests + help/glossary.
3. **TUI `@effort` suffix:** the redirect + tests (separable; can be folded into phase 2 or deferred one PR).
4. **Neovim/LSP:** Python materialization + Rust `ServerConfig`/dispatch/loader + Rust + Python regression tests.

Each phase is independently shippable; phases 1–3 deliver the full TUI experience even if phase 4 lands later.

## Files expected to change

**Python (this repo):**

- `src/sase/xprompt/model_completion.py` _(new)_ — `build_model_completion_catalog()`, the single source of truth.
- `src/sase/ace/tui/widgets/directive_completion.py` — directive-aware token boundary; model branch in
  `build_directive_arg_completion_candidates()`; `@effort` redirect for `%model:`.
- `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py` — surface provider/alias hint in the value row (likely just
  populating/styling the existing description field).
- `src/sase/integrations/xprompt_lsp.py` — `_materialize_model_catalog()` + new env var wired into
  `_prepare_xprompt_lsp_environment()`.
- ACE `?` help popup source and the glossary — doc sync.
- `src/sase/default_config.yml` — only if a dedicated gating setting is chosen over reusing `auto_directive_menu`.
- Tests under `tests/` for the catalog source, the provider, widget integration, the `@effort` redirect, and LSP
  materialization; PNG snapshots if applicable.

**Rust (`sase-core` linked repo, via the linked-repo workflow):**

- `crates/sase_xprompt_lsp/src/server.rs` — `ServerConfig.model_catalog`, `load_model_catalog()`, and the
  `DirectiveArgument`/`model` dispatch returning catalog candidates (preserving the `@effort` redirect).
- `crates/sase_core/src/editor/…` and/or the LSP test module — regression tests for the model-catalog-backed completion
  and the no-catalog degradation path.

## Out of scope (possible follow-ups)

- Backtick-literal completion for space/paren model names (Antigravity/Gemini).
- `%model(value)` paren-form completion.
- A `provider/` two-step typeahead, or availability-aware filtering (only showing providers whose CLI is on `PATH`).
