---
create_time: 2026-06-21 09:49:17
status: done
prompt: sdd/prompts/202606/reverted_agent_indicator.md
---
# Plan: "Reverted" Indicator on Agent Rows (Agents Tab)

## Goal

When a user reverts an agent's changes/commits via the Agents-tab `,r` leader action, the agent's row currently looks
identical to any other completed agent. Add a **beautiful, scannable visual indicator on the root agent row** so the
user can tell at a glance which agents have had their changes reverted.

## Product Context & Motivation

- `,r` reverts the commits an agent authored (matched by the `AGENT=<name>` provenance tag in commit messages). It
  creates a single `Revert N commit(s) from agent '<name>'` commit and, when a remote/branch exists, pushes it.
- Today there is **no lasting signal** in the TUI that this happened. After the confirmation modal closes, the agent row
  reverts to looking like a normal `DONE`/`FAILED` row. A user scanning the Agents tab cannot distinguish "this agent's
  work is live" from "this agent's work was rolled back," which is exactly the distinction `,r` exists to create.
- This is a read-at-a-glance affordance: it should be calm (not alarming), unmistakable, and consistent with the
  existing agent-row visual vocabulary.

## Source of Truth: `revert_result.json`

The revert backend already persists a durable, per-agent record of every revert. On success, `execute_agent_revert` /
`execute_agents_revert` write `revert_result.json` into the agent's **artifacts directory**:

```json
{
  "agent_name": "...",
  "reverted_shas": ["..."],
  "pushed": true,
  "reverted_at": "2026-06-21T10:32:00"
}
```

This file is the natural, authoritative signal for "this agent was reverted." It is written:

- for a **single-agent** revert → into the selected agent's `artifacts_dir`;
- for a **bulk** (marked-agents) revert → into the `artifacts_dir` of **every matched** target.

We will detect the presence of this file at agent **load time** and surface it on the row. No new persistence format is
introduced — we read what the revert backend already writes.

## Design (leading the look)

I'm recommending a **two-part, single-meaning treatment** applied to the root agent row only:

1. **A leading "revert" badge** — the glyph `↺` (U+21BA, counterclockwise open circle arrow: the universal "undo")
   rendered in a **calm, desaturated rose/terracotta** (starting value `#D7875F`). It sits immediately before the
   agent's display name, in the same name-adjacent badge cluster as the file-change `✏️` glyph.

2. **A strikethrough on the display name** — when reverted, the agent's name keeps its identity teal but gains a
   `strike` decoration (`strike #00D7AF`, `strike bold #00D7AF` when selected). This reads instantly, like crossing an
   item off a list: the badge makes the state _scannable_; the strikethrough makes it _unmistakable_.

Together: `↺ s̶a̶s̶e̶-̶f̶e̶a̶t̶u̶r̶e̶ (DONE)` — a rose undo-arrow followed by the struck-through agent name. The pairing is cohesive
(rose + teal are roughly complementary and read as intentional) and sits comfortably beside the existing status color
and runtime suffix.

### Why this design

- **Distinct from retry.** The retry badge is `↻N` (clockwise, _with_ a count, warm yellow `#FFAF00`). Revert is `↺`
  (counterclockwise, _no_ count, muted rose). Different direction, different color, different presence-of-number — no
  collision.
- **Distinct from failure.** Failures own bright red `#FF5F5F`. Revert is deliberately calmer (desaturated rose),
  because a revert is a _deliberate user action_, not an error to alarm on.
- **Consistent vocabulary.** A single name-adjacent glyph badge matches how `◌` (hidden), `◆` (bead), `⚡`
  (auto-approve), and `✏️` (file change) already work.
- **Root-only.** The indicator is gated on `not agent.is_workflow_child`, satisfying the "root agent row" requirement
  and keeping workflow-step children clean. (The backing flag is only set on terminal/done root agents anyway.)

### Glyph rendering note

The pinned visual-snapshot font is Fira Code, which already renders the retry glyph `↻` (U+21BB); its mirror `↺`
(U+21BA, same Unicode block) is expected to render identically. The visual snapshot suite (`just test-visual`) is the
arbiter — if `↺` shows as tofu, fall back to `⟲` (U+27F2). Final color/weight will be tuned against the rendered
snapshot during review.

## Technical Approach

### 1. Detect at load time, not render time

Reverted-ness is a one-time filesystem check (`<artifacts_dir>/revert_result.json` exists), so it must **not** run on
the Textual event loop during rendering. Done/terminal agents (the only ones that can be reverted) are built by the
done-agent loaders, which already read several files per agent during enrichment — one extra `is_file()` stat is
negligible and happens off the hot path.

- Add a small helper, e.g. `agent_is_reverted(artifacts_dir: str | None) -> bool`, that returns whether
  `revert_result.json` exists (guarding `None`/missing dirs and swallowing `OSError`). Co-locate it with the revert
  backend (`src/sase/ace/revert_agent.py` or a thin `src/sase/ace/tui/models/agent_revert.py`) so detection lives next
  to the writer.
- Call it from the done-agent loaders where the artifact directory is in scope, setting `agent.reverted`:
  - `src/sase/ace/tui/models/_loaders/_done_loaders.py` → `_load_done_agent_for_dir` (alongside the existing
    `enrich_agent_from_meta(agent, str(artifact_dir))` call).
  - the snapshot/record path in the same module (`_build_done_agent_from_record`), using the record's artifact dir.

  Prefer threading this through the existing enrichment step (a single `enrich_agent_revert_state(agent, artifact_dir)`
  invoked from both paths) so there is one code path rather than two copies.

### 2. New `Agent` field

In `src/sase/ace/tui/models/agent.py`, add a defaulted bool near the other simple state flags (e.g. just after
`hidden: bool = False`):

