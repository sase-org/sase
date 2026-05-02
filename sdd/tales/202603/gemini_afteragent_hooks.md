---
create_time: 2026-03-24 21:37:12
status: wip
prompt: sdd/prompts/202603/gemini_afteragent_hooks.md
---

# Implement Gemini CLI AfterAgent Stop Hooks

## Problem

`.gemini/settings.json` registers `sase_commit_stop_hook` on the `SessionEnd` event. `SessionEnd` is fire-and-forget —
Gemini CLI does **not** wait for it to complete and ignores all flow-control fields. The hook cannot block the agent or
force a retry, so the commit-orchestration stop hook is effectively a no-op for Gemini agents.

Meanwhile, Claude Code's `Stop` hook fires both `sase_core_stop_hook` (quality checks) and `sase_commit_stop_hook`
(commit orchestration). Both can block via exit code 2 + stderr, and the agent retries with the stderr message as a
correction prompt.

## Solution

Use Gemini CLI's **`AfterAgent`** hook event — the direct equivalent of Claude's `Stop` hook:

- Returns `{"decision":"deny","reason":"..."}` on stdout → agent retries with `reason` as correction prompt
- Input JSON includes `stop_hook_active: true` on retries → built-in deduplication (replaces our marker file hack)
- Exit code 2 also works (stderr becomes the reason), matching the existing Claude/Codex multi-runtime pattern

### Design Principle: Extend `emit_block`, Don't Fork

Both hook scripts already have a multi-runtime `emit_block()` function (Codex → JSON stdout, Claude → stderr + exit 2).
We add Gemini as a third runtime in the same function. The Gemini path reads `stop_hook_active` from stdin JSON for
deduplication instead of using the marker file.

## Changes

### Phase 1: Extract shared hook helpers into a library

Both scripts duplicate `get_changed_files()`, `is_codex_runtime()`, and `emit_block()`. Before adding Gemini as a third
runtime, extract these into `tools/lib/hook_helpers.sh` to avoid tripling the duplication.

**Create `tools/lib/hook_helpers.sh`** with:

- `get_changed_files()` — unchanged
- `is_codex_runtime()` — unchanged
- `is_gemini_runtime()` — new: checks if stdin has JSON with `hook_event_name`
- `read_gemini_input()` — new: reads stdin JSON once, caches in `GEMINI_HOOK_INPUT` global; extracts `stop_hook_active`
  into `GEMINI_STOP_HOOK_ACTIVE` global
- `emit_block()` — extended with Gemini path: outputs `{"decision":"deny","reason":"..."}` on stdout + exit 0

**Update both scripts** to `source "$SCRIPT_DIR/lib/hook_helpers.sh"` and remove their local copies.

### Phase 2: Add Gemini runtime detection and stdin JSON parsing

**`tools/lib/hook_helpers.sh`:**

```bash
# Global state populated by read_gemini_input
GEMINI_HOOK_INPUT=""
GEMINI_STOP_HOOK_ACTIVE=""

# Read Gemini hook input from stdin (call once at script start).
# Gemini passes JSON on stdin; Claude/Codex do not.
function read_hook_input() {
    # Only read if stdin is not a terminal (i.e., piped)
    if [ ! -t 0 ]; then
        GEMINI_HOOK_INPUT="$(cat)"
        if [ -n "$GEMINI_HOOK_INPUT" ]; then
            # Extract stop_hook_active using lightweight parsing
            GEMINI_STOP_HOOK_ACTIVE=$(echo "$GEMINI_HOOK_INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print('true' if d.get('stop_hook_active') else 'false')
except Exception:
    print('false')
" 2>/dev/null)
        fi
    fi
}

function is_gemini_runtime() {
    [ -n "$GEMINI_HOOK_INPUT" ]
}
```

**`emit_block()` — Gemini path:**

```bash
function emit_block() {
    local reason="$1"
    local details="${2:-}"

    if is_gemini_runtime; then
        # Gemini: structured JSON on stdout. Use python for proper JSON escaping.
        local full_reason="$reason"
        [ -n "$details" ] && full_reason="$details"
        python3 -c "
import json, sys
print(json.dumps({'decision': 'deny', 'reason': sys.argv[1]}))
" "$full_reason"
        return 0
    fi

    if is_codex_runtime; then
        printf '{"decision":"block","reason":"%s"}\n' "$reason"
        [ -n "$details" ] && echo -e "$details" >&2
        return 0
    fi

    # Claude: stderr + exit 2
    if [ -n "$details" ]; then
        echo -e "$details" >&2
    else
        echo "$reason" >&2
    fi
    return 2
}
```

