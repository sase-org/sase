---
create_time: 2026-05-12 14:54:42
status: done
prompt: sdd/prompts/202605/codex_phase_commit_workspace.md
---
# Codex phase-agent commit fallback workspace plan

## Problem

Recent `sase-36` phase agents show that Codex phase work can still finish dirty even after the Codex commit-stop
fallback was added. The native Codex Stop hook is still not firing for SASE-managed `codex exec`, so the in-band
fallback in `src/sase/llm_provider/codex.py` is the enforcement path.

The `sase-36` evidence narrows the failure:

- `sase-36.1` and `sase-36.2` ran as Codex phase agents under the `#gh:sase` embedded workflow, produced `diff_path`
  artifacts with uncommitted changes, and left dirty workspaces (`../sase_106`, `../sase_107`) without commits.
- Their fallback log entries are `codex_fallback_skip` with `reason="no_changes"` for their real session IDs
  (`20260512135627`, `20260512135628`), even though the embedded `#gh` post-step later captured non-empty diffs.
- `sase-36.5` did get `codex_fallback_block_emitted` for project dir `../sase_100` and committed successfully.

This points to project-directory resolution, not to bead prompts or model behavior. The fallback sometimes checks the
wrong directory or lacks a stable VCS workspace signal for embedded VCS workflows. The embedded `#gh`/`#git` setup step
does know the actual workspace via `_chdir=<workspace_dir>`, but the Codex fallback currently only looks at
`CODEX_PROJECT_DIR` from the parent environment or `os.getcwd()`.

## Goal

Make the Codex fallback check the same workspace that the embedded VCS workflow assigned to the phase agent, so Codex
receives the commit instruction whenever a phase agent leaves that workspace dirty.

Keep this narrow:

- Do not add runtime-specific behavior outside the existing Codex provider fallback.
- Do not loop indefinitely after a fallback turn.
- Do not change bead lifecycle semantics.
- Do not recover the existing dirty `sase-36` workspaces in this patch; they are evidence and likely need separate
  manual recovery.

## Design

1. Introduce a small shared environment contract for workflow-chdir state, e.g. `SASE_ACTIVE_PROJECT_DIR`, owned by the
   workflow executor.
2. When a script step emits `_chdir=<path>`, keep the existing `os.chdir(path)` behavior and also set
   `SASE_ACTIVE_PROJECT_DIR=<path>`.
3. Update the Codex provider to resolve its fallback project dir from:
   - explicit parent `CODEX_PROJECT_DIR` if set,
   - `SASE_ACTIVE_PROJECT_DIR` if set,
   - otherwise `os.getcwd()`.
4. Use that same resolved project dir when creating the Codex subprocess env, so native Codex hook delivery (if it ever
   starts working for `exec`) receives the same target directory.
5. Add structured fallback skip logging that includes `project_dir` for `no_changes` skips, because the current log
   makes this failure harder to diagnose.

## Tests

Add focused regression coverage:

- Codex fallback uses `SASE_ACTIVE_PROJECT_DIR` when parent `CODEX_PROJECT_DIR` is unset, even if process cwd differs.
- Parent `CODEX_PROJECT_DIR` remains an explicit override.
- `_chdir` script-step handling sets `SASE_ACTIVE_PROJECT_DIR` while preserving the existing cwd behavior.
- Existing Codex fallback tests continue to pass.

## Validation

Run:

```bash
just install
.venv/bin/pytest tests/test_llm_provider_codex_fallback.py tests/test_xprompt_jinja_and_standalone.py tests/test_commit_stop_hook.py -x
just check
```

If `just check` fails in an unrelated flaky test, rerun the failing test once and report the exact result.
