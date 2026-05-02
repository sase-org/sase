---
create_time: 2026-04-11 16:51:59
status: done
prompt: sdd/prompts/202604/pr_status_input.md
---

# Plan: Add `status` input to `#pr` xprompt workflow

## Goal

Add a `status` input argument to the `#pr` xprompt workflow (`src/sase/xprompts/pr.yml`) that controls the STATUS field
of the ChangeSpec created by the workflow. The argument accepts case-insensitive "wip", "draft", or "ready" and defaults
to "draft".

## Current State

- `pr.yml` has two inputs: `name` (word) and `bug_id` (int, default 0)
- Environment variables `SASE_BUG_ID` and `SASE_PR_NAME` are set from these inputs
- The commit workflow's `_create_changespec()` calls `create_changespec_for_workflow()` without a `status` param, always
  defaulting to `"Draft"`
- The `bug_id` flow is the reference pattern: xprompt input → env var (`SASE_BUG_ID`) → read in workflow → pass to
  ChangeSpec creation

## Design

Follow the established `SASE_BUG_ID` pattern: the xprompt sets a `SASE_PR_STATUS` environment variable, and the commit
workflow reads it when creating the ChangeSpec. Case normalization happens at the point of consumption in the workflow
(wip→WIP, draft→Draft, ready→Ready), with invalid values falling back to "Draft".

## Changes

### Phase 1: xprompt definition (`src/sase/xprompts/pr.yml`)

- Add `status` input with `type: word`, `default: "draft"`
- Add `SASE_PR_STATUS: "{{ status }}"` to the `environment` section

### Phase 2: Commit workflow consumption (`src/sase/workflows/commit/workflow.py`)

- In `_create_changespec()`, read `SASE_PR_STATUS` from environment
- Normalize case-insensitively: `{"wip": "WIP", "draft": "Draft", "ready": "Ready"}`
- Pass the normalized value as the `status` kwarg to `create_changespec_for_workflow()`
- Invalid values fall back to `"Draft"` (same as current default)

### Phase 3: CLI parity (`src/sase/main/parser_commands.py` + `src/sase/workflows/commit/workflow.py`)

- Add `-s`/`--status` argument to the `sase commit` CLI parser (choices: wip, draft, ready; case-insensitive)
- In `_create_changespec()`, prefer the CLI payload value over the env var (matching the `bug_id` precedence pattern:
  `self._payload.get("status") or os.environ.get("SASE_PR_STATUS")`)
