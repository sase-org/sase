---
create_time: 2026-03-30 19:13:39
status: done
prompt: sdd/prompts/202603/fix_pylimit_split.md
---

# Fix `#sase/pylimit_split` workflow: eliminate inter-step dependency

## Problem

The `#sase/pylimit_split` workflow (commit e341f268) ran an agent to split a src/ file but never ran the agent for the
tests/ file that also needed splitting. Only one agent was launched total.

## Root Cause

`xprompts/pylimit_split.yml` has 4 sequential steps:

1. `find_src_files` (bash)
2. `find_tests_files` (bash)
3. `split_src_files` (for+agent)
4. `split_tests_files` (for+agent)

Steps 3 and 4 are **logically independent** but **sequentially dependent**. In `workflow_executor.py:325-336`, if step 3
returns `False` or raises an exception, `failure_returned_false` / `failure_exception` is set, causing step 4 to be
skipped (lines 222-235).

The agent in step 3 successfully committed (e341f268), but the step itself failed during post-processing, preventing
step 4 from ever executing.

## Fix

Consolidate from 4 steps to 2 in `xprompts/pylimit_split.yml`:

- Merge `find_src_files` + `find_tests_files` into a single `find_files` bash step
- Merge `split_src_files` + `split_tests_files` into a single `split_files` for+agent step

This eliminates the inter-step failure surface. All files are discovered together and processed in one `for` loop —
there is no step boundary between src and tests processing where a failure can cause skipping.

## Changes

### `xprompts/pylimit_split.yml`

Replace the 4-step workflow with:

```yaml
input:
  limits: { type: text, default: "1000 850 700" }
steps:
  - name: find_files
    hidden: true
    bash: |
      { tools/pylimit_files-260227 src {{ limits }}; tools/pylimit_files-260227 tests {{ limits }}; } | python3 -c "import sys, json; print('files=' + json.dumps([l.strip() for l in sys.stdin if l.strip()]))"
    output: { files: text }

  - name: split_files
    for: { file_path: "{{ find_files.files }}" }
    agent: |
      #sase/pysplit:{{ file_path }}
```

The combined bash command pipes output from both `pylimit_files` invocations (src + tests) through the same JSON
serializer. Verified working: produces `files=["tests/test_agent_loader_dedup_vcs_pid.py"]` on current repo state.
