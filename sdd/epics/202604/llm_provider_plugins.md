---
create_time: 2026-04-24 14:02:00
status: done
bead_id: sase-n
prompt: sdd/prompts/202604/llm_provider_plugins.md
---
# LLM Provider Plugin Migration (pluggy)

## Goal

Convert sase's LLM provider layer from a hand-rolled registry into a pluggy-based plugin system that mirrors the
existing VCS plugin architecture (`src/sase/vcs_provider/`). At the end of this work:

- Claude, Codex, and Gemini remain built-in plugins inside the sase repo, registered via
  `[project.entry-points."sase_llm"]` in `pyproject.toml`.
- Jetski lives entirely in `../sase-google` as an external plugin. It ships with its own provider code, tests, metadata,
  CLI/skill deploy path, and retry defaults — sase itself has zero jetski-specific code.
- Third parties can publish new LLM provider plugins (e.g. sase-openai) without modifying sase core, exactly like
  sase-github and sase-google ship VCS plugins today.
- All observable behavior of existing commands (`sase`, `sase init-skills`, agent runs, retry flow, interrupt handling,
  chat history, telemetry) is preserved.

## Why now

The architecture analogue already exists — sase_100's VCS layer uses pluggy + entry points with two live external
plugins (sase-github, sase-google) as consumers. Mirroring that pattern for LLM providers removes the last
hard-coded-list chokepoint in the provider layer (`ALL_PROVIDERS`, `_MODEL_TO_PROVIDER`, `_PROVIDER_MODEL_RE`,
`_register_builtin_providers`, `PROVIDER_CONTEXT`, `_SKILL_DEPLOY_SUBPATH`, `cli_status` color map, `_BUILT_IN_DEFAULTS`
retry table), and specifically unblocks moving jetski out of the open-source sase repo into sase-google where
Google-internal concerns belong.

## Non-goals

- Changing the `invoke_agent()` public API or the `LLMProvider` ABC method signatures. The existing callers in 40+ files
  (TUI, agents, workflows, axe, notifications, ...) must keep working untouched.
- Changing preprocessing, postprocessing, telemetry, chat history, interrupt handling, or retry semantics. Only
  dispatch/discovery/metadata moves.
- Introducing a new plugin manifest format. Reuse `importlib.metadata` entry-points like the VCS layer already does.
- Rewriting `_subprocess.py`. All providers will keep importing its helpers regardless of which package they live in
  (sase-google can import from `sase.llm_provider._subprocess` exactly like it already imports from
  `sase.vcs_provider._command_runner`).

## Reference architecture (VCS analogue)

The migration copies the shape of:

- `src/sase/vcs_provider/_hookspec.py` — pluggy `hookspec` / `hookimpl` markers and `VCSHookSpec` class with
  `firstresult=True` methods.
- `src/sase/vcs_provider/_plugin_manager.py` — `VCSPluginManager(VCSProvider)` wraps a `pluggy.PluginManager` and
  delegates every ABC method to the corresponding `vcs_*` hook, raising `NotImplementedError` when no plugin returns a
  result.
- `src/sase/vcs_provider/_registry.py` — builds the PM once, iterates
  `importlib.metadata.entry_points(group="sase_vcs")`, and hands back a `VCSPluginManager` via `get_vcs_provider(cwd)`.
- `pyproject.toml` `[project.entry-points."sase_vcs"]` / `"sase_workspace"` declarations for built-in plugins, mirrored
  by external packages (sase-github, sase-google) that declare their own entries under the same group.

The LLM migration will introduce a `sase_llm` entry-point group and mirror each of the files above under
`src/sase/llm_provider/`.

---

## Phases

Each phase is self-contained: the test suite (`just check` in every touched repo) must pass before the phase can be
signed off, and `sase` / `sase init-skills` / agent invocation must keep working end-to-end. Phases are sized so that a
distinct agent instance can pick one up with only the plan and the current tree as context.

### Phase 1 — Foundation: hookspec + plugin manager, zero behavior change

**Scope.** Introduce the pluggy plumbing in parallel with the existing registry. Nothing uses it yet.

**Create:**

