---
create_time: 2026-05-06 21:25:30
status: done
prompt: sdd/prompts/202605/review_tag_axe_agents.md
---
# Review-Tagged Axe Agents Plan

## Goal

Stop treating CRS, mentor, and fix-hook agents as hidden background entries. They should be visible in the Agents tab by
default and grouped under the `review` agent tag. The intended behavior should apply consistently while the agent is
running, after it completes, and when the row is reconstructed from ChangeSpec fields, RUNNING claims, or artifacts.

## Current Behavior

There are several independent hiding paths to remove or bypass:

- ChangeSpec-derived rows are forced hidden in `src/sase/ace/tui/models/_loaders/_changespec_loaders.py` for
  HOOKS/fix-hook, MENTORS/mentor, and COMMENTS/CRS entries.
- RUNNING-claim rows are forced hidden in `src/sase/ace/tui/models/_loaders/_running_loaders.py` for `axe(mentor)`,
  `axe(fix-hook)`, `axe(crs)`, and `mentor(...)` workflow names.
- Standalone axe runner completions write `hidden: true` in `src/sase/axe/runner_utils.py::write_done_marker`, which
  affects completed CRS, mentor, and fix-hook artifact rows.
- Generic `%tag` directive support already exists in `src/sase/xprompt/directives.py` and persists tags through
  `src/sase/axe/run_agent_phases.py`, but the specialized axe CRS/mentor/fix-hook runners do not go through that
  prompt-directive extraction path.

## Design

Use `review` as the single canonical tag for CRS, mentor, and fix-hook agents. Keep the existing xprompt role tags
(`crs`, `mentor`, `fix_hook`) unchanged because they resolve workflow content and are not the same as Agents-tab
grouping tags.

For generic agent launches, continue relying on the existing `%tag:review` directive. For the specialized axe runners,
add a small shared helper around the existing tag persistence and metadata writing so these runners produce the same
observable state as a `%tag:review` launch:

- `agent_meta.json` should include `"tag": "review"`.
- `~/.sase/agent_tags.json` should receive the row identity with tag `review` when the identity is known.
- `done.json` should stop carrying `hidden: true` for these agents.

The helper should be centralized rather than duplicating tag-store details in each runner. It should be explicit enough
that summarize-hook and unrelated axe infrastructure do not accidentally get the review tag.

## Implementation Steps

1. Introduce a shared review-tag constant/helper.
   - Add a small function in the axe runner utility layer that can write metadata with `tag="review"` and persist the
     tag for a known `(AgentType, cl_name, raw_suffix)` identity.
   - Keep validation through the existing `sase.ace.agent_tags` APIs.

2. Update specialized runner metadata and done markers.
   - CRS runner: write/persist the `review` tag for its workflow identity and stop producing hidden completed rows.
   - Mentor runner: same, using the `mentor-<name>` artifacts directory identity.
   - Fix-hook runner: same, using the `fix-hook` artifacts directory identity.
   - Do not change summarize-hook unless tests reveal it shares a helper that would otherwise force hidden behavior.

3. Remove hardcoded hidden defaults for these review agents in loaders.
   - ChangeSpec loader rows for CRS, mentor, and fix-hook should be visible by default and carry `tag="review"` directly
     when loaded from ChangeSpec fields.
   - RUNNING-claim loader should stop marking `axe(crs)`, `axe(fix-hook)`, and `axe(mentor)` rows hidden; it should
     apply `tag="review"` instead.
   - Leave non-agent workflow children and genuinely hidden prompt-directed agents alone.

4. Preserve deduplication and cleanup behavior.
   - Revisit tests that mention "hidden fix-hook" because they often exist to prevent duplicate embedded VCS rows. The
     invariant should become "review-tagged ChangeSpec fix-hook row still wins deduplication" rather than "hidden row
     wins."
   - Keep kill/dismiss/cleanup classification based on workflow names, not hidden state.

5. Add focused tests.
   - Unit test that `write_done_marker` or its new wrapper can write review-tagged done metadata without `hidden: true`.
   - Loader tests for ChangeSpec CRS, mentor, and fix-hook rows: visible by default and `tag == "review"`.
   - RUNNING-claim loader test for `axe(fix-hook)` or `axe(crs)`: visible by default and `tag == "review"`.
   - Update existing dedup tests to assert the same duplicate-removal behavior without relying on `hidden=True`.
   - Keep existing `%tag` directive tests unchanged, and add one integration-style assertion only if the specialized
     helper touches the same tag store.

6. Verify.
   - Run targeted tests around agent loading, tags, axe runner utilities, and deduplication.
   - Run `just install` first if needed for this workspace, then `just check` before finishing code changes.

## Risks and Decisions

- The term `tag` is overloaded: xprompt role tags choose workflow implementations, while Agents-tab tags group agent
  rows. This change should only alter Agents-tab tags.
- The specialized axe runners currently bypass prompt-directive parsing, so literally prepending `%tag:review` to their
  LLM prompt would leak an implementation directive into model instructions. The safer design is to make their persisted
  metadata/tag-store state match the result of the `tag` directive instead.
- Existing completed hidden entries may remain hidden in historical artifacts because their `done.json` files already
  contain `hidden: true`. This plan changes new and reloaded rows going forward; migration of old artifacts is out of
  scope unless requested.