### Phase 3: Update `sase_commit_stop_hook` for Gemini deduplication

Replace the marker file logic with a runtime-aware deduplication check:

```bash
function run() {
    cd "$PROJECT_DIR" || return 1

    # Read hook input (populates GEMINI_HOOK_INPUT, GEMINI_STOP_HOOK_ACTIVE)
    read_hook_input

    # Log
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] sase_commit_stop_hook ran (method=$SASE_COMMIT_METHOD)" \
        >>"$PROJECT_DIR/.claude/hooks.log"

    # --- Deduplication ---
    if is_gemini_runtime; then
        # Gemini: use native stop_hook_active field
        if [ "$GEMINI_STOP_HOOK_ACTIVE" = "true" ]; then
            return 0
        fi
    else
        # Claude/Codex: use marker file
        local marker_file="/tmp/sase_commit_stop_hook_${TMUX_PANE_ID:-default}"
        if [ -f "$marker_file" ]; then
            rm -f "$marker_file"
            return 0
        fi
    fi

    # ... rest of change detection and emit_block calls ...
}
```

**Commit instructions for Gemini:** Since Gemini agents don't have `/sase_git_commit` skill, the deny reason must
include inline instructions. Replace `resolve_commit_skill()` calls for Gemini with direct CLI instructions:

```bash
function resolve_commit_instruction() {
    if is_gemini_runtime; then
        # Gemini: no skill available, use CLI directly
        echo "Run: .venv/bin/sase commit create --message '<your commit message>' to commit the changes"
    else
        echo "Use your $(resolve_commit_skill) skill to commit these changes now."
    fi
}
```

### Phase 4: Update `sase_core_stop_hook` for Gemini

Same changes: call `read_hook_input` at the start, `emit_block` handles the rest automatically since it already
dispatches by runtime. No deduplication changes needed here — the core hook doesn't use marker files.

The `print_cmd_to_user` function currently writes to stdout, which would corrupt Gemini's JSON output. Fix it to always
write to stderr:

```bash
function print_cmd_to_user() {
    local group="$1"
    local cmd="$2"
    echo "[sase_core_stop_hook:${group}] Running \`$cmd\`..." >&2
}
```

### Phase 5: Update `.gemini/settings.json`

Replace `SessionEnd` with `AfterAgent`, add both hooks (matching Claude's configuration):

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
            "command": "\"$GEMINI_PROJECT_DIR\"/tools/sase_commit_stop_hook",
            "timeout": 60000
          }
        ]
      }
    ]
  }
}
```

### Phase 6: Update `tools/AGENTS.md` documentation

Update the hook script descriptions to mention Gemini support and the three-runtime protocol.

## Files Changed

| File                          | Change                                                                                                                   |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `tools/lib/hook_helpers.sh`   | **New** — shared helpers: `read_hook_input`, `is_gemini_runtime`, `is_codex_runtime`, `get_changed_files`, `emit_block`  |
| `tools/sase_commit_stop_hook` | Source helpers, remove duplicated functions, add Gemini dedup via `stop_hook_active`, add `resolve_commit_instruction()` |
| `tools/sase_core_stop_hook`   | Source helpers, remove duplicated functions, fix `print_cmd_to_user` to use stderr                                       |
| `.gemini/settings.json`       | `SessionEnd` → `AfterAgent`, add `sase_core_stop_hook`                                                                   |
| `tools/AGENTS.md`             | Update docs for three-runtime support                                                                                    |

## Risks and Mitigations

1. **Stdin consumption**: `read_hook_input` reads all of stdin. If called multiple times or if stdin is a terminal, it
   could hang. Mitigation: guard with `[ ! -t 0 ]` check, call exactly once at script entry.

2. **Python dependency for JSON**: `emit_block` uses `python3 -c` for proper JSON escaping. This is acceptable since
   sase already requires Python 3.12+. Using bash string manipulation for JSON escaping is fragile.

3. **Gemini timeout units**: Gemini uses milliseconds (300000ms = 5min), Claude uses seconds (300s = 5min). The config
   already uses ms correctly.

4. **`print_cmd_to_user` stdout corruption**: The core hook's progress messages go to stdout, which would corrupt
   Gemini's JSON output channel. Fixed by redirecting to stderr in Phase 4.