- `src/sase/llm_provider/_hookspec.py`
  - `hookspec = pluggy.HookspecMarker("sase_llm")`, `hookimpl = pluggy.HookimplMarker("sase_llm")`.
  - `class LLMHookSpec` with `firstresult=True` specs. Initial surface:
    - Core dispatch: `llm_invoke(prompt, model_tier, suppress_output, model_override) -> InvokeResult`
    - Model naming: `llm_resolve_model_name(model_tier) -> str`
    - Provider identity (used by dispatch + metadata consumers in later phases): `llm_provider_name() -> str` (the
      entry-point-style key, e.g. `"claude"`).
    - Leave room for (but don't add yet) later metadata hooks — they land in Phase 3.
- `src/sase/llm_provider/_plugin_manager.py`
  - `LLMPluginManager(LLMProvider)` that wraps a `pluggy.PluginManager` configured against a single provider plugin
    instance. `invoke()` and `resolve_model_name()` delegate to the corresponding hooks, raising `NotImplementedError`
    when pluggy returns `None` (same pattern as `VCSPluginManager._call_or_raise`).
- Minimal unit tests under `tests/llm_provider/test_plugin_manager.py` exercising the wrapper with a fake `@hookimpl`
  plugin class.

**Do not touch:** `registry.py`, existing provider classes, `pyproject.toml` entry points, callers. The existing
`_REGISTRY` dict must still power `get_provider()` unchanged at the end of Phase 1.

**Exit criteria.**

- `just check` passes in sase.
- `pluggy` is already a declared dependency (confirmed in `pyproject.toml` line 15) so no dependency changes.
- Running `sase` / `sase init-skills` behaves identically to master.

### Phase 2 — Convert the four in-tree providers to pluggy + entry points

**Scope.** Replace `_REGISTRY` and `_register_builtin_providers` with entry-point-based discovery. All four existing
providers (claude, codex, gemini, jetski) ship as built-in entry points under `sase_llm` in the sase repo. Jetski stays
in sase for this phase — it moves out in Phase 4.

**Changes:**

- Add `@hookimpl`-decorated hook methods to each provider class. The simplest shape: keep `invoke()` /
  `resolve_model_name()` as the canonical implementation, and add thin `llm_invoke()` / `llm_resolve_model_name()` /
  `llm_provider_name()` hook methods that either alias or call the canonical methods. This lets the provider classes
  continue to satisfy the `LLMProvider` ABC for any code path that still constructs them directly during the migration
  window.
- Rewrite `src/sase/llm_provider/registry.py`:
  - Delete `_REGISTRY`, `register_provider`, `_register_builtin_providers`, and the module-import side effect.
  - New `_find_plugin_class(name)` walks `importlib.metadata.entry_points( group="sase_llm")` (mirroring
    `vcs_provider._registry._find_plugin_class`).
  - New `_create_provider_for(name)` builds a fresh `pluggy.PluginManager`, registers the plugin instance, and returns
    an `LLMPluginManager`.
  - `get_provider(name)` keeps its signature and return type (`LLMProvider`) but returns an `LLMPluginManager` under the
    hood.
  - `get_default_provider_name()` keeps its current auto-detect priority (`claude → codex → jetski → gemini`) for now;
    Phase 3 will make this plugin-driven.
  - Keep `register_provider` exported from `llm_provider/__init__.py` as a compatibility shim that raises a clear error
    ("LLM providers are now registered via `sase_llm` entry points — see CONTRIBUTING") **or** simply remove it if no
    in-tree caller uses it (audit — a quick grep in Phase 1 planning shows only `registry.py` itself uses
    `register_provider`, so removal is preferred per AGENTS.md "don't add compatibility shims").
- Update `pyproject.toml`:
  ```toml
  [project.entry-points."sase_llm"]
  claude = "sase.llm_provider.claude:ClaudeCodeProvider"
  codex  = "sase.llm_provider.codex:CodexProvider"
  gemini = "sase.llm_provider.gemini:GeminiProvider"
  jetski = "sase.llm_provider.jetski:JetskiProvider"
  ```
- Update tests that poked at `_REGISTRY` or `register_provider` directly (`tests/test_llm_provider_core.py` especially).
  Prefer using pluggy fixtures that register a fake plugin for isolated tests.

**Exit criteria.**

- `just check` passes.
- `sase -m opus "hello"`, `sase -m gemini-2.5-pro "hello"`, etc. continue to dispatch to the right provider (manual
  smoke — provider auto-detection and `%model` override still work).
- No file in the repo references `_REGISTRY` or `register_provider`.

### Phase 3 — Generalize provider metadata via hooks

**Scope.** Remove every remaining hardcoded provider list / table from sase core so that jetski can live entirely
outside sase in Phase 4. This is the largest behavioral-surface phase.

**Hook additions in `LLMHookSpec`** (all `firstresult=True`, all optional — dispatch helpers fall back to sane defaults
when a plugin doesn't implement them):

- `llm_known_model_names() -> list[str]` — replaces the per-provider branch of `_MODEL_TO_PROVIDER` in `registry.py`. A
  merged {model → provider_name} map is built by iterating plugins.
- `llm_skill_template_context() -> dict[str, str]` — replaces the `PROVIDER_CONTEXT` dict in `init_skills_handler.py`
  (keys: `provider_name`, `provider_tool_name`, `provider_native_ask_tool`).
- `llm_skill_deploy_subpath() -> str | None` — replaces the `_SKILL_DEPLOY_SUBPATH` dict; `None` means "use the default
  `.{name}`".
- `llm_cli_status_color() -> str | None` — replaces the hardcoded jetski entry in `src/sase/agents/cli_status.py`.
- `llm_autodetect_priority() -> int | None` — used by `get_default_provider_name()` to order CLI-presence
  auto-detection. Built-ins declare priorities that match the current order (claude=0, codex=10, jetski=20, gemini=30).
  Plugins that don't declare a priority aren't considered for auto-detect.
- `llm_autodetect_cli_name() -> str | None` — the binary name passed to `shutil.which` during auto-detection (e.g.
  `"claude"`, `"jetski-cli"`).
- `llm_default_retry_config() -> ProviderRetryConfig | None` — replaces `_BUILT_IN_DEFAULTS` in `retry_config.py`.

**Call-site refactors (all inside sase core):**

- `registry.py`: build `_MODEL_TO_PROVIDER` and the provider-name regex dynamically from the aggregated
  `llm_known_model_names()` results. Cache the PM across calls.
- `main/init_skills_handler.py`: replace `ALL_PROVIDERS`, `PROVIDER_CONTEXT`, and `_SKILL_DEPLOY_SUBPATH` with a helper
  that walks the entry points and asks each plugin for its metadata. `_get_target_providers(True)` now returns "all
  discovered provider names". Keep the chezmoi deploy path logic — only the subpath source changes.
- `agents/cli_status.py`: build the color map from plugins (with a fallback color for plugins that don't declare one).
- `llm_provider/retry_config.py`: `_BUILT_IN_DEFAULTS` becomes a function that aggregates `llm_default_retry_config()`
  across registered plugins. Tests that assert Claude's "Prompt is too long" default keep passing — the built-in Claude
  plugin declares it.

**Implementation note.** Build one shared `pluggy.PluginManager` factory (`_build_llm_pm()`) in `_registry.py` and
memoize it so the `init_skills_handler`, `cli_status`, `retry_config`, and dispatch paths all consult the same PM. Don't
scatter ad-hoc PM construction.

**Exit criteria.**

- `just check` passes.
- `grep -rn "jetski" src/sase/` returns only `src/sase/llm_provider/jetski.py`. All other mentions (init_skills_handler,
  cli_status, registry, retry_config, default_config.yml documentation) now route through plugin metadata.
- `sase init-skills` still produces identical `SKILL.md` content for each of the four providers as before (compare
  outputs before/after).

### Phase 4 — Extract jetski to sase-google

**Scope.** Physically move the jetski provider to sase-google and remove every jetski-specific trace from sase.

**Changes in sase_100:**

- Delete `src/sase/llm_provider/jetski.py`.
- Delete `tests/test_llm_provider_jetski.py`.
- Remove the `jetski = "sase.llm_provider.jetski:JetskiProvider"` line from `pyproject.toml`'s `sase_llm` entry-points
  block.
- Remove the `llm_provider.retry.jetski` documentation stanza (if any) from `src/sase/default_config.yml` — Phase 3 made
  it metadata-driven, but a documentation comment may still live there.
- Remove the `TODO(open-question-*)` comments that referenced jetski from anywhere they leaked into shared code.
- Update `memory/short/gotchas.md` and `memory/long/external_repos.md` to note that jetski is now provided by
  sase-google.

**Changes in ../sase-google:**

- New module `src/sase_google/llm_jetski/provider.py` (or similar) containing the `JetskiProvider` class. Imports:
  - `from sase.llm_provider._subprocess import start_interrupt_monitor, stream_process_output`
  - `from sase.llm_provider.base import LLMProvider`
  - `from sase.llm_provider.types import InvokeResult, ModelTier`
  - `from sase.llm_provider._hookspec import hookimpl`
  - `from sase.output import gemini_timer` The class carries all Phase 3 `@hookimpl` metadata methods:
    `llm_provider_name() -> "jetski"`, `llm_skill_deploy_subpath() -> ".gemini/jetski"`,
    `llm_skill_template_context() -> {...}`, `llm_cli_status_color() -> "magenta"`,
    `llm_known_model_names() -> ["jetski-default"]`, `llm_autodetect_priority() -> 20`,
    `llm_autodetect_cli_name() -> "jetski-cli"`.
- Move `tests/test_llm_provider_jetski.py` over as `tests/test_llm_jetski_provider.py` in sase-google, adapting imports.
- `pyproject.toml`:
  ```toml
  [project.entry-points."sase_llm"]
  jetski = "sase_google.llm_jetski.provider:JetskiProvider"
  ```
- Run `just check` in sase-google.

**Cross-repo verification (both workflows described in `memory/long/external_repos.md`):**

- `sase init-skills` in sase with sase-google installed should deploy jetski SKILL.md files to
  `~/.gemini/jetski/skills/...` exactly as before.
- `sase init-skills` in sase **without** sase-google installed should succeed and simply not deploy any jetski skills —
  proving jetski is truly optional.
- If this repo uses chezmoi (see `memory/long/external_repos.md`): run `chezmoi apply` after committing.

**Exit criteria.**

- `just check` passes in both sase_100 and sase-google.
- `grep -rn "jetski" sase_100/src sase_100/tests` returns nothing.
- All four providers still usable (with sase-google installed) via the same CLI invocations as before.
- `memory/` docs updated.

---

## Risks and open questions

1. **Test isolation with entry points.** pluggy + `importlib.metadata.entry_points` discovers installed packages. Test
   fixtures must avoid cross-plugin contamination when sase-google happens to be installed in the dev env. The VCS layer
   already solved this (see `src/sase/vcs_provider/_registry.py::_build_classification_pm`); reuse the pattern of
   constructing a fresh PM per test where needed and using `monkeypatch` on `importlib.metadata.entry_points` for
   registry tests.
2. **Entry-point caching.** `importlib.metadata.entry_points(group=...)` is cheap but not free — called once per call
   today. Memoize at module scope in Phase 3 so that hot paths (retry config, skill rendering loops) aren't re-walking
   entry points.
3. **Auto-detection order if a third-party plugin doesn't declare priority.** Decide in Phase 3: unpriced plugins are
   excluded from auto-detect (users must set `llm_provider.provider` explicitly). Safer than guessing.
4. **`register_provider` removal vs. deprecation.** Per AGENTS.md ("Don't add backwards-compatibility hacks"), prefer
   deletion. Verify the grep in Phase 2 picks up all call sites — the exports list in `llm_provider/__init__.py` must
   drop `register_provider` too.
5. **Jetski retry config / chezmoi SKILL.md.** After Phase 4, any user sase.yml with `llm_provider.retry.jetski:` still
   loads fine — that path is keyed by provider name string, not a whitelist. Confirm with a test.
6. **Open questions left over in `jetski.py`** (model tier mapping, JSON output format, conversation resume) travel with
   the code to sase-google and stay open questions there.

## Handoff checklist between phases

Each phase should end with a single commit (or short stack) whose message summarises the phase and explicitly mentions
"Phase N of LLM provider plugin migration". The next agent can then find the boundary via `git log` without having to
reconstruct state from the tree alone.
