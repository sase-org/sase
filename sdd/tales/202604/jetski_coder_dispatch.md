---
create_time: 2026-04-23 11:44:38
status: done
prompt: sdd/prompts/202604/jetski_coder_dispatch.md
---

# Fix: Jetski coder invocation incorrectly dispatches to the Gemini provider

## Problem

When running a jetski-backed workflow in `sase ace`, the **planner** step succeeds but the **coder** step (which
implements the plan) fails with:

```
Error when talking to Gemini API ... ModelNotFoundError: models/jetski-default
is not found for API version v1main
...
subprocess.CalledProcessError: Command
  ['/google/bin/releases/gemini-cli/tools/gemini', '--yolo', '--model',
   'jetski-default'] returned non-zero exit status 1.
```

The gemini CLI is being invoked with `--model jetski-default`, which means the coder is ending up inside
`GeminiProvider.invoke()` rather than `JetskiProvider.invoke()`.

## Root cause

Traced through the code (file paths relative to repo root):

1. **Planner** runs via `src/sase/axe/run_agent_phases.py:97-104`. When the default provider is auto-detected as jetski
   (via `shutil.which("jetski-cli")` in `src/sase/llm_provider/registry.py:138`), the planner calls
   `provider.resolve_model_name()` which returns `"jetski-default"` (see `src/sase/llm_provider/jetski.py:19`). That
   model string is stored in the agent meta under the `"model"` key, and the planner succeeds because at this stage
   `agent_llm_provider = "jetski"` was correctly resolved via `get_default_provider_name()`.

2. **Coder** is spawned by `src/sase/axe/run_agent_exec_plan.py:320-325`, which prepends a `%model:<ctx.agent_model>\n`
   prefix to the coder prompt — here `ctx.agent_model = "jetski-default"`. The `llm_provider` field is **not** forwarded
   — only the model name is.

3. When the coder re-enters `run_agent_phases.py:97-100`, the `%model` directive is parsed and
   `resolve_model_provider("jetski-default")` is called (`src/sase/llm_provider/registry.py:75-103`):
   - The `_PROVIDER_MODEL_RE` regex (line 38) requires a `provider/model` form — doesn't match a bare name.
   - The `_MODEL_TO_PROVIDER` dict (lines 13-35) has entries for claude/codex/gemini model names, but **no entry for
     `"jetski-default"`**.
   - The function therefore returns `(None, "jetski-default")`, leaving `resolved_provider = None`.

4. With no resolved provider, the coder falls back to `get_default_provider_name()`. On machines where `jetski-cli` is
   not on `PATH` (the real binary lives at `/google/bin/releases/jetski-devs/tools/ cli`), auto-detection returns
   whichever of claude/codex/gemini is present first — in the observed failure, `"gemini"`.

5. `GeminiProvider.invoke(model_override="jetski-default")` then runs `gemini --yolo --model jetski-default` → the
   observed `ModelNotFoundError` and `CalledProcessError`.

### Summary

The planner → coder handoff forwards the model name (`jetski-default`) but not the provider identity. The model name
alone is expected to disambiguate via `_MODEL_TO_PROVIDER`, but jetski is the only provider without any entry in that
dict. This asymmetry violates the "treat all runtimes uniformly" principle in `AGENTS.md` / `memory/short/gotchas.md`.

## Fix

Add a single entry to the `_MODEL_TO_PROVIDER` dict at `src/sase/llm_provider/registry.py:13-35`:

```python
# Jetski models
"jetski-default": "jetski",
```

This closes the dispatch gap and aligns jetski with the other providers. Once registry resolution works, the existing
`%model:jetski-default\n` prefix written by `run_agent_exec_plan.py` flows through correctly and the coder lands in
`JetskiProvider.invoke()`.

### Why this is safe

- `JetskiProvider.invoke()` already accepts `model_override` as a documented no-op (`src/sase/llm_provider/jetski.py:77`
  — `noqa: ARG002`; docstring at lines 82-88 explains jetski-cli has no `--model` flag). Routing
  `model_override="jetski-default"` to the jetski provider is therefore a silent pass-through — the current intended
  behavior.
- When the canonical jetski model name is later determined (per the `TODO(open-question-3)` at `jetski.py:17-19`), the
  registry entry gets updated alongside `_DEFAULT_MODEL` — no structural change.

### Why not other fixes

- **Forwarding `llm_provider` through the planner→coder handoff.** Broader ergonomics change; would also need plumbing
  through `_update_coder_model_meta`, `ctx.agent_*`, and the `%model` directive grammar. Not needed — the registry entry
  solves the root cause.
- **Making the prefix use `jetski/jetski-default` explicit syntax.** Same effect, but requires `run_agent_exec_plan.py`
  to know the provider identity, which it currently does not track. Strictly more code.
- **Changing auto-detect order.** Doesn't help — the failure happens on hosts where `jetski-cli` is installed at a
  non-PATH location, which is the documented install layout.

## Test

Extend `tests/test_llm_provider_core.py::test_resolve_model_provider_implicit_mapping` (lines 167-173) to include the
jetski mapping, matching the pattern already used for the other providers' default model names:

```python
assert resolve_model_provider("jetski-default") == ("jetski", "jetski-default")
```

Run `just check` to confirm lint + mypy + the full test suite pass.

## Scope

- Single-line addition to `_MODEL_TO_PROVIDER`.
- Single-line addition to the implicit-mapping test.
- No refactoring of the planner→coder handoff (out of scope).
- No changes to auto-detect logic or jetski binary resolution.
