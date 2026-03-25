# Research: Gemini CLI Stop Hook Equivalent for sase_commit_stop_hook

## Background

### What the Claude Code Stop Hook Does

Claude Code has a `Stop` hook event that fires when the agent is about to send its final response. The
`sase_commit_stop_hook` script (configured in `.claude/settings.json`) uses this to:

1. Detect uncommitted changes when `SASE_COMMIT_METHOD` is set (commit xprompt workflow)
2. Block the agent (exit code 2 + stderr message) telling it to use `/sase_git_commit` or `/sase_hg_commit`
3. The agent resumes, invokes the commit skill, which runs `CommitWorkflow` and writes `commit_result.json`
4. The xprompt post-steps read `commit_result.json` and report the result

The key value of this flow is that the **agent composes the commit message interactively** (via the skill), rather than
using a generic message like `"[agent] Agent changes"`.

### Current Gemini Situation

The `.gemini/settings.json` currently configures a `SessionEnd` hook pointing to `sase_commit_stop_hook`. This does not
work because:

- `SessionEnd` is **best-effort** -- the CLI does not wait for it to complete
- `SessionEnd` **cannot block** the agent or inject messages into the conversation
- `SessionEnd` **cannot force the agent to retry** or take additional actions

The xprompt workflows have a fallback path (the `create` step) that directly invokes `CommitWorkflow` without agent
interaction, producing generic commit messages. This works but loses the interactive commit message composition.

---

## Gemini CLI Hook System Overview

Gemini CLI (v0.26.0+) supports **11 hook event types**. Hooks communicate via **stdin** (JSON input) and **stdout**
(JSON output). Exit codes: 0 = success (parse stdout), 2 = system block (use stderr as reason), other = non-fatal
warning.

### Relevant Event Types

| Event         | When                               | Can Block?               | Can Force Retry?             |
| ------------- | ---------------------------------- | ------------------------ | ---------------------------- |
| `SessionEnd`  | Session ends (exit, clear)         | No                       | No                           |
| `AfterAgent`  | Agent loop ends (final response)   | Yes (`continue: false`)  | **Yes** (`decision: "deny"`) |
| `BeforeTool`  | Before tool executes               | Yes (`decision: "deny"`) | No                           |
| `AfterTool`   | After tool executes                | Yes                      | Can chain tools              |
| `BeforeAgent` | After user prompt, before planning | Yes                      | No                           |

### AfterAgent -- The Key Event

**Input** (via stdin):

```json
{
  "session_id": "string",
  "cwd": "string",
  "hook_event_name": "AfterAgent",
  "timestamp": "ISO 8601",
  "prompt": "original user prompt",
  "prompt_response": "agent's response text",
  "stop_hook_active": false
}
```

**Output** (via stdout):

```json
{
  "decision": "deny",
  "reason": "Instruction text injected as correction prompt",
  "hookSpecificOutput": {
    "clearContext": false
  }
}
```

When `decision: "deny"` is returned, the agent **retries** with `reason` injected as a correction prompt. On the retry,
`stop_hook_active` is set to `true` in the input, which can be used to prevent infinite loops.

This is semantically identical to Claude's Stop hook with exit code 2.

### Configuration Format

```json
{
  "hooks": {
    "AfterAgent": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/script.sh",
            "timeout": 60000
          }
        ]
      }
    ]
  }
}
```

### Environment Variables Available to Hooks

- `GEMINI_PROJECT_DIR`: Absolute path to project root
- `GEMINI_SESSION_ID`: Unique session ID
- `GEMINI_CWD`: Current working directory
- Any env vars set by xprompt workflows (e.g., `SASE_COMMIT_METHOD`, `SASE_ARTIFACTS_DIR`)

---

## Approaches Evaluated

### Approach 1: AfterAgent Hook (Recommended)

Use `AfterAgent` with `decision: "deny"` to replicate the Stop hook behavior.

**How it works:**

1. Agent finishes its response -> `AfterAgent` fires
2. Hook checks `SASE_COMMIT_METHOD` and uncommitted changes (same logic as current script)
3. If changes exist:
   - Returns `{"decision": "deny", "reason": "Uncommitted changes detected. Commit them now using ..."}`
   - Agent retries and commits
4. On retry, `stop_hook_active` is `true` in input -> hook allows it through (prevents infinite loop)

**Pros:**

- Semantically identical to Claude's Stop hook
- Agent can compose commit messages interactively
- Uses the same deduplication pattern (stop_hook_active replaces marker file)
- The existing bash script's core logic can be reused

**Cons:**

