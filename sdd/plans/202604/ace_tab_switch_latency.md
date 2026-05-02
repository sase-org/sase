---
create_time: 2026-04-27 10:13:20
status: wip
prompt: sdd/prompts/202604/ace_tab_switch_latency.md
---
# Plan: Make `sase ace` Tab Switching Fast

## Problem Summary

The provided profile from `.sase/home/tmp/sase/ace_profile_20260427_100850.txt` shows the TUI spending multiple seconds
on the event loop while switching or refreshing the ChangeSpecs tab. The hottest path is:

`watch_current_tab` / async refresh -> `_refresh_display()` -> `ChangeSpecDetail.update_display()` ->
`build_mentors_section()` -> `format_profile_with_count()` -> `get_mentor_profile_by_name()` ->
`get_all_mentor_profiles()` -> `_load_mentor_profiles()` -> `load_merged_config()` -> YAML/plugin config loading.

The biggest sampled block is about 5 seconds inside one ChangeSpec detail repaint, and the same shape repeats several
times. The expensive work is not inherent to tab switching; it is repeated mentor profile lookup and YAML parsing during
rendering. Rendering should never reload global config once per visible mentor profile.

## Goals

1. Make switching back to the CLs tab feel immediate even when the machine has large plugin config files.
2. Avoid synchronous repeated `load_merged_config()` calls from display formatting.
3. Preserve existing mentor profile semantics, including user/plugin config merge behavior and local-profile
   project-scoping behavior where it is still used.
4. Keep the fix focused and testable before broader TUI refresh changes.

## Proposed Implementation

### 1. Add a small in-process mentor profile cache

Add caching in `src/sase/config/mentor.py` around the parsed mentor profile list and name lookup.

Preferred shape:

- Keep `_load_mentor_profiles()` as the uncached parser/loader for tests and direct callers that intentionally want a
  fresh read.
- Make `get_all_mentor_profiles()` return a cached list populated by `_load_mentor_profiles()`.
- Make `get_mentor_profile_by_name()` use a cached dict keyed by `profile_name`, derived from the cached list.
- Add `clear_mentor_profile_cache()` for tests and for any future config-edit workflow that needs explicit invalidation.

This should collapse the repeated profile-count cost from "parse all merged YAML once per profile label per repaint" to
"parse once per process, then dictionary lookups".

### 2. Avoid extra config loads inside one mentors render

Even with the module cache, `build_mentors_section()` currently imports and calls `format_profile_with_count()` inside
the loop. After the module-level cache is in place, this is no longer catastrophic, but a render-local profile total map
is still cleaner.

Update `build_mentors_section()` to either:

- use a new helper that accepts precomputed profile totals, or
- load all mentor profiles once at the beginning of the MENTORS section and format counts locally.

Keep public formatting behavior unchanged: unknown profiles still render as the bare profile name; known profiles render
as `profile[started/total]`.

This makes the hot display path obvious and protects it from future changes that accidentally bypass the global cache.

### 3. Consider CL tab activation refresh behavior only if needed

`watch_current_tab()` currently calls `_refresh_display()` synchronously when switching to `changespecs`. Once mentor
profile lookups are cheap, this may be fine. If latency remains visible, adjust CL tab activation to:

- show the already-cached `self.changespecs` state immediately,
- schedule disk reload via `_schedule_changespecs_async_refresh()` instead of doing heavyweight work inline,
- ensure this does not regress hint mode, fold mode, and saved per-tab index behavior.

Do this as a second step only if profiler/tests still show tab activation blocking after the mentor cache fix.

## Tests

Add focused tests for mentor profile caching:

- `get_all_mentor_profiles()` should call `load_merged_config()` once across repeated calls.
- `get_mentor_profile_by_name()` should not reload config for repeated name lookups.
- `clear_mentor_profile_cache()` should force a subsequent reload.
- Unknown profile formatting should continue to fall back to the profile name.
- Known profile formatting should still include `[started/total]`.

Run targeted tests first:

```bash
pytest tests/test_mentor_config_loading.py tests/test_mentor_config_retrieval.py tests/test_display_helpers.py tests/test_mentors_builder.py
```

Because this repo requires it after changes, finish with:

```bash
just install
just check
```

## Validation

After implementation, run a small timing/profiling sanity check around repeated `format_profile_with_count()` calls with
a patched or real large config. The expected result is that repeated calls no longer repeatedly enter
`load_merged_config()` or YAML parsing.

If possible, rerun `sase ace --profile` and verify the profile no longer shows `load_merged_config()` under
`build_mentors_section()` as a multi-second hotspot.

## Risks and Mitigations

- **Stale config in long-running TUI sessions:** caching means config edits may not be reflected until the process
  restarts or the cache is cleared. This is acceptable for the first fix because the existing TUI already treats most
  config as process startup state, but expose `clear_mentor_profile_cache()` so refresh/config-edit flows can opt in to
  invalidation later.
- **Tests that patch `load_merged_config()`:** tests must clear the cache between scenarios. Add local fixture cleanup
  or call `clear_mentor_profile_cache()` in new tests.
- **Returning mutable cached objects:** existing callers receive mutable dataclasses today. Preserve compatibility, but
  avoid mutating cached profile objects in the new code.

## Success Criteria

- Repeated profile count formatting does not reload merged config.
- CL detail repaint no longer spends seconds in YAML/plugin config parsing.
- Existing mentor config and TUI widget tests pass.
- `just check` passes after code changes.
