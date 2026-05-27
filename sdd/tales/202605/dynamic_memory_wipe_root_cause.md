---
create_time: 2026-05-26 20:34:41
status: done
prompt: sdd/prompts/202605/dynamic_memory_wipe_root_cause.md
---
# Dynamic Memory Wipe Root-Cause Fix

## Problem

A `#git:home … #plan` agent failed on macOS with `SystemExit: 1` from `process_file_references()` during
`preprocess_prompt_late()`. The validation failure is the symptom; the trigger is that an `@.sase/memory/long-*.md`
reference injected by dynamic memory points at a file that is no longer on disk by the time the late phase validates.

The dynamic-memory pipeline today is:

1. `run_agent_runner.py:227` — `apply_dynamic_memory(prompt, project_name, …)` writes `.sase/memory/long-*.md` into the
   workspace and appends a `### DYNAMIC MEMORY` section listing each file as `@.sase/memory/long-*.md`.
2. Embedded `#git` workflow pre-step runs `git clean -fd` (`vcs_provider/plugins/_git_core_ops.py:93`) inside the
   workspace.
3. `preprocess_prompt_late` calls `rewrite_dynamic_memory_for_prompt(prompt)` (`memory/dynamic.py:296`) which is
   supposed to recreate the wiped files.
4. `process_file_references` (`gemini_wrapper/file_references.py:201`) validates that every `@`-ref exists; any miss
   triggers `_print_validation_errors → sys.exit(1)`.

Step 2 wipes `.sase/memory/` whenever the workspace's effective `.gitignore` does not list `.sase/` — and the sase
repo's own `.gitignore` does not propagate to _other_ projects' workspaces (the failing run was the user's `home`
project, which lives in its own repo). Step 3 is the recovery mechanism, but it silently no-ops on lookup failures
(`dynamic.py:319` — `if wf is None or XPromptTag.memory not in wf.tags: continue`), so any regression in re-resolution
manifests as the generic step-4 exit with no diagnostic.

Two structural defects:

- **D1 — fragile recovery.** The "write at launch, possibly wipe, rewrite late" dance only exists because step 2 reaches
  into sase-managed scratch state. Make step 2 leave `.sase/` alone and the recovery becomes unnecessary.
- **D2 — silent rewriter.** Even with step 1 protected, the rewriter should fail loudly if a memory listed in the
  prompt's DYNAMIC MEMORY section can't be re-resolved. Today the same failure mode produces an unrelated downstream
  "missing file" error.

I deliberately ruled out threading `project` through the late phase (a prior plan from agent `bh3`). Memory xprompts
come only from `load_memory_long_xprompts` (`xprompt/loader_memory.py:74`) and are never project-namespaced; the only
producer sets `name = f"memory/long/{md_file.stem}"`. So `get_all_prompts(project=None)` finds them just as well as
`get_all_prompts(project="home")`. Adding a `project` parameter to `WorkflowExecutor` / `preprocess_prompt_late` /
`rewrite_dynamic_memory_for_prompt` would not address the actual trigger — it is speculative API surface for a hazard
that does not exist in the current code.

## Implementation

### 1. Stop the wipe (primary fix)

Add `.sase/` to the workspace's `.git/info/exclude` once, early enough that no `#git` pre-step has run yet.
`.git/info/exclude` is git's per-clone, untracked ignore file — it does not require modifying any project's tracked
`.gitignore`, and `git clean -fd` honors it identically to `.gitignore` entries.

- New helper, e.g.
  `sase.workspace_provider.git_exclude.ensure_git_info_exclude_entry(workspace_dir: str, pattern: str) -> None`
  (location should sit next to other git-workspace helpers; not in `vcs_provider` because this is workspace bookkeeping,
  not a VCS op).
  - Resolve `<workspace_dir>/.git/info/exclude`. Two cases for `.git`:
    - Regular directory (common). Compose path directly.
    - `.git` file (worktree / submodule). Read `gitdir: <path>` from the file and compose `<that>/info/exclude`.
  - If neither exists, the workspace is not a git repo — no-op.
  - If the resolved exclude file already contains a non-comment line equal to the pattern, no-op. Otherwise append the
    pattern (preceded by a newline if the file does not end with one).
