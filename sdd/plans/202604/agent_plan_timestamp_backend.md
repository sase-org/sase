---
create_time: 2026-04-29 13:28:40
status: wip
prompt: sdd/prompts/202604/agent_plan_timestamp_backend.md
---
# Plan: Restore PLAN Timestamp Display in `sase ace`

## Diagnosis

The missing `PLAN` row is not caused by Codex failing to write metadata. In the live artifact from the screenshot
(`/home/bryan/.sase/projects/sase/artifacts/ace-run/20260429131818/agent_meta.json`), the planner metadata contains:

```json
"plan_submitted_at": "2026-04-29T17:20:22.951546+00:00"
```

The current Python artifact scanner also preserves this field, and the current TUI loader renders the same agent as:

```text
BEGIN | 2026-04-29 13:18:18
PLAN  | 2026-04-29 13:20:22
CODE  | 2026-04-29 13:21:34
```

The failing path is the installed `sase ace` runtime because this environment has `SASE_CORE_BACKEND=rust`. The
installed Rust extension returns `plan_submitted_at=[]` for the same artifact record, so the TUI has no `PLAN` timestamp
to render. This can look Codex-specific because the reproduced live example is a Codex agent, but the bug is
backend/schema parity: any runtime whose plan metadata is loaded through the stale Rust scanner would lose the same
field.

## Implementation

1. Add a Rust scanner parity regression test in `../sase-core` that writes a scalar `plan_submitted_at` value to
   `agent_meta.json` and asserts the scanner normalizes it to a one-element list, matching Python's `_coerce_str_list()`
   behavior.
2. Run the focused Rust scanner tests in `../sase-core`.
3. Rebuild and reinstall the Rust backend into the uv-tool `sase` environment used by `/home/bryan/.local/bin/sase`.
4. Re-run the installed-runtime check with `SASE_CORE_BACKEND=rust` against the live `20260429131818` artifact and
   verify the Rust scanner now returns the `plan_submitted_at` timestamp.
5. Run the required project verification for any modified repo: `just check` in the main `sase` repo if it changes, and
   the appropriate Rust checks in `../sase-core`.

## Expected Outcome

The `Agents` tab metadata panel will receive `agent.plan_times` even when `SASE_CORE_BACKEND=rust`, so plan workflows
will show `PLAN | ...` alongside `BEGIN`, `CODE`, and `END` timestamps. The fix is backend-neutral and does not add any
Codex-specific logic.
