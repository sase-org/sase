---
create_time: 2026-04-20 19:10:00
status: new
prompt: sdd/prompts/202604/repeat_agent_visual_indicator.md
---

# Plan: Visual Indicator for Repeat Agents in the Agents Tab

## Problem

When a user launches a prompt with `%repeat:N` (or `%r:N`), the TUI fans it out into N agents named `<base>.1`,
`<base>.2`, ..., `<base>.N`. These sibling agents appear in the Agents tab as plain, visually indistinguishable entries
— the only hint that they belong to the same repeat group is the numeric suffix on the name (e.g., `task.1`, `task.2`,
`task.3`).

Users can't see at a glance:

- Which agents are part of a repeat group
- Which iteration within the group a given row represents
- How many siblings exist in the group

This matters because repeat agents are a first-class workflow pattern (see `plans/202604/repeat_agents_as_entries.md`
and the recently shipped sequential-repeat fix), and the Agents tab is where users spend most of their triage time.

## Design

Add a compact inline badge — `⟳ k/N` (e.g. `⟳ 2/3`) — immediately after the existing `⚡` approve icon on each repeat
agent's row. The badge is rendered in a warm amber color so it reads as a cohesive unit and stands apart from the
cyan/blue/pink palette already used for step types and statuses.

### Visual Rationale

1. **Icon — `⟳` (U+27F3, clockwise gapped circle arrow)**
   - Universally recognized as "repeat / cycle / refresh"
   - Single-width Unicode, matching the style of the existing non-emoji icons (`⚡`, `✘`, `◌`)
   - Already used in `agent_list.py:373` as the retry-count annotation (`\u21bb`) — so there is precedent for a similar
     glyph meaning "iteration / repeat". We deliberately pick a _visually distinct_ variant (`⟳` vs `↻`) so repeat-group
     membership and retry count don't collide in the user's eye. Final variant to be locked in by a quick in-terminal
     readability check.

2. **Format — `⟳ k/N`**
   - Carries both the iteration index and the group size in ~5-6 characters
   - A boolean-only marker would fail to answer "which one is this?" and "how many are there?", both of which users need
     for triage
   - `k/N` matches the existing step-number format used elsewhere in the row (`1/3`, `2a/7`), so the visual grammar is
     consistent

3. **Color — warm amber (`#FFB347`)**
   - Distinct from bash's `#FFAF5F` (slightly brighter and more orange), status gold `#FFD700`, failed red `#FF5F5F`,
     and retry-orange `#FF8700`
   - Warm orange semantically conveys "motion / activity / in-progress multiplicity", which fits the mental model of a
     fan-out
   - Applied to both the glyph and the `k/N` digits as one unit, so the badge reads as a single token

4. **Placement — immediately after `⚡` approve icon, before workflow-child indentation**
   - Repeat agents are by definition top-level (a `%r` prompt fans out at launch; repeat slots are first-class Agent
     entries, not workflow children), so conflict with the `_CHILD_INDENT` path is rare. However we still place the
     badge _before_ the indentation block so nesting remains visually correct in the corner case where a workflow child
     is somehow tagged as a repeat slot
   - Non-repeat agents skip the badge entirely — zero visual regression

### What We Deliberately Rejected

- **Tree-connector glyphs (`┌`, `├`, `└`) grouping the N rows together.** Conflicts with existing workflow child
  indentation (`_CHILD_INDENT = "  └─ "`). Also fragile when the group is interleaved with unrelated agents after
  sorting.
- **Background color band on the row.** Textual's `OptionList` does not support per-row background styling cleanly, and
  adds visual weight the user hasn't asked for.
- **Stripping the `.k` suffix from the display name** (so `task.2` becomes `task` with the badge carrying the index).
  Keeps grep-ability and round-trippability with CLI names (`sase ace --agent task.2`). The minor redundancy is worth
  it.
- **Emoji (`🔁`).** Inconsistent with the surrounding single-width icons; widths vary by terminal.
- **Subscript Unicode (`²⁄₃`).** Cute but harder to read at small sizes and in some monospace fonts.
- **Boolean-only flag (`⟳` without `k/N`).** Discards the most useful context.

### Example Row Layouts (before → after)

```
[h] ⚡ [agent] task.1 (RUNNING) @task.1
[h] ⚡ [agent] task.2 (DONE)    @task.2
[h] ⚡ [agent] task.3 (WAITING) @task.3
```

becomes

```
[h] ⚡ ⟳ 1/3  [agent] task.1 (RUNNING) @task.1
[h] ⚡ ⟳ 2/3  [agent] task.2 (DONE)    @task.2
[h] ⚡ ⟳ 3/3  [agent] task.3 (WAITING) @task.3
```

