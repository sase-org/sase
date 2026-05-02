---
create_time: 2026-05-01 22:56:28
status: done
prompt: sdd/prompts/202605/cd_chat_filename.md
---
# Plan: Fix `#cd` Chat Filename Paths

## Problem

`#cd` launches use the directory reference as the agent `cl_name`. For refs such as `~/org`, that value is later passed
as `branch_or_workspace` when predicting and saving the ace-run chat transcript. `generate_chat_filename()` currently
uses the branch/workspace string directly, so the generated basename can contain path separators:

```text
~/org-ace_run-260501_225009
```

When that basename is handed to `sharded_path("chats", ...)`, it becomes a nested path under the month shard:

```text
~/.sase/chats/202605/~/org-ace_run-260501_225009.md
```

The sharding helper creates only the shard directory, not arbitrary nested parents, so saving the chat fails with
`FileNotFoundError`. This matches the Telegram screenshot.

## Scope

Fix chat transcript filename generation centrally so any workflow whose branch/workspace label contains slashes or other
unsafe path characters produces a real filename, not a nested path. Keep display labels and agent names unchanged; only
the on-disk chat basename should be sanitized.

## Approach

1. Update `sase.history.chat.generate_chat_filename()` to sanitize every filename component that can originate from
   user/project/workflow data before joining with `-`.
2. Reuse the existing `sase.core.paths.make_safe_filename()` policy for consistency with hooks, diffs, checks, and other
   SASE artifact filenames.
3. Keep the timestamp untouched so sharding and duration extraction continue to work.
4. Add regression tests in `tests/history/test_chat.py` covering:
   - explicit `branch_or_workspace="~/org"` no longer creates a slash-containing basename;
   - `save_chat_history()` can write a chat for that branch/workspace and returns a path under the expected month shard;
   - existing simple names still produce the current filename shape except for the already-established workflow dash to
     underscore normalization.
5. Run targeted chat tests first, then `just install` and `just check` per repository instructions.

## Risks

This changes chat filenames for branch/workspace names containing characters outside `[a-zA-Z0-9_]`. That is already the
artifact filename convention elsewhere in SASE and is preferable to allowing invalid/nested paths. Existing transcripts
remain discoverable because lookup scans current and legacy shard locations by filename; this change only affects newly
written transcripts.
