---
create_time: 2026-06-13 16:34:03
status: done
prompt: sdd/prompts/202606/prompt_pyvision_cleanup.md
---
# Prompt History Pyvision Cleanup Plan

## Context

`just pyvision` is blocking CI after the `sase-4o` prompt-command epic closed. The original CI symptom reported three
unused public compatibility symbols in `src/sase/history/prompt.py`:

- `PromptAmbiguousError`
- `PromptNotFoundError`
- `compute_prompt_id`

Local verification in this workspace shows two related issues that need to be fixed together:

- `just pyvision` now fails earlier on private cross-module prompt-history imports introduced by the prompt-history
  split.
- `just _lint-pyvision` still passes closed-epic `--epic-symbol sase-4o(...)` allowances in `Justfile`, which pyvision
  correctly rejects because `sase-4o` is closed.

I checked production source and the configured sibling workspaces (`sase-core`, `sase-github`, `sase-telegram`, and
`sase-nvim`). None of them reference the three CI-reported symbols. Tests are the only consumers of those names through
`sase.history.prompt`. That rules out `# pyvision:` pragmas: there is no non-test file, documentation contract, or
external repository reference that would make a pragma truthful.

## Direction

Treat `sase.history.prompt` as the public compatibility facade only, not as a facade for every private helper in the
split implementation modules.

The appropriate durable fix is:

1. Remove the stale `sase-4o` `--epic-symbol` allowances from the pyvision lint recipe.
2. Remove the unused public compatibility exports from `sase.history.prompt` instead of adding pragmas.
3. Keep the actual command/runtime public surface intact:
   - prompt storage and recording,
   - list/show/stats/doctor/delete/prune,
   - selector resolution through the public base `PromptSelectorError`,
   - TUI picker compatibility through `get_prompts_for_fzf`.
4. Promote only the split-module helpers that are genuinely used across production modules to public names in their
   owning modules. Keep same-file implementation helpers private.
5. Update tests to depend on the owning modules for storage internals and to compute expected prompt IDs locally when
   they need exact selector strings.

## Implementation Plan

### 1. Clean the pyvision recipe

Edit `Justfile` `_lint-pyvision` so it invokes:

```bash
BD_COMMAND=tools/sase_bead {{ venv_bin }}/python tools/pyvision-260608 src/sase
```

with no `--epic-symbol` entries for the now-closed `sase-4o` epic.

### 2. Make cross-module prompt-history APIs explicit

In `src/sase/history/prompt_store.py`, expose production helpers that are currently used outside the file through
leading-underscore names:

- `PromptHistoryLoadError`
- `prompt_history_file`
- `prompt_entry_from_json`
- `load_prompt_history`
- `load_prompt_history_for_write`
- `locked_prompt_history`
- `save_prompt_history`
- `format_prompt_for_display`

Leave mutation-shaping helpers private when they are only used inside `prompt_store.py`.

In `src/sase/history/prompt_catalog.py`, expose `record_from_entry` because stats and maintenance need to convert stored
entries into catalog records. Make prompt ID/hash implementation private if it has no non-test production consumer.
Selector failures should continue to raise `PromptSelectorError`; the specialized not-found/ambiguous subclasses do not
need to remain part of the public facade if only tests used them.

In `src/sase/history/prompt_stats.py`, expose `short_preview` because maintenance uses it for doctor output. Leave
percentile/chip parsing helpers private when they are same-file implementation details.

Update `prompt_catalog.py`, `prompt_stats.py`, and `prompt_maintenance.py` call sites to use those public names instead
of reaching into sibling modules with private attributes.

### 3. Simplify `sase.history.prompt`

Keep `src/sase/history/prompt.py` as a narrow compatibility facade over public split-module APIs:

- public data types and errors that production source imports,
- public command/runtime functions,
- `generate_timestamp` / `_PROMPT_HISTORY_FILE` compatibility syncing if still needed by existing prompt-history tests.

Remove private wrapper functions such as `_save_prompt_history`, `_load_prompt_history`, `_record_from_entry`,
`_short_preview`, etc. They are exactly what made the facade look like a non-test importer of private implementation
details.

Remove `PromptAmbiguousError`, `PromptNotFoundError`, and `compute_prompt_id` from the facade `__all__` and module-level
compatibility exports unless a real non-test consumer appears during implementation.

### 4. Update tests without broadening product API

Move storage-internal tests to the storage module API:

- use `sase.history.prompt_store.PromptEntry`,
- use `load_prompt_history` / `save_prompt_history`,
- patch `sase.history.prompt_store._PROMPT_HISTORY_FILE`,
- patch `sase.history.prompt_store.generate_timestamp` only when calling storage functions directly.

For tests that exercise public prompt facade behavior, either patch the facade compatibility variables intentionally or
patch the storage module directly, depending on the call path.

Replace test imports of `compute_prompt_id` with a local test helper that computes `ph_<sha256[:12]>`, or derive IDs
from listed records. Replace subclass-specific assertions for not-found/ambiguous selectors with assertions against
`PromptSelectorError` plus message/attribute checks where needed.

### 5. Verify

Run focused checks first:

```bash
just pyvision
just _lint-pyvision
pytest tests/history/test_prompt*.py tests/prompt_command
```

Because this repo requires it after code changes, finish with:

```bash
just check
```

## Non-Goals

- Do not add `# pyvision:` pragmas for test-only references.
- Do not reintroduce closed-epic pyvision allowances.
- Do not edit the vendored `tools/pyvision-260608` script.
- Do not move prompt-history behavior into Rust core; this is a Python API hygiene fix, not a backend behavior change.
