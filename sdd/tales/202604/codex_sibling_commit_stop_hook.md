---
create_time: 2026-04-25 12:07:11
status: done
---
# Plan: Fix Codex Sibling Repo Commit Stop Hook Coverage

## Problem

A Codex agent edited the sibling `retired chat plugin` repository from a `sase` workspace and finished without being prompted to
commit those plugin changes. The normal `sase_commit_stop_hook` ran at the end of the session, but it only checked the
agent workspace (`/home/bryan/projects/github/sase-org/sase_101`) and found it clean.

The existing sibling repository hook already exists at `tools/sase_sibling_commit_stop_hook`, and tracked project-local
settings wire it into Claude and Gemini:

- `.claude/settings.json` runs `"$CLAUDE_PROJECT_DIR"/tools/sase_sibling_commit_stop_hook`
- `.gemini/settings.json` runs `"$GEMINI_PROJECT_DIR"/tools/sase_sibling_commit_stop_hook`

Codex does not have the equivalent hook coverage. The live Codex config at `~/.codex/hooks.json` and its chezmoi source
at `~/.local/share/chezmoi/home/dot_codex/hooks.json` only run `sase_commit_stop_hook`. As a result, Codex stop hooks
can pass whenever the main workspace is clean, even if a primary sibling repo such as `../retired chat plugin` is dirty.

## Goals

1. Make Codex sessions run the sibling repository stop hook in addition to the normal workspace commit stop hook.
2. Preserve the existing once-per-session behavior of the sibling hook so agents can decline unrelated changes without
   getting trapped in repeated stop-hook blocks.
3. Keep sibling checks scoped to primary sibling repos and chezmoi, not ephemeral agent clones.
4. Verify the hook actually blocks for dirty `retired chat plugin`-style sibling repos and still skips ephemeral workspaces.

## Implementation

### Phase 1: Update Codex Hook Configuration Source

Modify the chezmoi-managed Codex hooks source:

- `~/.local/share/chezmoi/home/dot_codex/hooks.json`

Add a second `Stop` hook command after `sase_commit_stop_hook`:

```json
{
  "type": "command",
  "command": "\"$CODEX_PROJECT_DIR\"/tools/sase_sibling_commit_stop_hook",
  "timeout": 300
}
```

This mirrors the tracked Claude/Gemini project-local hook setup and keeps the project-specific sibling scanner anchored
to the Codex project directory.

### Phase 2: Apply the Config

Run `chezmoi apply` so `~/.codex/hooks.json` receives the same hook entry. Confirm the live file matches the source.

### Phase 3: Add In-Repo Coverage for the Sibling Hook

Add focused tests for `tools/sase_sibling_commit_stop_hook` behavior using temporary repositories:

- dirty primary sibling repo blocks
- dirty ephemeral sibling workspace ending in `_<number>` does not block
- second run with the same `SASE_AGENT_TIMESTAMP` exits cleanly after the first block
- Codex runtime emits a JSON block response whose `reason` includes the actionable sibling repo details

If testing the bash script directly is too awkward in the current test harness, add a small pytest module that invokes
the script with `subprocess.run`, controlled `CODEX_PROJECT_DIR`, `SASE_TMPDIR`, `SASE_AGENT_TIMESTAMP`, and temporary
git repos.

### Phase 4: Verify End To End

Run:

- `just install` in this `sase` workspace
- targeted sibling-hook tests
- `just check` in this `sase` workspace, because the repo changed
- `just check` in `~/.local/share/chezmoi`, because the chezmoi repo changed

Also manually smoke-test the applied Codex hook config by making a temporary dirty primary sibling repo and invoking
`~/.codex/hooks.json`'s sibling command with `CODEX_PROJECT_DIR` pointed at a `sase` workspace.

## Expected Outcome

Future Codex agents launched from `sase` workspaces will be stopped once if they leave uncommitted changes in primary
sibling repos like `retired chat plugin`. The failure mode from the 2026-04-25 11:48 run is closed because Codex now runs the
same sibling dirty-repo detector already configured for Claude and Gemini.
