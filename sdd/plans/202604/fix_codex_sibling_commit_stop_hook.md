---
create_time: 2026-04-29 13:27:23
status: done
prompt: sdd/prompts/202604/fix_codex_sibling_commit_stop_hook.md
---
# Plan: Fix Codex Sibling Commit Stop Hook

## Problem

Codex is configured to run the repo-local sibling commit hook with this command:

```json
"\"$CODEX_PROJECT_DIR\"/tools/sase_sibling_commit_stop_hook"
```

That looked symmetric with Claude and Gemini, but the current Codex runtime does not define `CODEX_PROJECT_DIR`. In this
session the environment includes `CODEX_THREAD_ID` and `CODEX_CI`, but no `CODEX_PROJECT_DIR`. When the hook command is
expanded by the shell, the command becomes:

```bash
/tools/sase_sibling_commit_stop_hook
```

That path does not exist, so the hook exits before the sibling scanner script can run. A direct cwd-relative invocation
of `./tools/sase_sibling_commit_stop_hook` does block correctly for a dirty sibling repo, which means the primary bug is
hook command resolution for Codex rather than the sibling scanner itself.

There is a second related issue in SASE's Codex provider: it creates a shadow `CODEX_HOME` and inherits most environment
variables, but it does not inject a project-directory variable for Codex child processes. Several hook paths and helper
functions already know how to use `CODEX_PROJECT_DIR` if it exists, so SASE should provide it consistently.

## Goals

1. Make SASE-launched Codex agents receive `CODEX_PROJECT_DIR=<current workspace>`.
2. Make the live Codex hook command robust even when Codex is launched outside SASE and does not set
   `CODEX_PROJECT_DIR`.
3. Preserve the existing sibling hook behavior:
   - scan primary sibling repos and chezmoi;
   - skip ephemeral `_<number>` workspaces;
   - block only once per session marker;
   - emit Codex JSON block payloads.
4. Add regression coverage for the provider environment injection and the cwd-fallback command shape.

## Implementation

### Phase 1: Fix SASE's Codex provider environment

Update `src/sase/llm_provider/codex.py` so `_codex_subprocess_env()` sets:

```python
env["CODEX_PROJECT_DIR"] = os.getcwd()
```

This should happen in the normal shadow-home path. If `SASE_CODEX_DISABLE_SHADOW_HOME=1` is set, keep the current
behavior of inheriting the parent environment unchanged unless a broader provider-env refactor is needed.

Add a focused test in `tests/test_llm_provider_codex.py` that invokes `CodexProvider` from a temporary cwd and asserts
the `subprocess.Popen(..., env=...)` mapping contains both the shadow `CODEX_HOME` and the expected `CODEX_PROJECT_DIR`.

### Phase 2: Make the Codex hook config independent of `CODEX_PROJECT_DIR`

Update the chezmoi-managed Codex hook source:

```text
~/.local/share/chezmoi/home/dot_codex/hooks.json
```

Change the sibling hook command to use a shell fallback:

```json
"\"${CODEX_PROJECT_DIR:-$PWD}\"/tools/sase_sibling_commit_stop_hook"
```

Then run `chezmoi apply --force` and verify the live file:

```text
~/.codex/hooks.json
```

matches the source. This keeps the hook working for SASE-launched Codex agents and for manually launched Codex sessions
whose hook cwd is the project workspace.

### Phase 3: Test the hook path and scanner behavior

Extend `tests/test_sibling_commit_stop_hook.py` with a regression test that executes the configured fallback command
with `CODEX_PROJECT_DIR` unset from a temporary project cwd and verifies it emits a Codex JSON block when a primary
sibling repo is dirty.

Keep existing tests for:

- dirty primary sibling repo blocks;
- ephemeral sibling workspace is skipped;
- repeated same-session invocation exits cleanly;
- Codex JSON reason includes actionable sibling details.

### Phase 4: Verify

Run:

```bash
just install
pytest tests/test_llm_provider_codex.py tests/test_sibling_commit_stop_hook.py
just check
```

Because the chezmoi repo is modified, also run:

```bash
just check
```

from `~/.local/share/chezmoi`.

Finally, manually reproduce the original failure shape by running the fallback command with `CODEX_PROJECT_DIR` unset
from a SASE workspace. It should no longer resolve to `/tools/...`; it should invoke the repo-local hook and emit a
Codex block payload when a sibling repo is dirty.
