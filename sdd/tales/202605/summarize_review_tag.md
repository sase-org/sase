---
create_time: 2026-05-06 21:49:18
status: done
---
# Plan: Tag summarize-hook agents as review agents

## Goal

Make summarize-hook agents behave like the other axe review agents in the Agents tab. New summarize-hook runs should be
visible by default and grouped under the existing `review` tag. Reconstructed summarize-hook rows from ChangeSpec hook
suffixes should also be visible and tagged `review`.

## Current behavior

The current review-tag support is already in place for CRS, mentor, and fix-hook:

- `sase.ace.agent_tags.REVIEW_AGENT_TAG` defines the tag value as `review`.
- `sase.axe.runner_utils.detect_write_and_persist_review_agent_meta()` writes `agent_meta.json` with `tag: "review"` and
  persists the matching identity in `~/.sase/agent_tags.json`.
- ChangeSpec loaders tag CRS, mentor, and fix-hook rows directly when the row is reconstructed from COMMENTS, MENTORS,
  or HOOKS.
- RUNNING-field reconstruction treats mentor, CRS, and fix-hook workflow claims as review agents.

Summarize-hook is still the exception:

- `src/sase/axe/summarize_hook_runner.py` calls `detect_and_write_agent_meta(...)` with no tag, so its `agent_meta.json`
  does not carry `tag: "review"`.
- Both summarize-hook `write_done_marker(...)` calls omit `hidden=False`, so completed summarize rows still write
  `hidden: true`.
- `src/sase/ace/tui/models/_loaders/_changespec_loaders.py` sets `is_review_agent = workflow == "fix-hook"`, which
  leaves ChangeSpec-derived summarize-hook rows hidden and untagged.
- `src/sase/ace/tui/models/_loaders/_running_loaders.py` does not recognize `axe(summarize_hook)` /
  `axe(summarize-hook)` as a review workflow if such a claim exists.

## Implementation plan

1. Update the summarize-hook runner metadata path.
   - In `src/sase/axe/summarize_hook_runner.py`, import `detect_write_and_persist_review_agent_meta` instead of the
     generic `detect_and_write_agent_meta`.
   - After creating the artifacts directory, call
     `detect_write_and_persist_review_agent_meta(artifacts_dir, project_file, changespec_name)`.
   - This writes `agent_meta.json` with `tag: "review"` and stores the normalized artifact timestamp identity in
     `agent_tags.json`, matching how CRS, mentor, and fix-hook bypass the normal `%tag:` prompt parser.

2. Make completed summarize-hook rows visible by default.
   - In both summarize-hook completion paths, pass `hidden=False` to `write_done_marker(...)`:
     - the metahook early-return path
     - the normal success/failure finalization path
   - Keep error reporting, notifications, hook suffix updates, telemetry, and fix-hook chaining behavior unchanged.

3. Tag ChangeSpec-derived summarize-hook rows as review agents.
   - In `load_agents_from_hooks(...)`, change the review-agent predicate from fix-hook-only to include summarize-hook.
   - Result: HOOKS rows with `summarize_hook-<pid>-<timestamp>` or summarize-hook error suffixes load with
     `hidden=False` and `tag=REVIEW_AGENT_TAG`.
   - Keep workflow detection based on existing suffix content so fix-hook vs summarize-hook classification remains
     unchanged.

4. Recognize summarize-hook workflow claims as review agents.
   - Extend `_is_review_agent_workflow_claim(...)` in `_running_loaders.py` to include the normalized
     `axe(summarize_hook)` prefix.
   - This is mostly defensive because summarize-hook currently does not claim a workspace, but it keeps the review-agent
     contract consistent if claims are added later or appear from older/alternate launch paths.

5. Add focused tests.
   - Update `tests/test_agent_loader_changespec.py::test_load_all_agents_with_summarize_agents` to expect
     `hidden is False` and `tag == REVIEW_AGENT_TAG`.
   - Add or update a RUNNING-claim loader test so `axe(summarize-hook)-<timestamp>` is visible and tagged `review`.
   - Add a summarize-runner test that patches the expensive external pieces and verifies:
     - the runner calls the review metadata helper with the ChangeSpec name
     - `write_done_marker(...)` receives `hidden=False`
   - If practical, cover both the normal summarize path and the metahook early-return path, because both write done
     markers.

## Verification

Run the focused tests first:

```bash
uv run pytest tests/test_agent_loader_changespec.py tests/test_agent_loader.py tests/test_axe_runner_utils.py
```

If adding a dedicated summarize-runner test in another file, include that file in the focused run.

Before final response after implementation, follow repo guidance:

```bash
just install
just check
```

`just install` is required before repo-level checks because this workspace may have stale editable installs or native
bindings.

## Non-goals

- Do not rename summarize-hook to a separate tag such as `summarize`; the user explicitly requires the tag value to be
  `review`.
- Do not change hook eligibility, summary generation, metahook behavior, or the automatic summarize -> fix-hook
  chaining.
- Do not migrate historical `done.json` files that already contain `hidden: true`. This plan changes new runner output
  and live/reconstructed loader behavior.