Non-repeat agents render exactly as before.

## Data Flow

The repeat iteration / total is already known at launch time via the env vars `SASE_REPEAT_ITERATION` and
`SASE_REPEAT_TOTAL` (set in `src/sase/agent/launcher.py:273-274`). The cleanest propagation path is:

**Launch-time write** → **On-disk persistence** → **Load-time read** → **Render**

1. **Launch-time write (`src/sase/axe/run_agent_phases.py::extract_directives_and_write_meta`, ~line 114)**: read
   `SASE_REPEAT_ITERATION` and `SASE_REPEAT_TOTAL` from the environment and add them to the `agent_meta` dict before it
   is written to `agent_meta.json`. This is analogous to how `name`, `model`, `llm_provider`, `approve`, `hidden`, etc.
   are already persisted.

2. **On-disk persistence (`agent_meta.json`)**: the per-agent artifacts directory already holds this file for every
   agent. Adding two integer fields is a minimal, backward-compatible change — legacy agents without these fields will
   simply be treated as non-repeat (field = `None`).

3. **Load-time read (`src/sase/ace/tui/models/_loaders/_artifact_loaders.py`, around lines 55-64 and the bundle load
   paths around lines 403-510)**: when enriching an `Agent` from `agent_meta.json`, populate the new `repeat_iteration`
   and `repeat_total` fields if present.

4. **Render (`src/sase/ace/tui/widgets/agent_list.py::_format_agent_option`, ~line 260)**: when both fields are set,
   append the badge to the row `Text` object between the approve-icon block and the child-indentation block.

This approach piggybacks on an existing, well-tested persistence mechanism and requires no new file formats, no schema
migrations, and no special-casing of in-memory state vs. restart state.

## Changes

### 1. `src/sase/ace/tui/models/agent.py`

Add two fields to the `Agent` dataclass (alongside other optional metadata):

```python
# Repeat-group membership (populated for agents spawned via %repeat).
# Both None for non-repeat agents. When set, both are always set.
repeat_iteration: int | None = None
repeat_total: int | None = None
```

Add a convenience property:

```python
@property
def is_repeat(self) -> bool:
    """True when this agent is a member of a %repeat fan-out group."""
    return self.repeat_iteration is not None and self.repeat_total is not None
```

Update `to_bundle_dict` / `from_bundle_dict` in `agent_bundle.py` to round-trip the two new fields.

### 2. `src/sase/axe/run_agent_phases.py`

In `extract_directives_and_write_meta` (~line 114), after the existing block that writes `name`, `model`, etc., read the
env vars and add to `agent_meta`:

```python
repeat_iter_env = os.environ.get("SASE_REPEAT_ITERATION")
repeat_total_env = os.environ.get("SASE_REPEAT_TOTAL")
if repeat_iter_env and repeat_total_env:
    try:
        agent_meta["repeat_iteration"] = int(repeat_iter_env)
        agent_meta["repeat_total"] = int(repeat_total_env)
    except ValueError:
        pass  # malformed env → skip, don't poison the meta file
```

Import `REPEAT_ITERATION_ENV` / `REPEAT_TOTAL_ENV` constants from `sase.agent.repeat_launcher` rather than
string-duplicating the env var names.

### 3. `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`

In the function that enriches an Agent from `agent_meta.json` (around lines 50-70 based on the `approve` field
precedent), add:

```python
if data.get("repeat_iteration") is not None and data.get("repeat_total") is not None:
    agent.repeat_iteration = int(data["repeat_iteration"])
    agent.repeat_total = int(data["repeat_total"])
```

And at the bundle-load paths (~lines 403, 508) where `Agent(...)` is constructed directly, pass the new fields through
similarly.

### 4. `src/sase/ace/tui/widgets/agent_list.py`

Add a module-level constant block near the other icon constants:

```python
# Badge for repeat-group members (agents spawned via %repeat)
_REPEAT_ICON = "⟳"
_REPEAT_COLOR = "#FFB347"  # Warm amber, distinct from bash #FFAF5F
```

In `_format_agent_option`, immediately after the approve-icon block (line 262, before the workflow-child indentation at
line 264), insert:

```python
# Repeat-group badge
if agent.is_repeat:
    text.append(
        f"{_REPEAT_ICON} {agent.repeat_iteration}/{agent.repeat_total}  ",
        style=f"bold {_REPEAT_COLOR}",
    )
```

Note the two trailing spaces to create a clean separator before the rest of the row. Use `bold` for legibility at small
terminal font sizes; drop it if informal feedback says it's too heavy.

### 5. `src/sase/ace/tui/styles.tcss`

