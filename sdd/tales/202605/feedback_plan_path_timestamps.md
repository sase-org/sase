---
create_time: 2026-05-06 19:28:17
status: done
prompt: sdd/prompts/202605/feedback_plan_path_timestamps.md
---
# Append Rejected Plan Paths to FBACK Timestamps

## Goal

On the `sase ace` TUI Agents tab, the agent metadata panel currently renders feedback events as timestamp-only rows such
as:

```text
FBACK | 2026-05-06 19:21:24
```

After this change, each feedback row should append the path of the plan that was rejected when the user submitted that
feedback:

```text
FBACK | 2026-05-06 19:21:24 | ~/.sase/plans/foobar.md
```

The display should work for the root `.plan` entry and for plan-chain feedback rounds (`.2`, `.3`, ...), including the
normal parent metadata-panel view where feedback round timestamps are propagated back onto the root plan agent.

## Current Behavior and Relevant Flow

The existing execution path already records the data needed for this display:

- `src/sase/axe/run_agent_exec_plan.py` records `plan_path` when a plan is submitted and records `feedback_submitted_at`
  when the user rejects a plan with feedback.
- `create_followup_artifacts()` in `src/sase/axe/run_agent_helpers.py` writes follow-up `agent_meta.json` files
  containing `plan_path` and `feedback_submitted_at` for feedback round agents.
- The Rust/Python artifact scan wire already exposes both `AgentMetaWire.plan_path` and
  `AgentMetaWire.feedback_submitted_at`; the sibling Rust scanner already parses both fields, so this does not need a
  new Rust schema field.
- The TUI loader currently parses feedback timestamps into `Agent.feedback_times: list[datetime]`, but it discards the
  associated plan path.
- `apply_status_overrides()` propagates feedback-round timestamps to the root plan entry, but only as bare datetimes.
- `Agent.timestamps_display` formats all timestamp rows and currently has no way to add per-feedback metadata.

## Proposed Design

Add a small TUI model field that preserves the association between each feedback timestamp and the plan path rejected at
that time.

1. Extend `Agent` with a display-oriented field such as:

   ```python
   feedback_plan_paths: dict[datetime, str]
   ```

   This keeps existing `feedback_times` behavior intact for runtime/status logic while allowing `timestamps_display` to
   look up an optional path for a specific `FBACK` event.

2. Populate that mapping during metadata enrichment:
   - In `enrich_agent_from_meta()`, when `agent_meta.json` has `feedback_submitted_at` and `plan_path`, parse the
     feedback timestamp(s) as today and record `timestamp -> plan_path`.
   - In `enrich_agent_from_meta_wire()`, mirror the same logic using `AgentMetaWire.feedback_submitted_at` and
     `AgentMetaWire.plan_path`.
   - Handle both scalar and list-shaped `feedback_submitted_at` inputs, matching the current loader behavior.
   - If no `plan_path` exists, keep the current bare `FBACK | timestamp` rendering.

3. Propagate the mapping alongside feedback timestamps in `apply_status_overrides()`:
   - When a feedback-round child propagates `feedback_times` to its root plan parent, also copy matching
     `feedback_plan_paths` entries.
   - Make this idempotent, preserving the current no-duplicate behavior when status overrides run repeatedly.
   - If a timestamp already exists on the parent with a path, do not replace it with an empty/missing path. If a
     timestamp exists without a path and the child has one, fill it in.

4. Update `Agent.timestamps_display`:
   - Keep chronological ordering exactly as today.
   - For `FBACK` rows only, append ` | <path>` when a path exists for that feedback timestamp.
   - Use the existing `sase.core.paths.shorten_path()` helper so absolute home paths display as `~`.
   - Leave `PLAN`, `QUEST`, `CODE`, `EPIC`, `RETRY`, `BEGIN`, `WAIT`, and `END` output unchanged.

5. Preserve dismissed bundle compatibility:
   - `Agent.to_bundle_dict()` already serializes dataclass fields generically, but `Agent.from_bundle_dict()` needs to
     deserialize a `dict[str, str]` form for `feedback_plan_paths` because JSON/dismissed bundles cannot use datetimes
     as keys.
   - Store the mapping in bundles as ISO timestamp strings to path strings.
   - Continue loading older bundles that lack this field with an empty mapping.

## Tests

Add focused tests rather than a broad TUI integration test.

1. `tests/test_agent_model_timestamps.py`
   - Assert `timestamps_display` renders `FBACK | <timestamp> | ~/.sase/plans/foo.md` when `feedback_plan_paths` has a
     matching entry.
   - Assert feedback rows remain bare when the mapping is empty.
   - Assert multiple feedback rows keep chronological order and only the matching feedback row gets its own path.

2. `tests/test_enrich_agent_wait_duration.py` or a new adjacent metadata-enrichment test
   - Filesystem path: `agent_meta.json` with `feedback_submitted_at` plus `plan_path` populates both `feedback_times`
     and `feedback_plan_paths`.
   - Wire path: `AgentMetaWire(feedback_submitted_at=[...], plan_path=...)` produces the same state.

3. `tests/test_agent_loader_status_overrides.py`
   - A `.2` feedback child with `feedback_times` and `feedback_plan_paths` propagates the mapping to the root parent.
   - Reapplying `_apply_status_overrides()` stays idempotent.
   - A parent path is not overwritten by a missing child path.

4. `tests/test_agent_model_bundle.py`
   - Bundle round-trip preserves `feedback_plan_paths`.
   - Older bundles without the field still load normally.

Run the focused tests first:

```bash
pytest tests/test_agent_model_timestamps.py tests/test_enrich_agent_wait_duration.py tests/test_agent_loader_status_overrides.py tests/test_agent_model_bundle.py
```

If implementation files change in this repo, run the repo-required final check after `just install` if needed:

```bash
just install
just check
```

## Risks and Edge Cases

- Existing historical agents may have `feedback_submitted_at` but no `plan_path`; those should continue rendering
  without the appended path.
- If a single metadata file ever contains multiple feedback timestamps but only one `plan_path`, the best available
  interpretation is that all listed feedback timestamps came from that metadata record's current rejected plan. This
  matches the current scalar/list compatibility model.
- The path shown is display-only; no file panel behavior needs to change because `extra_files` already handles plan file
  visibility from `plan_path.json`.
- No ACE help modal or keybinding documentation changes are needed because this is not a user-facing command or option.
- No Rust core change is expected because the needed wire fields already exist on both Python and Rust sides.

## Implementation Order

1. Add the `Agent.feedback_plan_paths` field and bundle serialization/deserialization support.
2. Update filesystem and wire metadata enrichment to populate the mapping.
3. Update status override propagation to copy the mapping with feedback timestamps.
4. Update `timestamps_display` formatting for `FBACK` rows.
5. Add and run the focused tests, then run `just check`.