- Requires adapting the script to read JSON from stdin and write JSON to stdout
- Need to handle the fact that Gemini agents don't have `/sase_git_commit` skill -- the "reason" message needs to tell
  the agent what to do in Gemini-native terms (run a command, use a skill, etc.)
- AfterAgent fires on **every** agent turn, not just during commit workflows -- the `SASE_COMMIT_METHOD` check handles
  this, but it's more invocations than Claude's Stop hook

### Approach 2: AfterAgent + Gemini Skill

Same as Approach 1, but create a Gemini skill (`~/.gemini/skills/sase_git_commit/SKILL.md`) that teaches the agent how
to commit using `CommitWorkflow`.

**How it works:**

1. Create a Gemini skill that mirrors the Claude `/sase_git_commit` skill behavior
2. The AfterAgent hook's `reason` tells the agent to activate the `sase_git_commit` skill
3. The skill's `SKILL.md` instructs the agent on how to run CommitWorkflow

**Pros:**

- Closest behavioral match to Claude Code
- Agent gets structured instructions for committing (via SKILL.md)
- Skills are agent-aware -- can include VCS-specific instructions

**Cons:**

- Skills require user confirmation to activate (adds friction)
- More moving parts (hook + skill + script)
- Skill activation may not work reliably in the retry flow

### Approach 3: AfterAgent + Custom Command

Create a Gemini custom command (`.gemini/commands/sase_commit.toml`) that wraps the commit workflow.

**How it works:**

1. Create `.gemini/commands/sase_commit.toml` with a prompt that tells the agent to commit
2. AfterAgent hook's `reason` tells the agent to run `/sase_commit`
3. The custom command prompt instructs the agent to invoke CommitWorkflow

**Pros:**

- Custom commands are simpler than skills (no activation step)
- Can embed dynamic content via `!{shell command}` syntax
- Natural `/sase_commit` command name matches Claude's `/sase_git_commit`

**Cons:**

- Custom commands are essentially prompt templates, not executable workflows
- Can't directly invoke CommitWorkflow -- relies on the agent interpreting the prompt correctly
- VCS-specific logic would need to be in the prompt text

### Approach 4: AfterAgent + Direct CommitWorkflow Invocation

The hook itself invokes CommitWorkflow directly (no agent interaction).

**How it works:**

1. AfterAgent hook detects uncommitted changes
2. Hook directly runs `python -c "from sase.workflows.commit import CommitWorkflow; ..."`
3. Returns `continue: false` after committing

**Pros:**

- Simplest implementation
- No agent retry needed
- Guaranteed to work (no reliance on agent behavior)

**Cons:**

- Loses the interactive commit message composition (same problem as current fallback)
- Agent can't review or customize the commit
- Doesn't achieve "same behavior" as Claude's Stop hook

### Approach 5: Unified Script with Multi-Runtime Protocol Detection

Modify the existing `sase_commit_stop_hook` to detect its runtime and speak the appropriate protocol.

**How it works:**

1. Detect runtime via environment variables:
   - Claude: `CLAUDE_PROJECT_DIR` is set
   - Codex: `CODEX_THREAD_ID` or `CODEX_CI` is set
   - Gemini: `GEMINI_SESSION_ID` or `GEMINI_PROJECT_DIR` is set
2. Read input appropriately (Gemini: JSON from stdin; Claude/Codex: no stdin)
3. Emit output in the correct protocol:
   - Claude: stderr + exit 2
   - Codex: JSON stdout + exit 0
   - Gemini: JSON stdout with `decision: "deny"` + exit 0
4. For Gemini, use `stop_hook_active` from stdin JSON for deduplication instead of marker file

**Pros:**

- Single script to maintain
- Consistent behavior across all runtimes
- Natural extension of existing multi-runtime pattern (already handles Claude + Codex)
- Can be configured in both `.claude/settings.json` (Stop) and `.gemini/settings.json` (AfterAgent)

**Cons:**

- Script complexity increases
- Testing across runtimes becomes more important
- Different hook event names in different configs (Stop vs AfterAgent)

---

## The Commit Skill Problem

The Claude Stop hook tells the agent to "use your `/sase_git_commit` skill". This works because Claude Code has a Skill
tool that invokes Claude Code skills. Gemini CLI has a different skill system:

- Skills are directories with `SKILL.md` files
- Skills require activation (agent calls `activate_skill` tool, user confirms)
- Once activated, the skill's instructions are injected into the conversation

For the AfterAgent retry, we need the agent to commit changes. Options for what to tell the agent:

1. **Run a shell command**: `reason: "Run: .venv/bin/sase commit create ..."` -- simplest but requires the agent to run
   the exact right command
2. **Activate a skill**: `reason: "Activate the sase_git_commit skill and follow its instructions"` -- may not work in
   retry context