```python
# Whether this agent's commits were reverted via the Agents-tab `,r` action
# (detected from revert_result.json in the agent's artifacts dir at load time).
reverted: bool = False
```

### 3. Render the indicator

In `src/sase/ace/tui/widgets/_agent_list_render_agent.py` (`format_agent_option`):

- Add the badge immediately before the display-name append (after the file-change glyph block), guarded by
  `agent.reverted and not agent.is_workflow_child`.
- When reverted, compose the name style with `strike` (combined with the existing selected/unselected teal).

Add the glyph + style constants to `src/sase/ace/tui/widgets/_agent_list_styling.py` (`_REVERTED_GLYPH = "↺"`,
`_REVERTED_GLYPH_STYLE`), mirroring the existing `_BEAD_GLYPH` / `_FILE_CHANGE_GLYPH` constants.

### 4. Keep the render cache correct

The row render is memoized by `agent_render_key` in `src/sase/ace/tui/widgets/_agent_list_render_cache.py`. Add
`agent.reverted` to that key so a row that becomes reverted is not served a stale cached render. (The key is
intentionally explicit, so this is a deliberate one-line addition.)

### 5. Immediate feedback (optional polish)

After a successful `,r` revert, the Agents tab already schedules an async refresh, which reloads agents and picks up the
new `revert_result.json` — so the indicator appears without extra work. Optionally, the revert action handler can also
set `reverted = True` on the in-memory row and patch it immediately for zero-latency feedback. Low priority; the reload
path is the correctness guarantee.

### 6. Help legend

Per the ACE guidelines (help popup must stay in sync), add an entry to the "Agent Row Glyphs" section of
`src/sase/ace/tui/modals/help_modal/agents_bindings.py`:

```python
("↺", "Reverted (changes undone)"),
```

## Edge Cases & Known Limitations

- **Family-scope single revert.** A single `,r` revert with _family_ scope reverts the whole family's commits but writes
  `revert_result.json` only into the **selected** agent's artifacts dir. So only the acted-upon agent shows the badge;
  sibling family members do not. This is an acceptable V1 behavior — the selected agent is the natural anchor for "the
  family was reverted here" — and is called out as a future enhancement (fan the marker out to all matched family
  members). **Bulk** reverts already mark every matched agent, so they are fully covered.
- **Push failed but local revert succeeded.** `revert_result.json` is still written (with `pushed: false`), so the badge
  appears. This is correct: the commits _were_ reverted locally. A future enhancement could vary the badge (e.g., a
  dimmer tone or an extra mark) when `pushed == false`; V1 treats "reverted" as a single state for simplicity and calm.
- **STOPPED agents** have no commits and are non-revertable, so they will never carry the marker.

## Rust Core Boundary

The entire agent-revert subsystem currently lives in **Python** in this repo (`revert_agent.py` and friends);
`revert_result.json` is written by Python, and the `Agent` model and its loaders are Python-owned. Detecting that marker
to drive a TUI badge is presentation/state glue that belongs alongside the existing revert code, so this change stays
Python-side and does **not** cross into `sase-core`. If the revert backend is ever migrated to the Rust core, the
reverted-state detection should migrate with it.

## Testing

- **Render unit test** (`tests/ace/tui/widgets/test_agent_display_list_rendering.py`): a root agent with `reverted=True`
  renders the `↺` badge and a struck name; a workflow-child with `reverted=True` renders neither (root-only guard); a
  normal agent renders neither.
- **Render-key test** (`tests/ace/tui/widgets/test_agent_render_key_badges.py`): toggling `agent.reverted` changes
  `agent_render_key`, proving the cache won't serve a stale row.
- **Detection test**: with a temp artifacts dir containing `revert_result.json`, the loader/helper sets
  `agent.reverted = True`; without it, `False`.
- **Help-legend test**: if the glyph legend is asserted in tests, add the new entry there too.
- **Visual PNG snapshot** (`tests/ace/tui/visual/`, `just test-visual`): add/extend an Agents-tab snapshot that includes
  a reverted row, and regenerate goldens with `--sase-update-visual-snapshots` once the look is approved. This is also
  where we confirm `↺` renders in Fira Code and finalize the rose tone.
- Run `just check` (after `just install`) before finishing.

## Files to Change (summary)

| File                                                                 | Change                                              |
| -------------------------------------------------------------------- | --------------------------------------------------- |
| `src/sase/ace/tui/models/agent.py`                                   | Add `reverted: bool = False` field                  |
| `src/sase/ace/revert_agent.py` (or new `tui/models/agent_revert.py`) | `agent_is_reverted(artifacts_dir)` helper           |
| `src/sase/ace/tui/models/_loaders/_done_loaders.py`                  | Set `agent.reverted` in both done-agent build paths |
| `src/sase/ace/tui/widgets/_agent_list_styling.py`                    | `_REVERTED_GLYPH` + style constants                 |
| `src/sase/ace/tui/widgets/_agent_list_render_agent.py`               | Render badge + name strikethrough (root-only)       |
| `src/sase/ace/tui/widgets/_agent_list_render_cache.py`               | Add `agent.reverted` to `agent_render_key`          |
| `src/sase/ace/tui/modals/help_modal/agents_bindings.py`              | Add `↺` to "Agent Row Glyphs" legend                |
| `tests/ace/tui/widgets/…`, `tests/ace/tui/visual/…`                  | Unit, render-key, detection, and snapshot tests     |

## Out of Scope / Future Enhancements

- Fanning the reverted marker out to all matched **family** members on family-scope reverts.
- Differentiating `pushed: false` (reverted locally, push failed) from a fully-pushed revert.
- Surfacing richer revert metadata (when reverted, how many commits) in the agent detail panel.
- A filter/query token to show only reverted (or only non-reverted) agents.
