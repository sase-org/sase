---
create_time: 2026-04-20 13:32:36
status: done
prompt: sdd/prompts/202604/fix_critique_comments_stderr_merge.md
---

# Plan: Fix `critique_comments` stderr-merge bug breaking `sase axe` comment polling

## Problem

`sase axe` polls reviewer comments for Mailed ChangeSpecs by running the external `critique_comments <changespec_name>`
shell script. On a remote machine that uses the `../retired Mercurial plugin` plugin repo, this command fails with:

```
critique_comments: error: JSON parsing failed (exit 5): jq: parse error: Invalid numeric literal at line 1, column 6
```

As a result, the `bs_allow_model` ChangeSpec (CL 898381783, status `Mailed`) never gets a `COMMENTS` field populated,
even though mentor reviews have completed and the CL has real reviewer comments to fetch.

## Root cause (empirically confirmed)

The bug is in the external `critique_comments` shell script, not in either sase repo.

**File**: `/home/bryan/.local/share/chezmoi/home/bin/executable_critique_comments` (chezmoi-managed; deployed to
`/home/bryan/bin/critique_comments` on each machine via `chezmoi apply`).

**Line 68-69**:

```bash
rpc_output=$(stubby call blade:codereview-rpc CodereviewRpcService.GetComments \
  --proto2 "changelist_number: ${cl_number}" --output_json 2>&1)
```

The `2>&1` captures **both** stdout and stderr of `stubby` into `$rpc_output`. Stubby routinely emits glog-style
informational / warning lines on stderr even when it succeeds (exit 0) — for example:

```
W0420 10:30:45.123 stubby.cc:100] Some deprecation or transient warning
{"comment":[...]}
```

With `2>&1` those lines get prepended to the JSON payload. Line 78 then pipes the combined blob to jq:

```bash
result=$(echo "$rpc_output" | jq "$@" '.comment | ...')
```

jq tries to parse the first line (`W0420 10:30:45.123 stubby.cc:100] ...`) and fails.

**Reproduction (local)**:

```
$ echo 'W0420 10:30:45.123 file.cc:100] Warning message' | jq .
jq: parse error: Invalid numeric literal at line 1, column 6
```

This matches the user's error message byte-for-byte, confirming the theory. The script then emits
`critique_comments: error: JSON parsing failed (exit $jq_exit): ...` and exits 5 (`EXIT_JSON_FAILURE`).

Downstream, `src/sase/ace/scheduler/checks_runner.py::_handle_reviewer_comments_completion` correctly observes
`exit_code != 0`, logs the failure, and returns without adding a `COMMENTS` drawer entry — which is why the
`bs_allow_model` ChangeSpec has no `COMMENTS` field.

## Fix

In `/home/bryan/.local/share/chezmoi/home/bin/executable_critique_comments`, capture stubby's stderr to a separate
tempfile instead of merging it with stdout. Preserve the existing behavior of including stderr text in the error message
on RPC failure.

**Replace lines 67-75** with:

```bash
# Make the RPC call.  Stderr is kept separate from stdout so glog-style warnings
# from stubby (e.g. "W0420 10:30:45...") do not pollute the JSON that gets piped
# to jq below.
rpc_stderr=$(mktemp)
trap 'rm -f "$rpc_stderr"' EXIT
rpc_output=$(stubby call blade:codereview-rpc CodereviewRpcService.GetComments \
  --proto2 "changelist_number: ${cl_number}" --output_json 2>"$rpc_stderr")
rpc_exit=$?

if [[ $rpc_exit -ne 0 ]]; then
  rpc_err_content=$(cat "$rpc_stderr")
  _error "RPC call failed (exit $rpc_exit): ${rpc_err_content:0:200}"
  exit $EXIT_RPC_FAILURE
fi
```

Notes:

- `trap 'rm -f "$rpc_stderr"' EXIT` ensures the tempfile is cleaned up on every exit path (success, RPC failure, jq
  failure).
- On success the JSON flowing into jq is exactly what stubby wrote to stdout — no prefix lines.
- On failure we still get the useful stderr snippet in the user-facing error (in fact it's cleaner now, since it no
  longer has any JSON tail spliced on).

## Files changed

- `~/.local/share/chezmoi/home/bin/executable_critique_comments` — the only file touched.

## Out of scope

- No changes to the `sase_100` repo. `checks_runner.py` and `workspace_plugin.py` behave correctly; they fail loudly
  when `critique_comments` exits nonzero, which is the right behavior.
- No changes to the `retired Mercurial plugin` plugin repo.
- The workspace-directory gate issue (comment checks silently skipped when `get_workspace_directory()` returns empty)
  tracked in `plans/202604/fix_comment_check_workspace_gate.md` is a separate concern and has its own WIP plan — not
  folding it in here.

## Post-edit workflow

1. Edit the chezmoi-managed file.
2. Run `just check` in `~/.local/share/chezmoi` (per the `long-external-repos.md` memory for modifications to chezmoi
   files).
3. Commit the chezmoi change.
4. Run `chezmoi apply` so the deployed copy at `/home/bryan/bin/critique_comments` picks up the fix on the current
   machine.
5. On the remote machine where the original failure was observed, pull the chezmoi repo and run `chezmoi apply` there as
   well.

## Verification

- Local smoke test — jq accepts clean stubby output:
  ```
  echo '{"comment":[]}' | jq '.comment | sort_by(.depot_path, .line_number)[]'
  ```
  should exit 0 (with no output, since the array is empty).
- On a machine with stubby access, run `critique_comments bs_allow_model`; expect exit 0 and either empty output (no
  unresolved comments) or a list of comment objects.
- On the next `sase axe` poll cycle, the `bs_allow_model` ChangeSpec should gain a `COMMENTS` drawer entry of the form
  `(1) [critique]: ~/.sase/comments/bs_allow_model-critique-<ts>.txt`.

## Risk

Very low. The change is scoped to one shell script, the logic preserves the existing error-reporting contract, and the
bug only affects a code path that is already broken. Worst case the fix is no-op (if for some reason stubby doesn't emit
stderr warnings on a given machine), which is indistinguishable from the "working" state.
