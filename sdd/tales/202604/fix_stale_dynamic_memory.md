---
create_time: 2026-04-14 17:58:21
status: done
prompt: sdd/prompts/202604/fix_stale_dynamic_memory.md
---

# Fix Stale Dynamic Memory Files

## Problem

Dynamic memory files (`.sase/memory/long-*.md`) persist and show up in agent prompts after their corresponding tier 3
source files (`memory/long/*.md`) have been deleted. The user deleted `memory/long/tui_development.md` and
`memory/long/xprompt_system.md` (commit `46c6d355`), but both still appear in agent prompts as dynamic memory matches.

## Root Cause

Two independent bugs compound to produce the stale memory behavior:

**Bug 1 — No cache cleanup.** `generate_dynamic_memory()` in `src/sase/memory/dynamic.py` writes matched memories to
`.sase/memory/long-*.md` but never removes files from previous runs whose source xprompts no longer exist. When a tier 3
file is deleted, the cached copy persists indefinitely across all workspaces.

**Bug 2 — Spec files bake in `### DYNAMIC MEMORY` sections.** The agent runner appends `### DYNAMIC MEMORY` to the
prompt (`run_agent_runner.py:249`). When the plan is approved, `expand_prompt_for_spec()` captures this section into the
committed spec file (`specs/<YYYYMM>/<name>.md`). On subsequent runs (or when the spec is referenced), the prompt
already contains stale `### DYNAMIC MEMORY` references pointing to cached files that still exist on disk.

## Fix

### Phase 1 — Clean up stale `.sase/memory/long-*.md` files

**File:** `src/sase/memory/dynamic.py`

Add a cleanup step at the end of `generate_dynamic_memory()`. After loading all memory xprompts from `all_prompts`,
collect the set of valid `long-*.md` filenames (derived via `_memory_filename()` from every xprompt whose name starts
with `memory/long/`). Then scan `.sase/memory/` for existing `long-*.md` files and delete any that aren't in the valid
set.

This runs on every `generate_dynamic_memory()` call, so stale files are cleaned up as soon as any agent runs in the
workspace — even if no keywords matched.

### Phase 2 — Strip existing `### DYNAMIC MEMORY` before regeneration

**File:** `src/sase/memory/dynamic.py`

Add a `strip_dynamic_memory_section(prompt)` function that removes any existing `### DYNAMIC MEMORY` section (and
everything after it) from a prompt string. Call this function inside `generate_dynamic_memory()` at the top, so the
keyword matching runs against the clean prompt without stale references influencing it.

This also prevents double-injection if a spec already contains a `### DYNAMIC MEMORY` section: the old section is
stripped, dynamic memory is regenerated fresh, and the runner appends the new section.

### Phase 3 — Tests

**File:** `tests/test_dynamic_memory.py`

1. **Stale file cleanup test** — Pre-create a `.sase/memory/long-stale.md` file that doesn't correspond to any loaded
   xprompt. Run `generate_dynamic_memory()`. Assert the stale file is deleted while valid matched files are preserved.

2. **Existing section stripped test** — Pass a prompt that already contains a `### DYNAMIC MEMORY` section. Assert that
   keyword matching uses the clean prompt (without the section) and that the returned result reflects fresh matching.

3. **Unit test for `strip_dynamic_memory_section()`** — Verify it correctly removes the section from various positions
   (end of prompt, middle of prompt, not present).