- Call site: `run_agent_runner.py`, immediately after `os.chdir(workspace_dir)` (line 219) and before
  `apply_dynamic_memory` (line 227). Two reasons for putting it here rather than inside the workspace-prep step:
  - `prepare_workspace_if_needed` early-returns for home mode (line 48 of `run_agent_runner_setup.py`) but home-mode
    workspaces are still git repos and still suffer the wipe (the failing run was home mode).
  - The runner is the single funnel through which every agent invocation passes. Adding it here is one line in one
    place.
  - Idempotency lets us run it on every invocation safely.
- The pattern to write is `.sase/` (matching the sase repo's existing convention).

After this lands, the `rewrite_dynamic_memory_for_prompt` call at step 2.5 of `preprocess_prompt_late` becomes
defense-in-depth (still useful if a user does `git clean -fdx` or otherwise nukes ignored files). Do **not** remove it.

### 2. Make the rewriter loud (secondary fix)

In `rewrite_dynamic_memory_for_prompt` (`memory/dynamic.py:296`):

- Replace the silent `continue` at line 319 with a clear error per unresolved memory. Aggregate all failures into one
  message rather than raising on the first, so the user sees every broken reference.
- Use `RuntimeError`, not `SystemExit`. `SystemExit` is the existing pattern in `file_references.py` because that module
  is invoked from the prompt-preprocessing entry path; the dynamic-memory module is also called from test/library
  contexts (`memory/cli_list.py` and tests under `tests/`) where a `SystemExit` would be hostile. The workflow executor
  already catches `Exception` and feeds it through `handle_workflow_error` (see `axe/run_agent_exec.py:172`), which
  surfaces a useful traceback.
- Error text shape: `"DYNAMIC MEMORY rewrite failed for <name>: xprompt not found (or no memory tag)"`. Include all
  names in one message.
- Apply the same loud check after `_write_memory_files` returns — if any expected `@.sase/memory/…` path is missing on
  disk, raise. This catches the residual case where the xprompt resolved but write to disk silently failed (read-only
  fs, permission error in subprocess substitution, etc.).

### 3. Tests

- `tests/workspace_provider/test_git_info_exclude.py` (or wherever the new helper lives):
  - Writes the pattern when `.git/info/exclude` exists and lacks it.
  - Is idempotent on repeated calls.
  - Handles a `.git` file (worktree) by following `gitdir:`.
  - Is a no-op when `.git` is absent.
- `tests/memory/test_dynamic_rewrite_loud.py`:
  - When the DYNAMIC MEMORY section lists an unknown xprompt name, `rewrite_dynamic_memory_for_prompt` raises
    `RuntimeError` mentioning the name.
  - When all listed memories resolve and write successfully, no exception.

### 4. Verify

- `just install` (workspaces are ephemeral so dependency state may be stale).
- `just check` — must pass.
- If feasible, exercise the full path manually: from this workspace, launch an agent against a project whose
  `.gitignore` does not list `.sase/`, confirm `.git/info/exclude` now contains `.sase/` after one run, and confirm the
  embedded `#git` pre-step no longer wipes the memory files.

## Risks

- **Wrong call site for the exclude write.** If a code path bypasses `run_agent_runner.py` (e.g. some direct
  WorkflowExecutor entry from a test harness or a future `sase ace` direct-execute path), it would skip the protection.
  Mitigation: the late-phase rewriter remains in place as defense-in-depth.
- **`.git` resolution edge cases.** Worktrees, submodules, or bare repos in unusual layouts may not resolve cleanly.
  Mitigation: any `OSError` / unreadable-file path becomes a no-op rather than a hard error — the dynamic-memory dance
  still works in the degraded path.
- **Loud rewriter surfaces previously-tolerated misconfigurations.** If some user has an environment where memory
  xprompts can't always be re-resolved and they were getting away with it silently, they will now see errors. This is
  the intended trade — but it is a behavior change worth calling out in the commit message.
