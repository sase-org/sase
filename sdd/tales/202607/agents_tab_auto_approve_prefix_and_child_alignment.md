---
create_time: 2026-07-05 21:37:01
status: wip
prompt: sdd/prompts/202607/agents_tab_auto_approve_prefix_and_child_alignment.md
---
# Plan: Fix over-applied ⚡ (auto-approve) prefix on Agents-tab child rows + child row alignment

## Problem

On the "Agents" tab of the `sase ace` TUI, too many rows carry the ⚡ / ⚡T / ⚡E auto-approve prefix (see
`.sase/home/tmp/screenshots/20260705_211955.png`). For an `%auto:epic` run, the root workflow entry, the main agent
child entry, AND every bash/python embedded-workflow step (`setup`, `prepare`, `checkout`, `resolve`, `load_history`,
`diff`) all render `⚡E`. Only two rows should have it:

1. The root agent/workflow entry.
2. The child _agent_ entry whose prompt contained `%auto` (e.g. `main ... --plan`).

Additionally, child rows are misaligned: the ⚡ icon is appended _before_ the ` └─` child-indent connector, so any child
row carrying the icon has its connector shifted ~4 cells right of its siblings (e.g. the `--epic` follow-up child, which
has no icon, sits left of the `⚡E`-prefixed rows).

## Root Cause

Two independent defects:

### 1. Bash/python child steps inherit `approve` from the shared root meta

Every step of a workflow run shares the run's artifacts directory: each `prompt_step_*.json` marker's `artifacts_dir`
points at the workflow timestamp dir, which holds the ROOT agent's `agent_meta.json` (verified on disk:
`~/.sase/projects/home/artifacts/ace-run/20260605085824/`). That root meta carries `approve` /
`auto_approve_plan_action` when the launch prompt had `%auto*` (written by
`src/sase/axe/run_agent_directives.py:237-247`).

Both child-step loaders funnel through the filesystem enrichment helper:

- `src/sase/ace/tui/models/_loaders/_workflow_step_loaders.py:206`
- `src/sase/ace/tui/models/_loaders/_workflow_snapshot_loaders.py:357`

each calling `enrich_agent_from_meta(agent, artifacts_dir_from_marker, workflow_child=True)`. Inside that helper
(`src/sase/ace/tui/models/_loaders/_meta_enrichment_filesystem.py:74-82`) the `approve` / `auto_approve_plan_action`
assignments are NOT guarded by `workflow_child` (unlike `name`, `role_suffix`, `agent_family`, etc.), so every
bash/python child step inherits `approve=True` and renders ⚡. The same inherited flag also makes the detail panel show
a bogus `Auto: ⚡ EPIC` line for bash steps (`prompt_panel/_agent_display_header.py:_append_auto_approve_field`).

### 2. The ⚡ icon renders before the child indent

In `src/sase/ace/tui/widgets/_agent_list_render_agent.py:96-120` (`format_agent_option`), the approve icon is appended
first and `_CHILD_INDENT` (" └─ ") after, so icon-bearing child rows have their tree connector pushed right relative to
icon-less siblings. Even after fix 1, the legitimate `%auto` agent child (`main`) would still be misaligned with its
siblings.

## Design

### Fix 1 — Gate approve inheritance for workflow children (`_meta_enrichment_filesystem.py`)

In `enrich_agent_from_meta`, only apply `agent.approve = True` / `agent.auto_approve_plan_action` when the row is
either:

- not a workflow child (`workflow_child=False` — roots, done agents, re-parented follow-up agents reading their own
  meta), or
- the main agent step of the run — reuse the existing predicate `_is_main_workflow_agent_step(agent)` from
  `_meta_enrichment_common.py:216` (`step_type == "agent"` and `parent_step_index is None`). This is exactly the entry
  whose prompt contained `%auto`; embedded-workflow agent steps and bash/python/parallel steps are excluded.

This mirrors the established pattern already used for identity fields (`apply_workflow_child_identity_from_meta` only
applies to the main agent step).

**Status-regression guard**: the plan-status enrichment at the bottom of the same function
(`plan_enrichment_status(..., auto_approved=agent.approve)` at line ~259) must keep receiving the _meta-derived_
auto-approve truth even when the row-level flag is suppressed. Otherwise a still-RUNNING bash child of a `plan: true`
meta would flip to "PLAN" (manual-review) status. Compute a local
`meta_auto_approved = agent.approve or bool(data.get("approve")) or bool(auto_action)` and pass that, keeping status
behavior byte-for-byte identical.

