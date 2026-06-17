---
create_time: 2026-06-17 07:18:48
status: done
prompt: sdd/prompts/202606/xprompt_metadata_capture.md
---
# Plan: Complete Xprompt Metadata Capture

## Problem

The new `Xprompts:` field in the Agents-tab metadata panel can omit xprompt references that were present in the prompt
that launched the agent. `#plan` is the most visible example: it is a config-backed simple xprompt and the collector can
recognize it, but it does not reliably appear in the panel.

## Findings

The display path is intentionally cheap: the detail header reads precomputed JSON metadata from the agent artifacts
directory via `load_xprompts_used()`. It does not re-parse `raw_xprompt.md` in the Textual hot path, which is the right
shape for TUI responsiveness.

The collector itself is not the immediate problem. `collect_used_xprompts("#plan #propose #coder")` recognizes `plan` as
a `part`, `propose` as a `workflow`, and `coder` as a `part`.

The metadata write boundary is incomplete:

- Normal daemon-launched agents persist `submitted_xprompt.md` and `raw_xprompt.md`, then expand xprompts, but do not
  write `xprompts.json` for the launch-boundary prompt.
- Workflow prompt steps write step-specific metadata, but the same helper also writes the shared `xprompts.json`, which
  is the filename used by root/non-step agent rows. That can replace prompt-level metadata with step-level metadata.
- The TUI loader then does what it was designed to do: non-step rows read `xprompts.json`; step rows read
  `xprompts_<step>.json` and intentionally do not fall back to the shared file.

## Implementation Plan

1. Separate prompt-level and step-level usage writes.
   - Keep the existing JSON record shape stable: `name`, `kind`, `positional`, `named`, `tags`.
   - Add an explicit option or small helper so prompt-step execution can write only `xprompts_<step>.json` while
     preserving the shared `xprompts.json` as launch/root metadata.
   - Preserve backward compatibility for existing callers that expect the current shared-file behavior unless they opt
     into step-only writes.

2. Capture daemon-launched agent xprompt usage at the launch boundary.
   - In the runner setup/preprocessing path, write `xprompts.json` from the alias-resolved raw prompt before xprompt
     expansion.
   - Use the same prompt text that is persisted to `raw_xprompt.md`, so aliases and VCS underscore normalization match
     the expansion path and existing collector behavior.
   - Keep this outside the TUI event loop; it runs in the detached agent process, so it does not add synchronous work to
     selection or render paths.

3. Update workflow prompt-step execution.
   - Continue writing per-step files for child rows.
   - Stop overwriting shared root metadata from prompt-step execution once the prompt-level writer exists.
   - Keep workflow-local xprompts available to the collector through the existing `extra_xprompts` parameter.

4. Add focused regression tests.
   - Runner preprocessing writes `xprompts.json` containing `#plan` for a normal daemon-launched prompt.
   - Step execution writes `xprompts_<step>.json` without clobbering an existing prompt-level `xprompts.json`.
   - `load_xprompts_used()` still prefers step-specific files for child rows and still avoids shared fallback when a
     child step has no xprompt metadata.
   - Existing mixed workflow/part and alias tests continue to pass.

5. Verify behavior and quality.
   - Run focused tests for `used_xprompts`, runner setup, workflow execution, and prompt-panel metadata loading.
   - Run `just install` if needed for the ephemeral workspace.
   - Run `just check` after code changes, per project instructions.

## Risk Management

The main compatibility risk is changing what `xprompts.json` means for workflow artifacts. The plan keeps the shared
file as prompt/root metadata and moves child-specific data to the already-supported `xprompts_<step>.json` file. That
matches the TUI loader contract and avoids adding any prompt parsing to detail-panel rendering.