3. **Inline instructions**: Put full commit instructions in the `reason` field -- verbose but reliable
4. **Run a custom command**: `reason: "Run /sase_commit"` -- clean but relies on custom command being set up

### Recommended: Inline Instructions in AfterAgent Reason

The most reliable approach is to put clear, complete instructions in the `reason` field. The agent is guaranteed to see
these instructions during retry. Example:

```
Uncommitted changes detected in the working directory. You must commit them now before stopping.

Changed files:
<list of files>

Instructions:
1. Review the changed files
2. Stage all changed files with git add
3. Write a clear, descriptive commit message
4. Run: .venv/bin/sase commit create --message "<your commit message>"
   (This command handles bead lifecycle, precommit hooks, and VCS-specific operations)
5. Verify the commit succeeded
```

This approach:

- Works reliably in the retry flow
- Doesn't depend on skills or custom commands being properly activated
- Gives the agent enough context to compose a good commit message
- Routes through `sase commit create` which invokes CommitWorkflow

---

## Recommendation

### Primary: Approach 5 (Unified Script) + Approach 1 (AfterAgent)

**Extend the existing `sase_commit_stop_hook` to handle Gemini's AfterAgent protocol**, configured as an `AfterAgent`
hook in `.gemini/settings.json`.

#### Implementation Plan

**1. Add Gemini runtime detection to `sase_commit_stop_hook`:**

```bash
function is_gemini_runtime() {
    [ -n "$GEMINI_SESSION_ID" ] || [ -n "$GEMINI_PROJECT_DIR" ]
}
```

**2. Read AfterAgent input from stdin (Gemini only):**

```bash
if is_gemini_runtime; then
    HOOK_INPUT=$(cat)
    STOP_HOOK_ACTIVE=$(echo "$HOOK_INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stop_hook_active', False))")
    # If this is a retry (agent already got our deny), let it through
    if [ "$STOP_HOOK_ACTIVE" = "True" ]; then
        echo '{"decision": "allow"}'
        exit 0
    fi
fi
```

**3. Extend `emit_block` to handle Gemini protocol:**

```bash
function emit_block() {
    local reason="$1"
    local details="${2:-}"

    if is_gemini_runtime; then
        local escaped_reason
        escaped_reason=$(echo "$details" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")
        printf '{"decision":"deny","reason":%s}\n' "$escaped_reason"
        return 0
    fi
    # ... existing Claude/Codex handling ...
}
```

**4. Update `.gemini/settings.json`:**

Replace the `SessionEnd` hook with `AfterAgent`:

```json
{
  "hooks": {
    "AfterAgent": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "\"$GEMINI_PROJECT_DIR\"/tools/sase_commit_stop_hook",
            "timeout": 300000
          }
        ]
      }
    ]
  }
}
```

**5. Adapt the block message for Gemini agents:**

Instead of "Use your /sase_git_commit skill", tell the agent to run the sase commit command with inline instructions
(since Gemini doesn't have the same skill invocation model).

**6. Remove `SASE_DISABLE_COMMIT_STOP_HOOK`:**

Since Gemini now has proper stop hook support via AfterAgent, the disable flag and the xprompt fallback path can be
simplified. The fallback path in xprompts should still exist (for robustness) but would be the exception rather than the
primary path.

**7. Apply the same pattern to `sase_core_stop_hook`:**

The quality-check stop hook can also be ported to Gemini using AfterAgent, giving Gemini agents the same
format-lint-test cycle that Claude agents get.

#### Why This Approach

- **Minimal new code**: Extends existing scripts rather than creating new ones
- **Consistent behavior**: Same commit flow across Claude, Codex, and Gemini
- **Natural fit**: AfterAgent's `decision: "deny"` with retry is semantically identical to Claude's Stop + exit 2
- **Built-in dedup**: `stop_hook_active` replaces the marker file hack for Gemini
- **Interactive commits**: Agent composes the commit message, not a generic fallback
- **Future-proof**: Adding new runtimes is just another `is_X_runtime()` check

#### Risks & Mitigations

| Risk                                             | Mitigation                                                  |
| ------------------------------------------------ | ----------------------------------------------------------- |
| AfterAgent fires on every turn, not just commits | `SASE_COMMIT_METHOD` check exits early (same as today)      |
| Agent ignores the retry instructions             | Inline clear instructions + sase commit command as fallback |
| Infinite retry loop                              | `stop_hook_active` check + marker file as backup            |
| stdin reading blocks if no input                 | Gemini always provides stdin JSON for hooks                 |
| Core stop hook (lint/test) takes too long        | Same timeout handling as Claude (300s timeout in config)    |