No changes needed in `_meta_enrichment_wire.py`: the wire path is only used for root-level entries (both snapshot
loaders explicitly fall back to the filesystem helper for child steps). No changes in `../sase-core`: the Rust scan only
supplies raw meta; which rows _display_ the flag is presentation-side enrichment that already lives in this repo.

### Fix 2 — Render the ⚡ icon after the child indent (`_agent_list_render_agent.py`)

In `format_agent_option`, compute the icon string once, then:

- non-child rows: append it in the current leading position (unchanged — root rows keep today's look, matching the
  existing `test_agents_auto_approve_icons_png_snapshot` golden).
- workflow-child rows: append it _after_ `_CHILD_INDENT` (before the step glyph / provider badge), so all `└─`
  connectors align in one column regardless of the flag. This matches how the hidden `◌` icon already renders after the
  indent.

This also fixes alignment for re-parented follow-up agents (rows made children via `parent_timestamp`, like `--epic`),
which can legitimately carry their own `%auto` flag.

Perf note (per `memory/tui_perf.md`): both fixes are pure in-memory logic in already-cached paths; `agent_render_key`
already includes `approve` and `auto_approve_plan_action`, so no cache-key or I/O changes are needed.

## Behavior After the Fix (screenshot scenario)

| Row                                                                                   | Before                 | After                            |
| ------------------------------------------------------------------------------------- | ---------------------- | -------------------------------- |
| root `sase (EPIC APPROVED) 0b.f1.f1`                                                  | `⚡E ≡ …`              | unchanged                        |
| `main (DONE) 0b.f1.f1--plan` (agent child, `%auto:epic` prompt)                       | `⚡E   └─ …` (shifted) | `  └─ ⚡E …` (connector aligned) |
| `sase (EPIC APPROVED) 0b.f1.f1--epic` (follow-up child)                               | `  └─ …`               | unchanged                        |
| bash/python steps (`setup`, `prepare`, `checkout`, `resolve`, `load_history`, `diff`) | `⚡E   └─ 🐚 …`        | `  └─ 🐚 …` (no ⚡, aligned)     |
| detail panel for a bash step                                                          | shows `Auto: ⚡ EPIC`  | no `Auto:` line                  |

## Files to Change

1. `src/sase/ace/tui/models/_loaders/_meta_enrichment_filesystem.py` — gate approve/auto-action assignments for workflow
   children on `_is_main_workflow_agent_step`; preserve `plan_enrichment_status` inputs via a meta-derived local.
2. `src/sase/ace/tui/widgets/_agent_list_render_agent.py` — move the approve-icon append after `_CHILD_INDENT` for
   workflow-child rows.

## Tests

1. **Enrichment unit tests** — extend `tests/test_workflow_child_meta_enrichment.py` (existing agent-vs-bash pattern):
   shared meta with `auto_approve_plan_action: "epic"` (and separately `approve: true`) →
   - main agent step (`parent_step_index=None`): `approve is True`, action propagated;
   - bash/python step and embedded agent step (`parent_step_index` set): `approve is False`, action `None`;
   - a RUNNING bash child with `plan: true` + `plan_submitted_at` in meta keeps its RUNNING status (does not become
     "PLAN") — the status-regression guard.
2. **Render unit tests** — extend `tests/ace/tui/widgets/test_agent_list_status_indicators.py`:
   - approve-flagged workflow child renders the connector first and the ⚡ icon after it (`left.plain.startswith` on the
     indent, icon position after `└─ `);
   - approve-flagged child and non-approve sibling produce the connector at the same column;
   - root-row icon placement unchanged.
3. **PNG snapshot** — add one snapshot to `tests/ace/tui/visual/test_ace_png_snapshots_agents_interactions.py` showing
   an expanded `%auto:epic`-style family: root with ⚡E, agent child with post-indent ⚡E, bash children with no icon —
   locking in the alignment. Generate the golden with `--sase-update-visual-snapshots`.
4. Run `just check` (includes lint + the full test/visual suites) and inspect existing goldens for incidental diffs
   (only snapshots that render approve-flagged child rows should change; the existing root-row auto-approve icon
   snapshot must NOT change).
