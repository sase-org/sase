---
create_time: 2026-03-25 18:52:48
status: done
prompt: sdd/prompts/202603/fix_done_agent_meta_enrichment.md
---

# Fix: Missing CL URL and CL Name in Agent Metadata Panel for Done Agents

## Problem

When an agent completes with an embedded `#pr` workflow (e.g., `#pr:foobar`), the CL URL (`meta_pr_url`), CL name
(`meta_changespec`), and PR header (`meta_pr_header`) are not displayed in the agent metadata panel on the Agents tab.

## Root Cause

The `#pr` workflow's `report` step outputs `meta_pr_url`, `meta_pr_header`, and `meta_changespec` into prompt step
marker files (`prompt_step_pr__report.json`) in the agent's artifacts directory. However, when loading **done** agents
from `done.json`, the function `_enrich_agent_from_prompt_markers()` is **never called**, so these meta fields are never
populated on `agent.step_output`.

**Evidence:**

- `load_running_home_agents()` (line 433 of `_artifact_loaders.py`): calls BOTH `enrich_agent_from_meta()` AND
  `_enrich_agent_from_prompt_markers()`.
- `load_done_agents()` (line 336 of `_artifact_loaders.py`): calls ONLY `enrich_agent_from_meta()` — the
  `_enrich_agent_from_prompt_markers()` call is **missing**.

The `step_output` written to `done.json` comes from `extract_step_output_and_diff_path()`, which reads
`workflow_state.json`. This only captures the parent workflow's step outputs, NOT the embedded workflow's rollover step
outputs (which are stored in the prompt step marker files).

## Data Flow (Current)

```
pr.yml report step → outputs meta_pr_url, meta_changespec, meta_pr_header
  → saved to prompt_step_pr__report.json (marker file in artifacts dir)

done.json ← step_output from workflow_state.json (parent steps only, no embedded meta)

TUI load_done_agents() → reads done.json → step_output has no meta fields
  → calls enrich_agent_from_meta() only
  → meta fields from prompt_step_pr__report.json are NEVER read
  → Agent details panel shows no CL URL / CL name
```

## Fix

### File: `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`

**Change:** Add `_enrich_agent_from_prompt_markers(agent, str(artifact_dir))` after the existing
`enrich_agent_from_meta(agent, str(artifact_dir))` call at line 336 in `load_done_agents()`.

```python
# Before (line 336):
enrich_agent_from_meta(agent, str(artifact_dir))

# After:
enrich_agent_from_meta(agent, str(artifact_dir))
_enrich_agent_from_prompt_markers(agent, str(artifact_dir))
```

This is a **one-line addition**. The `_enrich_agent_from_prompt_markers()` function already exists and is designed
exactly for this purpose — it reads `prompt_step_*.json` marker files, extracts `meta_*` fields, and merges them into
`agent.step_output`.

### Effect on Display

After the fix, `agent.step_output` will contain:

- `meta_changespec` → shown in header as "ChangeSpec: eval_foobar" (replaces "Project: eval" since `meta_changespec` is
  checked before `is_project_agent` in the elif chain)
- `meta_pr_url` → shown as dynamic meta field: "Pr Url: https://..."
- `meta_pr_header` → shown as dynamic meta field: "Pr Header: ..."

### Why This Is Safe

1. The function already runs for running home agents (line 433) — adding it for done agents follows the same pattern.
2. It's additive — it only adds `meta_*` fields to `step_output`, never removes existing data.
3. The marker files persist in the artifacts directory alongside `done.json`, so they're always available.
4. Performance impact is minimal — reads a few small JSON files per agent from the same directory.
5. Works retroactively for all existing done agents whose marker files are still on disk.
