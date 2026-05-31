---
create_time: 2026-05-31 10:48:44
status: done
prompt: sdd/prompts/202605/revert_dynamic_memory.md
---
# Revert Dynamic Memory Functionality

## Goal

Remove SASE's dynamic-memory feature end to end: no keyword-triggered long-memory matching, no `.sase/memory/long-*.md`
cache generation, no `### DYNAMIC MEMORY` prompt section, no late rewrite pass, and no generated instruction/docs/tests
that advertise or validate that behavior.

## Current Shape

Discovery found dynamic memory in these active surfaces:

- Runtime launch path: `run_agent_runner.py` calls `apply_dynamic_memory()`, which writes `dynamic_memory.json`, prints
  a launch summary, and appends a `### DYNAMIC MEMORY` prompt section.
- Late provider preprocessing: `preprocess_prompt_late()` rewrites `.sase/memory/long-*.md` files from the dynamic
  section before file-reference validation.
- XPrompt registry: `memory/long/*.md` files with `keywords` frontmatter are auto-discovered as `memory`-tagged
  xprompts. `XPrompt` and `Workflow` also carry `keywords` metadata that was added for this feature.
- AMD/memory init: generated `AGENTS.md` and `memory/README.md` text describe dynamic memory when keyworded long-memory
  files exist.
- Episode collection: `dynamic_memory.json` is treated as a memory-context artifact source.
- Docs, schema, bundled `sase_memory_read` skill text, tests, and fixtures still reference dynamic memory.

Episodic recall is distinct and should stay. It currently lives in `src/sase/memory/dynamic.py`, so that code needs to
move before the dynamic module is removed.

## Scope Decisions

- Preserve audited memory reads, reviewed memory proposals, and opt-in episodic recall.
- Preserve generic memory-proposal `keywords` metadata unless it directly describes dynamic discoverability; removing
  the proposal field would be a ledger/schema migration and is not required to disable dynamic memory.
- Do not edit canonical `memory/long/*.md` memory files. Existing keyword frontmatter can remain inert metadata.
- Treat historical SDD/bead event logs as history, not product references, unless a test fixture depends on them.

## Implementation Plan

1. Split episodic recall out of `src/sase/memory/dynamic.py`.
   - Create a focused module for `SASE_MEMORY_EPISODES_RECALL`, recall limits, recall generation, and
     `### EPISODIC MEMORY` formatting.
   - Update launch setup and tests to import from that module.

2. Remove dynamic-memory runtime behavior.
   - Replace `apply_dynamic_memory()` with an episode-recall-only augmentation helper.
   - Remove `generate_dynamic_memory()`, `MatchedMemory`, `DynamicMemoryResult`, dynamic section formatting, stale cache
     cleanup, dynamic section parsing, and late rewrite logic.
   - Remove the late preprocessing rewrite step and update prompt pipeline docs/comments.
   - Keep `.sase/` workspace ignore handling only if still useful for other runtime files, with non-dynamic comments.

3. Remove dynamic-memory xprompt discovery and metadata.
   - Delete the `memory/long/*.md` auto-discovery loader and remove it from xprompt discovery order and exports.
   - Remove the `memory` xprompt tag.
   - Remove xprompt/workflow `keywords` parsing, schema entries, catalog rendering, and tests that only exist for
     dynamic-memory matching.

4. Remove generated instruction and memory-init references.
   - Stop AMD-managed `AGENTS.md` from rendering the "Dynamic Memory Files" section.
   - Update `memory/README.md` generation and `sase memory list` notes so they describe only loaded, referenced,
     available, and audited memory behavior.
   - Remove dynamic-discoverability warnings from memory proposal approval.

5. Remove episode artifact handling for dynamic memory.
   - Stop collecting `dynamic_memory.json` as a current artifact marker/source.
   - Remove `dynamic_memory` from memory-context source classification and housekeeping lists.
   - Update episode tests and fixtures to use audited memory reads only.

6. Sweep docs, skill source text, tests, and fixtures.
   - Update `docs/memory.md`, `docs/xprompt.md`, `docs/configuration.md`, `docs/init.md`, `docs/llms.md`, architecture
     and development docs, and image prompt/critique files so active docs no longer mention dynamic memory.
   - Update `src/sase/xprompts/skills/sase_memory_read.md`; then run `sase init-skills --force` per generated-skill
     workflow.
   - Delete dynamic-memory test modules and adjust parser/catalog/AMD/memory tests to the reverted behavior.

7. Verify.
   - Run targeted tests around launch setup, preprocessing, xprompt loading, AMD/memory init, memory proposals, memory
     episodes, and shipped skill sources.
   - Run `just install` if needed, then `just check` because this repo requires it after file changes.
   - Finish with a final `rg` sweep for active dynamic-memory terms to catch stale references.
