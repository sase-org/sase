---
create_time: 2026-06-09 13:07:26
status: done
prompt: sdd/prompts/202606/agent_restore_preview_roots_prompts.md
---
# Plan: Agent Restore Root-Only Preview With Prompt Snippets

## Goal

In the Agent Restore panel's Preview pane, show only the root/top-level agent entries that the user would explicitly
restore, and include a compact prompt preview for each shown root agent. Workflow children and other non-root refs must
remain part of the saved/recent group payload so restore execution still revives the complete group, but they should no
longer clutter the preview list.

## Current Architecture

- The restore panel is `SavedAgentGroupRevivalModal` in `src/sase/ace/tui/modals/saved_agent_group_revival_modal.py`.
- The right pane is rendered by `build_saved_group_preview()` in
  `src/sase/ace/tui/modals/saved_agent_group_revival_rendering.py`.
- Full preview details come from `SavedAgentGroupWire.agent_refs`. The renderer currently loops over `group.agent_refs`
  directly, which is why workflow children and other non-root refs appear.
- Saved and recent restore records are built through
  `src/sase/ace/tui/actions/agents/_saved_group_records.py::build_saved_agent_group()`. That builder is shared by marked
  saved groups, recent single/bulk dismissals, and kill/dismiss flows.
- `SavedAgentGroupRefWire` currently stores identity/display/status/runtime metadata, but no prompt snippet.
- Dismissed bundles intentionally do not store raw prompt contents, and artifacts may be removed during dismissal.
  Therefore the prompt preview must be captured while the live `Agent` object can still read `raw_xprompt.md`, not
  lazily during later restore-panel display.
- The saved-group archive crosses the Rust-core boundary. This workspace does not have a sibling `../sase-core`
  checkout, so the local implementation must at least update Python wire compatibility and the existing Rust capability
  probe/fallback path. If the sibling core is available in the final implementation environment, the Rust wire/API
  should be updated in the same way.

## Proposed Design

### Preserve Complete Restore Semantics

Keep `SavedAgentGroupWire.agent_refs` complete. Do not filter children when building records or resolving restore
targets. `resolve_saved_group_agents()` should continue to load and match every ref so parent/child restoration behavior
does not change.

### Add Optional Prompt Snippets To Refs

Add an optional `prompt_preview: str | None = None` field to `SavedAgentGroupRefWire`.

- Treat this as an additive, backward-compatible field. Legacy records without it should read as `None`.
- Include the field in `saved_agent_group_wire_to_json_dict()` automatically through the dataclass projection.
- Update `_saved_agent_group_ref_from_dict()` to accept the field when present.
- Extend the saved-group facade wire capability probe so Rust-backed archive operations must preserve `prompt_preview`;
  otherwise the facade falls back to the Python implementation instead of silently dropping snippets.
- If `../sase-core` is present during implementation, mirror the new optional field in Rust serde structs, PyO3
  conversions, and Rust tests.

### Capture Prompt Preview At Record-Build Time

In `_saved_group_records.py`, add a bounded helper that reads `agent.get_raw_xprompt_content()` and normalizes it into a
small one-line snippet.

Suggested contract:

- Strip leading/trailing whitespace.
- Collapse internal whitespace/newlines to single spaces.
- Truncate to a fixed width, e.g. 120 characters, with `...` when needed.
- Return `None` if the prompt is unavailable or normalizes to empty.
- Catch read/cache errors defensively so saving or dismissing an agent never fails just because prompt preview capture
  failed.

Thread this into `_saved_group_ref_for_agent()`. Because `build_saved_agent_group()` is shared, this covers saved marked
groups and recent dismissal records together. This does add bounded `raw_xprompt.md` reads for the agents in the current
dismiss/save action, but it does not scan dismissed archives or resolve bundle paths.

### Render Only Root Entries In The Preview

In `build_saved_group_preview()`:

- Derive `root_refs = [ref for ref in group.agent_refs if not ref.is_workflow_child]`.
- Render only `root_refs` under the included-agent section.
- Keep the existing summary counts, including the existing total/top-level count text, so users still understand when
  children are included implicitly.
- Limit the rendered roots with the existing preview cap, but make the overflow text refer to remaining root agents.
- If a malformed legacy group has refs but no roots, show a short dim fallback such as "No root agent refs found" rather
  than rendering children.

In `_append_ref_line()` or a small companion helper:

- Keep the current first line with name, agent name, status, and runtime/model metadata.
- If `ref.prompt_preview` exists, add a second indented dim line like `prompt: <snippet>`.
- Avoid changing selection/routing behavior; this is presentation-only.

## Files To Change

- `src/sase/core/agent_group_archive_wire.py`
  - Add optional `prompt_preview` to `SavedAgentGroupRefWire` and dict rehydration.
  - Keep legacy records compatible.

- `src/sase/ace/dismissed_agent_groups.py`
  - Update `_WIRE_CAPABILITY_PROBE` and `_rust_group_archive_supports_current_wire()` to require preservation of
    `prompt_preview`.

- `src/sase/ace/tui/actions/agents/_saved_group_records.py`
  - Add prompt-preview normalization/truncation.
  - Populate `SavedAgentGroupRefWire.prompt_preview` for every ref when available.

- `src/sase/ace/tui/modals/saved_agent_group_revival_rendering.py`
  - Filter preview display to root refs.
  - Render prompt snippets under each root ref.

- `../sase-core` if available
  - Add the optional field to Rust saved-group ref wire structs and tests so the Rust archive path preserves it.

## Test Plan

- `tests/ace/tui/actions/test_saved_group_records.py`
  - Add coverage that the builder captures a normalized, truncated prompt preview from `raw_xprompt.md`.
  - Confirm prompt capture failure/missing prompt produces `None` without failing the group build.
  - Keep existing no-bundle-probe tests intact.

- `tests/test_dismissed_agent_groups.py`
  - Add a Python facade round-trip assertion that `prompt_preview` persists.
  - Add a legacy/missing-field assertion that old records load with `prompt_preview is None`.

- `tests/ace/tui/modals/test_saved_agent_group_revival_modal.py`
  - Add a preview regression with one parent and one workflow child: the parent appears, the child does not.
  - Assert the parent prompt preview appears under the parent row.

- `tests/test_agent_group_revival_execution.py`
  - Existing tests should continue to prove restore resolution still consumes child refs. Add no execution filtering.

- Visual snapshots
  - The Agent Restore rich preview snapshot may need an intentional update if the prompt line changes the expected PNG.

## Verification

Run `just install` first in this ephemeral workspace if dependencies are stale.

Focused Python tests:

```bash
pytest tests/ace/tui/actions/test_saved_group_records.py \
  tests/test_dismissed_agent_groups.py \
  tests/ace/tui/modals/test_saved_agent_group_revival_modal.py \
  tests/test_agent_group_revival_execution.py
```

If a sibling `../sase-core` checkout is available and changed:

```bash
just rust-check
```

Because implementation changes will touch source files in this repo, finish with:

```bash
just check
```

## Risks And Mitigations

- **Prompt preview silently dropped by stale Rust binding:** update the existing capability probe to require
  `prompt_preview` preservation, forcing the Python fallback until Rust support is available.
- **Dismiss-path latency:** keep prompt capture bounded to the agents in the current action and a fixed snippet length;
  do not scan dismissed bundles or archives.
- **Legacy records:** make the new field optional and default to `None`.
- **Restore behavior regression:** filter only the preview rendering. Keep group records and revive resolution complete.
