---
create_time: 2026-04-05 11:41:10
status: done
prompt: sdd/prompts/202604/unlimited_agent_revival.md
---

# Plan: Unlimited Agent Revival

## Goal

Remove the `MAX_DISMISSED = 500` limit so ALL agent chats are saved forever and revivable via the `R` keymap.
Restructure bundle storage to keep performance excellent even with thousands of dismissed agents.

## Current Design

Two flat JSON files in `~/.sase/`:

- `dismissed_agents.json` — list of identity tuples `[agent_type, cl_name, raw_suffix]` (lightweight index)
- `dismissed_agent_bundles.json` — list of full Agent serializations (the heavy data)

Both files are capped at 500 entries (`MAX_DISMISSED`). On every dismissal, the **entire** bundles file is read, the new
agent is appended, and the entire file is rewritten. On every `_load_agents()` call (which fires on a timer), all
bundles are deserialized to populate `_dismissed_agent_objects`.

## Problem with Unbounded Growth

With no cap, `dismissed_agent_bundles.json` grows indefinitely. Each bundle is ~1-3KB of JSON. At 5,000 agents that's
~10MB read+parsed+written on every single dismissal and every load cycle. This is the bottleneck.

The identity index (`dismissed_agents.json`) is fine — it's just small tuples and stays under 1MB even at 10K+ entries.

## Design: Per-Agent Bundle Files

Split the monolithic bundles file into individual files under `~/.sase/dismissed_bundles/`:

```
~/.sase/dismissed_bundles/
  20260401153022.json     # one file per agent (named by raw_suffix)
  20260402091545.json
  ...
```

### Performance Characteristics

| Operation                 | Before (monolithic)           | After (per-file)                                                |
| ------------------------- | ----------------------------- | --------------------------------------------------------------- |
| Dismiss 1 agent           | Read all + write all (O(n))   | Write 1 file (O(1))                                             |
| Load for `_load_agents()` | Read + parse all bundles      | Read only bundles not found by loaders (typically small subset) |
| Revive 1 agent            | Read all → filter → write all | Delete 1 file (O(1))                                            |
| Batch dismiss N           | Read all + write all          | Write N files (O(N), no read)                                   |

## Implementation

### Phase 1: Core — Split bundles into per-agent files

**File: `src/sase/ace/dismissed_agents.py`**

1. Remove `MAX_DISMISSED` constant
2. Remove trimming logic from `save_dismissed_agents()` — keep all entries
3. Add `_DISMISSED_BUNDLES_DIR = Path.home() / ".sase" / "dismissed_bundles"`
4. Replace `save_dismissed_bundles(agents: list[Agent])` with `save_dismissed_bundle(agent: Agent)` — writes a single
   `{raw_suffix}.json` file. For agents without `raw_suffix`, use a deterministic name like
   `{agent_type}_{cl_name_hash}.json`
5. Replace `load_dismissed_bundles()` with `load_dismissed_bundles(identities: set[...])` — takes specific identities to
   load and only reads those files (no longer reads everything)
6. Update `remove_bundle_by_identity()` to delete the individual file(s) — the parent file plus any child files matching
   `parent_timestamp`

### Phase 2: Update callers

**File: `src/sase/ace/tui/actions/agents/_killing.py`**

- `_save_agent_bundle()`: Replace read-all + append + write-all with single `save_dismissed_bundle(agent)` call. Write
  child step bundles as separate files too.

**File: `src/sase/ace/tui/actions/agents/_loading.py`**

- `_load_agents()` (lines 189-208): Pass the specific identities that need bundle supplementation to the new targeted
  `load_dismissed_bundles(identities)` instead of loading all bundles.

**File: `src/sase/ace/tui/actions/agents/_revive.py`**

- `_do_revive_agent()` / `_do_revive_agents()`: `remove_bundle_by_identity()` already works by identity — just verify it
  handles the new file-per-agent layout.

### Phase 3: Migration

**File: `src/sase/ace/dismissed_agents.py`**

Add a one-time migration in `load_dismissed_bundles()` (or a dedicated helper called from there):

1. If `~/.sase/dismissed_agent_bundles.json` exists:
   - Read it, write each bundle as an individual file under `~/.sase/dismissed_bundles/`
   - Delete the monolithic file
2. This is idempotent — if the directory already has the files, skip duplicates
