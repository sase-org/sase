---
create_time: 2026-03-25 11:56:01
status: done
prompt: sdd/prompts/202603/gemini_afteragent_stop_hooks.md
---

# Fix sase_commit_stop_hook for Gemini Agents (AfterAgent Hooks)

## Root Cause

`.gemini/settings.json` registers `sase_commit_stop_hook` on the `SessionEnd` event. Gemini CLI's `SessionEnd` is
**fire-and-forget** — the hook runs asynchronously after the agent completes, but Gemini ignores exit codes and output.
The hook cannot block the agent or force a retry. We can see from the sase ace logs that the hook _did_ fire ("Expanding
hook command: sase_commit_stop_hook"), but its `exit 2` was silently discarded. The `create` workflow step in
`commit.yml` then fell through to its CommitWorkflow fallback (line 29: `# Create the commit ourselves`).

## Solution

Switch from `SessionEnd` to Gemini CLI's **`AfterAgent`** event — the direct equivalent of Claude's `Stop` hook:

- Returns `{"decision":"deny","reason":"..."}` on stdout → agent retries with `reason` as correction prompt
- Input JSON on stdin includes `stop_hook_active: true` on retries → built-in deduplication
- Exit code 2 also works (stderr becomes the reason)

Then remove the CommitWorkflow fallback from xprompt steps, since all three runtimes (Claude, Codex, Gemini) will
support stop-hook-based commit orchestration.

## Changes

### Phase 1: Add Gemini runtime support to `sase_commit_stop_hook.py`

**File:** `src/sase/scripts/sase_commit_stop_hook.py`

1. Add `_is_gemini_runtime()` — detect via `GEMINI_PROJECT_DIR` env var (set by Gemini CLI, not set by Claude/Codex).

2. Add `_read_gemini_stdin()` — read JSON from stdin (Gemini pipes hook metadata on stdin; Claude/Codex do not). Parse
   `stop_hook_active` field. Guard with `sys.stdin.isatty()` check to avoid hanging when stdin is a terminal.

3. Update `_emit_block()` — add Gemini path before the Claude fallback:

   ```python
   if _is_gemini_runtime():
       print(json.dumps({"decision": "deny", "reason": details or reason}))
       return 0
   ```

4. Update deduplication in `main()` — for Gemini, use `stop_hook_active` from stdin instead of the marker file. Keep
   marker file logic for Claude/Codex.

5. Update commit instructions — for Gemini agents (which don't have `/sase_git_commit` or `/sase_hg_commit` skills),
   provide inline CLI instructions in the deny reason instead of skill references:
   ```
   "Run: .venv/bin/sase commit create --message '<your commit message>' to commit the changes"
   ```

### Phase 2: Add Gemini runtime support to `tools/sase_sibling_commit_stop_hook`

**File:** `tools/sase_sibling_commit_stop_hook`

Same pattern as Phase 1, but in Bash:

1. Add `read_hook_input()` — reads stdin JSON, extracts `stop_hook_active` into `GEMINI_STOP_HOOK_ACTIVE` global.
2. Add `is_gemini_runtime()` — checks if `GEMINI_HOOK_INPUT` is non-empty.
3. Update `emit_block()` — add Gemini path: `{"decision":"deny","reason":"..."}` via `python3 -c` for JSON escaping.
4. Update commit instructions — same `resolve_commit_instruction()` pattern as Phase 1.
5. Call `read_hook_input` at script entry (before `check_sibling_repos`).

### Phase 3: Add Gemini runtime support to `tools/sase_core_stop_hook`

**File:** `tools/sase_core_stop_hook`

1. Same `read_hook_input()`, `is_gemini_runtime()`, `emit_block()` updates as Phase 2.
2. Fix `print_cmd_to_user()` — redirect to stderr (`>&2`) so progress messages don't corrupt Gemini's JSON stdout
   channel. This is harmless for Claude/Codex since they already read stderr.
3. Call `read_hook_input` at the start of `run()`.

### Phase 4: Update `.gemini/settings.json`

**File:** `.gemini/settings.json`

Replace `SessionEnd` with `AfterAgent`. Add `sase_core_stop_hook` (matching Claude's configuration which runs quality
checks). Structure as separate hook groups so they run in sequence (core checks first, then commit orchestration):

```json
{
  "hooks": {
    "AfterAgent": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"$GEMINI_PROJECT_DIR\"/tools/sase_core_stop_hook",
            "timeout": 300000
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"$GEMINI_PROJECT_DIR\"/tools/sase_sibling_commit_stop_hook",
            "timeout": 60000
          },
          {
            "type": "command",
            "command": "sase_commit_stop_hook",
            "timeout": 60000
          }
        ]
      }
    ]
  }
}
```

### Phase 5: Remove CommitWorkflow fallback from xprompt steps

**Files:** `src/sase/xprompts/commit.yml`, `src/sase/xprompts/pr.yml`, `src/sase/xprompts/propose.yml`

In each file, simplify the `create`/`propose` step to **only** read `commit_result.json` (the short-circuit path).
Remove the `CommitWorkflow` fallback invocation. If the stop hook didn't create the result file, the step reports
`success=false`.

Example for `commit.yml`:

```yaml
- name: create
  hidden: true
  if: "{{ check_changes.has_changes }}"
  python: |
    import json, os
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "")
    result_file = os.path.join(artifacts_dir, "commit_result.json") if artifacts_dir else ""
    if result_file and os.path.isfile(result_file):
        with open(result_file) as f:
            d = json.load(f)
        print("success=true")
        print(f"new_commit={d.get('result', '') or ''}")
    else:
        print("success=false")
  output:
    success: bool
    new_commit: word
```

Same pattern for `pr.yml` (read `pr_url`) and `propose.yml` (read `proposal_id`).

## Files Changed

| File                                        | Change                                                          |
| ------------------------------------------- | --------------------------------------------------------------- |
| `src/sase/scripts/sase_commit_stop_hook.py` | Add Gemini runtime detection, stdin parsing, deny JSON output   |
| `tools/sase_sibling_commit_stop_hook`       | Add Gemini runtime support to bash emit_block                   |
| `tools/sase_core_stop_hook`                 | Add Gemini runtime support, fix print_cmd_to_user stdout→stderr |
| `.gemini/settings.json`                     | `SessionEnd` → `AfterAgent`, add `sase_core_stop_hook`          |
| `src/sase/xprompts/commit.yml`              | Remove CommitWorkflow fallback from create step                 |
| `src/sase/xprompts/pr.yml`                  | Remove CommitWorkflow fallback from create step                 |
| `src/sase/xprompts/propose.yml`             | Remove CommitWorkflow fallback from propose step                |

## Risks

1. **Stdin consumption**: `read_hook_input` / `_read_gemini_stdin()` reads all of stdin once. Guarded by `isatty()`/
   `[ ! -t 0 ]` to avoid hanging when stdin is a terminal (Claude/Codex case).

2. **No fallback**: Removing the CommitWorkflow fallback means if the stop hook fails for any reason (timeout, crash,
   misconfiguration), no commit will be created. The `report` step will output empty metadata. This is acceptable
   because: (a) the fallback was a workaround, not a feature, and (b) silent commit creation without agent involvement
   masks bugs in the hook system.

3. **Gemini CLI version**: `AfterAgent` support requires a sufficiently recent Gemini CLI version. If the user's CLI
   doesn't support it, hooks will silently not fire (same as `SessionEnd` today, but now intentionally the failure
   mode).
