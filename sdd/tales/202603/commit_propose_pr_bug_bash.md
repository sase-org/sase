---
status: done
create_time: 2026-03-24 20:33:48
prompt: sdd/prompts/202603/commit_propose_pr_bug_bash.md
---

# Bug Bash: commit / propose / PR xprompt workflows

## Context

The commit.yml, propose.yml, and pr.yml xprompt workflows were recently refactored (commit f922b42) to add
`check_changes` and `create` post-steps that enable these workflows to run via both:

1. **Stop-hook path** (Claude/IDE): Stop hook intercepts and commits, writes `commit_result.json`, post-steps read it
2. **Agent dispatch path** (Gemini/fix-hook/CRS): Post-steps run `CommitWorkflow` directly when no `commit_result.json`
   exists

Two callers use `expand_embedded_workflows_in_query` + `execute_standalone_steps` for the agent dispatch path:

- `fix_hook_runner.py`
- `crs.py`

## Bugs Found

### Bug 1: Shell quoting in `report` bash steps (security/correctness)

All three workflows have a `report` bash step that does:

```bash
eval "$(python3 -c "
import json, shlex
d = json.load(open('$RESULT_FILE'))
...")"
```

`$RESULT_FILE` is interpolated into a Python string literal with single quotes. If the artifacts dir path contains a
single quote, this breaks. Fix: pass as env var or use escaped double quotes.

### Bug 2: Unclosed file handles in `create`/`propose` python steps

All three workflows use `json.load(open(result_file))` which opens a file handle without closing it. Fix: use
`with open(...)`.

### Bug 3: `report` step runs unconditionally (no `if` guard)

The `create`/`propose` step is gated by `if: "{{ check_changes.has_changes }}"`, but the `report` step is not. While it
handles missing files gracefully (`[ -f "$RESULT_FILE" ] || exit 0`), it should be gated for consistency and to avoid
emitting empty metadata.

### Bug 4: pr.yml doesn't pass `bug_id` to CommitWorkflow payload

pr.yml sets `SASE_BUG_ID` in environment but the `create` python step only passes `message` and `name` in the payload.
The `bug_id` input variable is available but not forwarded to `CommitWorkflow`.

### Bug 5 (deferred): Environment variable leakage

Environment injection via `os.environ` is never cleaned up. This is a design-level issue that would require a larger
refactor — note but don't fix in this pass.

### Bug 6 (deferred): CRS/fix-hook hardcode `"propose"` step name

Both `crs.py` and `fix_hook_runner.py` do `ewf_result.context.get("propose", {})` — only works for `#propose`. This
coupling is fragile but changing it requires rethinking the output extraction pattern.

## Plan

### Phase 1: Fix `report` step conditional guards (Bug 3)

Add `if: "{{ check_changes.has_changes }}"` to the `report` step in commit.yml, propose.yml, and pr.yml.

**Files**: `src/sase/xprompts/commit.yml`, `src/sase/xprompts/propose.yml`, `src/sase/xprompts/pr.yml`

### Phase 2: Fix unclosed file handles (Bug 2)

Replace `json.load(open(result_file))` with `with open(...)` blocks in the python steps of all three workflows.

**Files**: same three xprompt files

### Phase 3: Fix shell quoting in report steps (Bug 1)

Pass `$RESULT_FILE` via env var to the inline Python, or use proper quoting to handle paths with special characters.

**Files**: same three xprompt files

### Phase 4: Pass `bug_id` to CommitWorkflow payload in pr.yml (Bug 4)

Add `bug_id` to the payload dict, reading from the Jinja2 `bug_id` variable.

**Files**: `src/sase/xprompts/pr.yml`

### Phase 5: Run tests

Run `just check` to verify nothing breaks.