No CSS changes needed. All repeat-badge styling is inline via Rich `Text` styles (consistent with how the approve icon,
pin icon, and done icon are already styled inline, not via TCSS).

## Tests

### Unit tests

1. **`tests/test_agent_model_repeat_fields.py`** (new): assert that `Agent(...)` accepts
   `repeat_iteration=2, repeat_total=3` and that `is_repeat` returns `True`; with both `None`, `is_repeat` is `False`.
   Cover the bundle round-trip (`to_bundle_dict` → `from_bundle_dict` preserves both fields).

2. **Extend `tests/test_axe_run_agent_exec_repeat_env.py`** (existing): add a case that invokes
   `extract_directives_and_write_meta` with `SASE_REPEAT_ITERATION=2, SASE_REPEAT_TOTAL=5` set in the environment and
   asserts that the resulting `agent_meta.json` contains `"repeat_iteration": 2` and `"repeat_total": 5`. Also add a
   no-env-var case to prove the fields are omitted cleanly.

3. **New test for `_artifact_loaders.py`**: write a fake `agent_meta.json` with the two fields and assert the loaded
   `Agent` has them populated; write one without the fields and assert they are `None`.

### Widget / rendering tests

4. **`tests/tui/widgets/test_agent_list_repeat_badge.py`** (new, mirroring existing widget tests): construct an `Agent`
   with `repeat_iteration=2, repeat_total=3` and verify the rendered `Option.prompt` (the `Text` object) contains the
   substring `⟳ 2/3` with the expected amber style. Construct a non-repeat `Agent` and verify the string `⟳` does not
   appear in the rendered prompt.

### Manual verification

5. Launch `sase ace`, submit a test prompt with `%r:3 echo hello` (or equivalent), and visually confirm:
   - All three rows show `⟳ 1/3`, `⟳ 2/3`, `⟳ 3/3` in warm amber
   - Non-repeat agents in the same tab are visually unchanged
   - The badge is stable across status transitions (RUNNING → DONE → etc.)
   - Toggling fold / hidden / pinned doesn't break the rendering
   - Terminal width at 80 and 120 cols — the extra 7-8 chars don't cause ugly wraps

## Edge Cases

1. **`repeat_total == 1`**: `repeat_launcher.extract_repeat_and_name` returns `None` when `count <= 1` (line 138), so no
   slots are ever created with `total=1` — the fields will never be populated in that case and no badge renders. We do
   not need to special-case this.

2. **One sibling archived or in a terminal state while others run**: the badge is per-row and reads from each agent's
   own meta, so it's unaffected by sibling state. A `DONE` sibling and a `RUNNING` sibling both correctly show their own
   `k/N`.

3. **Workflow children that happen to be repeat slots**: currently no code path produces this combination (repeats fan
   out at launch, not inside workflows), but the rendering placement ensures correct composition if it ever happens —
   badge first, then `_CHILD_INDENT`, then step number.

4. **Legacy agents predating this change**: their `agent_meta.json` has no `repeat_iteration` / `repeat_total` keys. The
   loader sets the fields to `None`, `is_repeat` returns `False`, no badge renders. Zero regression for existing
   artifacts.

5. **Malformed env vars (e.g., `SASE_REPEAT_ITERATION=foo`)**: `int()` conversion is wrapped in `try/except ValueError`
   at both write and read sites. The agent proceeds without repeat badging — we do not want a malformed env var to crash
   the launch.

6. **`SASE_REPEAT_ITERATION` leaking from a parent shell**: already mitigated upstream (see
   `plans/202604/repeat_agents_as_entries.md:804`). No action needed here.

7. **Followup agents on a repeat slot** (e.g., `.plan`, `.code` role suffixes on `task.2`): the followup agent inherits
   neither env var by default, so the badge only shows on the actual repeat slots, not their followups. This is the
   correct behavior — a followup is not itself a repeat.

## Implementation Phases

Phase 1 — **Data model & persistence** (small, independently mergeable):

- `Agent` dataclass fields + `is_repeat` property
- `run_agent_phases.py` env-var → meta write
- Bundle round-trip update
- Tests 1–3

Phase 2 — **Loader wiring** (small, depends on Phase 1):

- `_artifact_loaders.py` populates new fields from `agent_meta.json`
- Tests covering the loader path

Phase 3 — **Rendering** (small, depends on Phase 2):

- `agent_list.py` badge insertion + constants
- Test 4
- Manual verification (Test 5)

Phases 1 and 2 can ship in a single CL since they're both trivial and coupled. Phase 3 should be its own CL so the
visual change is isolated for review and easy to revert if the color/glyph choice turns out to be wrong in practice.
