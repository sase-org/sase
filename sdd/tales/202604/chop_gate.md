---
create_time: 2026-04-08 20:06:20
status: done
prompt: sdd/prompts/202604/chop_gate.md
---

# Plan: Add `gate` field to chop config to prevent unnecessary agent spawns

## Problem

The `sase_pylimit_split` chop runs every 60 minutes and always spawns an agent
(`#gh:sase #sase/pylimit_split %approve`). When no Python files exceed line limits, the agent runs anyway and wastes
resources. The expected behavior: the `split_files` agent step in the `pylimit_split` workflow should only run when
`pylimit_files` finds files to split.

### Root cause analysis

I traced the full code path from chop trigger through `_flatten_anonymous_workflow` to for-loop execution. In the
**current codebase**, everything works correctly:

- `_flatten_anonymous_workflow` successfully extracts `sase/pylimit_split` from the anonymous wrapper (confirmed with
  direct test)
- The workflow executor's for-loop correctly handles empty lists (zero iterations, no agent spawned)
- The `pylimit_files` bash step produces `files=[]` and exits 0 when no files exceed limits
- Full end-to-end test: workflow completes in 2.3s with no agent invocation

**I could not reproduce the issue.** The most likely explanation is that the workspace clone had an older version of the
code where `_flatten_anonymous_workflow` lacked the slow-path logic for multi-reference prompts like
`#gh:sase #sase/pylimit_split`. When flattening fails, the anonymous workflow's single agent step runs, sending the raw
prompt to an LLM agent that then manually interprets `#sase/pylimit_split`.

### Why a code-level fix is still needed

Even though the current code works, it's fragile: if `_flatten_anonymous_workflow` fails for **any** reason (stale
workspace, env issue, code regression), the entire prompt silently degrades to an agent that runs pylimit_files
manually. There's no defense-in-depth. The fix should ensure that the agent is never spawned when there's no work to do,
regardless of the flattening behavior.

## Proposed solution: chop `gate` field

Add a `gate` field to `ChopConfig` -- a bash command that runs **before** the agent is spawned. If the gate exits
non-zero, the chop is skipped for that cycle. This is a clean, reusable mechanism.

### Config example

```yaml
chops:
  - name: sase_pylimit_split
    description: "Run the #sase/pylimit_split xprompt workflow"
    agent: "#gh:sase #sase/pylimit_split %approve"
    gate: "{ tools/pylimit_files-260227 src 1000 850 700; tools/pylimit_files-260227 tests 1000 850 700; } | grep -q ."
    run_every: 60m
```

The gate command checks if `pylimit_files` produces any output. If no files exceed limits, `grep -q .` fails (exit 1),
and the agent is not spawned.

## Implementation

### Phase 1: Add `gate` to ChopConfig and parsing

**`src/sase/axe/config.py`**:

- Add `gate: str | None = None` field to `ChopConfig` dataclass
- Parse `gate` from YAML in `_parse_lumberjacks()`

### Phase 2: Execute gate before agent launch

**`src/sase/axe/lumberjack.py`**:

- In `_run_single_chop()`, before calling `_launch_agent_chop()`, check if `chop.gate` is set
- If set, run the gate command via `subprocess.run(chop.gate, shell=True, ...)`
- If gate exits non-zero, return a `_ChopResult` with `executed=False` (or a new `gated=True` flag)
- The gate runs in the **project workspace directory** (resolved from the chop's agent prompt), not from the
  lumberjack's CWD

### Phase 3: Gate CWD resolution

The gate command references project-relative paths (e.g., `tools/pylimit_files-260227`). The gate must run from the
correct project directory. Since the chop's agent prompt contains `#gh:sase`, we need to resolve the sase project's
workspace directory to use as CWD.

- Use the existing `resolve_ref_from_prompt()` mechanism (already used by `launch_agent_from_cwd`) to detect the VCS ref
- Resolve the primary workspace directory from the project file
- Run the gate command with `cwd=primary_workspace_dir`

### Phase 4: Update chop config

**`~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`**:

- Add `gate` field to the `sase_pylimit_split` chop

### Phase 5: Tests

- Unit test: `ChopConfig` with `gate` field parses correctly
- Unit test: gate that exits 0 allows agent launch
- Unit test: gate that exits non-zero prevents agent launch
- Unit test: gate CWD is set to the resolved project directory
