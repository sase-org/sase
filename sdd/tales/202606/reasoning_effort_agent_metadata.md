---
create_time: 2026-06-23 14:38:57
status: done
prompt: sdd/prompts/202606/reasoning_effort_agent_metadata.md
---
# Plan: Restore Reasoning-Effort Metadata in Agent Panels

## Problem Summary

The `04m.*` agents did run with the expected effort levels from the `sase-55` epic:

- `04m.1`: prompt `%effort:medium`; `agent_meta.json["reasoning_effort"] == "medium"`
- `04m.2`: prompt `%effort:high`; `agent_meta.json["reasoning_effort"] == "high"`
- `04m.3`: prompt `%effort:xhigh`; `agent_meta.json["reasoning_effort"] == "xhigh"`

The ACE Agents-tab metadata panel did not show those levels because the Rust artifact scanner does not project
`reasoning_effort` into its wire records. Python already expects the fields on `AgentMetaWire` and
`PromptStepMarkerWire`, and `append_model_field()` already renders `Model: PROVIDER(model) @ <effort>`. However the
installed Rust scanner returns `None` for both `agent_meta.reasoning_effort` and `prompt_steps[*].reasoning_effort`, so
workflow-entry rows selected by ACE lose the metadata before rendering.

I verified this is not just stale user data: a fresh temporary artifact tree with `reasoning_effort` in
`agent_meta.json` and `prompt_step_*.json` fails
`tests/test_reasoning_effort_metadata_display.py::test_rust_scan_projects_reasoning_effort`.

## Root Cause

The Python side of `sase-55.4` was implemented, but the linked Rust backend (`sase-core`) was not updated for the same
wire shape:

- `crates/sase_core/src/agent_scan/wire.rs`
  - `AgentMetaWire` has `model` and `llm_provider`, but no `reasoning_effort`.
  - `PromptStepMarkerWire` has `model` and `llm_provider`, but no `reasoning_effort`.
- `crates/sase_core/src/agent_scan/scanner.rs`
  - `agent_meta_from_object()` reads `model` / `llm_provider`, but not `reasoning_effort`.
  - `prompt_step_from_object()` reads `model` / `llm_provider`, but not `reasoning_effort`.

Because artifact-index rows store serialized scanner records, this record shape change must also bump the artifact-index
schema version. The current Python and Rust constants are still `AGENT_ARTIFACT_INDEX_SCHEMA_VERSION = 5`; existing
indexes therefore consider themselves current and do not rebuild record JSON after this field is added.

## Implementation Plan

1. Update the Rust scanner wire in `sase-core`.
   - Add `#[serde(default)] pub reasoning_effort: Option<String>` to both `AgentMetaWire` and `PromptStepMarkerWire`.
   - Populate the fields in `agent_meta_from_object()` and `prompt_step_from_object()` with `coerce_str(...)`.
   - Keep this as an additive/defaulted wire change so old marker files and old serialized records remain readable.

2. Add Rust scanner/index coverage.
   - Extend `crates/sase_core/tests/agent_scan_parity.rs` fixture data to include `reasoning_effort` on at least one
     `agent_meta.json` and one `prompt_step_*.json`.
   - Assert direct scans preserve both values.
   - Assert rebuilt/query-indexed records also preserve both values, so the persistent index path is covered.

3. Bump artifact-index schema versions.
   - Change Rust `AGENT_ARTIFACT_INDEX_SCHEMA_VERSION` from `5` to `6`.
   - Add/update the index migration comment/function to state that v6 refreshes record JSON for `reasoning_effort`.
   - Change Python `AGENT_ARTIFACT_INDEX_SCHEMA_VERSION` from `5` to `6`.
   - Update pinned schema-version tests in Python and any Rust expectations.

4. Keep ACE on the existing fast path.
   - Do not add synchronous detail-panel filesystem reads. Once the Rust snapshot includes `reasoning_effort`,
     `enrich_agent_from_meta_wire()` and `append_model_field()` already render the suffix.
   - Re-run the real `load_all_agents()` check for `04m.*`; expected normalized rows should carry: `medium`, `high`, and
     `xhigh`.

5. Align the CLI detail panel.
   - `sase agent show` currently prints `Model: opus` and `Provider: claude`, ignoring `reasoning_effort`.
   - Update it to use the shared `append_model_field()` helper or otherwise render the same
     `Model: CLAUDE(opus) @ <effort>` shape from `agent_meta.json`.
   - Add a focused CLI test so this separate display path does not regress.

6. Verification.
   - In `sase-core`: run the relevant Rust tests for `agent_scan_parity` and then the crate test set if practical.
   - In `sase`: run:
     - `.venv/bin/python -m pytest tests/test_reasoning_effort_metadata_display.py -q`
     - a focused CLI test for `sase agent show`
     - `just check` after `just install` if repo dependencies require refresh.
   - Manually verify:
     - `load_all_agents()` reports `04m.1=medium`, `04m.2=high`, `04m.3=xhigh`.
     - `sase agent show -n 04m.1` includes the effort suffix.

## Expected Outcome

The ACE Agents-tab metadata panel receives `Agent.reasoning_effort` from the Rust-backed artifact snapshot and renders
the existing uniform `Model: PROVIDER(model) @ <effort>` suffix. Existing artifact indexes rebuild automatically because
the schema version changes, so historical rows such as `04m.*` will show the effort levels without manual cache repair.
