---
create_time: 2026-04-27 09:53:47
status: done
prompt: sdd/prompts/202604/rename_default_grouping_to_by_project.md
---
# Rename `default` grouping label to `by project` and give it a unique badge color

## Problem

The Agents-tab info panel renders a grouping badge of the form `[group: <label> (o)]`. Three labels exist today:

| Mode (`GroupingMode`) | Label       | Badge style                 | Where styled                                       |
| --------------------- | ----------- | --------------------------- | -------------------------------------------------- |
| `STANDARD`            | `default`   | `dim italic` (unstyled)     | `src/sase/ace/tui/widgets/agent_info_panel.py:103` |
| `BY_DATE`             | `by date`   | `bold #87D7FF` (sky cyan)   | `src/sase/ace/tui/widgets/agent_info_panel.py:104` |
| `BY_STATUS`           | `by status` | `bold #FFAF87` (warm amber) | `src/sase/ace/tui/widgets/agent_info_panel.py:105` |

Two issues:

1. **Naming inconsistency.** The `BY_DATE` / `BY_STATUS` labels follow a `by <noun>` pattern that names the bucket
   dimension. `STANDARD` instead uses `default`, which describes its position in the cycle rather than what it buckets
   by. Since `STANDARD` groups by _project_ (per `docs/ace.md:330` — "Project (with optional ChangeSpec sub-level)"),
   `by project` is both more descriptive and aligns the three labels into a uniform `by <noun>` family.
2. **Visual treatment.** `default` renders `dim italic` while the other two get distinctive accent colors. This
   underweights the active label when `STANDARD` is selected — the badge looks half-disabled. Giving it a unique accent
   color brings it to parity with its siblings.

## Source-of-truth label mapping

The label strings are not duplicated across the codebase — they live in a single dict at
`src/sase/ace/tui/actions/agents/_grouping.py:26-30`:

```python
_MODE_LABELS: dict[str, str] = {
    "STANDARD": "default",
    "BY_DATE": "by date",
    "BY_STATUS": "by status",
}
```

This dict is consumed in two places:

- `src/sase/ace/tui/actions/agents/_display.py:597-601` — passes the label into
  `agent_info_panel.update_grouping_mode(...)`.
- `src/sase/ace/tui/actions/agents/_grouping.py:85-88` — emits the cycle-toast (`Grouping: default` / `by date` /
  `by status`).

So flipping `STANDARD`'s label in `_MODE_LABELS` fixes both the badge text and the toast in one stroke. The badge
_style_ dict in `agent_info_panel.py` keys on the label string, so the style dict needs a parallel rename.

## Plan

### Step 1 — Rename the label

`src/sase/ace/tui/actions/agents/_grouping.py:27`:

```python
"STANDARD": "default",
```

→

```python
"STANDARD": "by project",
```

This is the only label-string change needed; `_display.py:597-601` reads through the dict and the cycle toast in
`_grouping.py:85-88` reads through the same dict, so both pick up the new label automatically.

### Step 2 — Restyle the badge

`src/sase/ace/tui/widgets/agent_info_panel.py:102-106`:

```python
_GROUPING_MODE_STYLES: dict[str, str] = {
    "default": "dim italic",
    "by date": "bold #87D7FF",
    "by status": "bold #FFAF87",
}
```

→

```python
_GROUPING_MODE_STYLES: dict[str, str] = {
    "by project": "bold #5FAFFF",
    "by date": "bold #87D7FF",
    "by status": "bold #FFAF87",
}
```

**Color choice — `#5FAFFF` (project sky-blue).** This is the exact color used for project-banner left-bars and rules in
the agent list (`src/sase/ace/tui/widgets/_agent_list_styling.py:22`: `_PROJECT_BANNER_BAR_STYLE = "bold #5FAFFF"`).
Reusing it ties the `by project` badge thematically to the visual cue users already associate with project banners,
mirroring how `by date` / `by status` use color to differentiate. It's distinct from `#87D7FF` (a lighter cyan used by
`by date` and the `Agents:` header) but in the same blue family — a deliberate choice, since both modes foreground a
"spatial" grouping (where it belongs) versus the warm amber for status (what state it's in).

**Alternatives if the sibling-blue feels too close to `by date`:**

- `bold #af87d7` (purple) — already used by `view: thinking`, would create a cross-badge collision so probably not.
- `bold #D787AF` (pink/magenta) — fresh in this palette, maximally distinct.
- `bold #00D7AF` (teal) — already used by the position counter (`{position}/{total}`), would collide.

I'll go with `#5FAFFF` for the project-banner thematic tie-in unless the user prefers the magenta on review.

### Step 3 — Update the fallback and docstring

`src/sase/ace/tui/widgets/agent_info_panel.py:128`:

```python
grouping_label = self._grouping_mode or "default"
```

→

```python
grouping_label = self._grouping_mode or "by project"
```

And update the docstring at `src/sase/ace/tui/widgets/agent_info_panel.py:75-85` to replace `"default"` references with
`"by project"` in the Args description and the empty-string-fallback note.

### Step 4 — Update the tests

`tests/ace/tui/widgets/test_agent_info_panel.py`:

- Line 23-29 — `test_grouping_badge_renders_default_when_unset`: rename to
  `test_grouping_badge_renders_by_project_when_unset` and update the assertion from
  `f"[group: default ({_DEFAULT_GROUPING_KEY})]"` to `f"[group: by project ({_DEFAULT_GROUPING_KEY})]"`.

The `by date` and `by status` tests on lines 32-47 are unaffected.

### Step 5 — Update the docs

`docs/ace.md:325-326`:

```text
Press `g` on the Agents tab to cycle the L0 grouping bucket through three modes. The Agents tab shows a brief toast
(`Grouping: default` / `by date` / `by status`) on each cycle:
```

→

```text
Press `o` on the Agents tab to cycle the L0 grouping bucket through three modes. The Agents tab shows a brief toast
(`Grouping: by project` / `by date` / `by status`) on each cycle:
```

(I'll also fix the stale `g` → `o` keybind reference here while I'm in the file — that's a piggyback fix, not strictly
in scope, but the section is being touched anyway. If the user wants to scope it out I'll drop the `g` → `o` change and
only flip the toast label.)

The cycle-toast wording in the running TUI flows through `_MODE_LABELS` from Step 1, so no separate code change is
needed for that — only the docs need to mirror the new label.

### Step 6 — Verify

- `just check` (fmt + ruff + mypy + tests) per `CLAUDE.md`.
- Manually launch `sase ace`, switch to the Agents tab, confirm:
  - The badge reads `[group: by project (o)]` in `STANDARD` mode and renders in sky-blue (`#5FAFFF`).
  - Cycling with `o` flips through `[group: by project (o)] → [group: by date (o)] → [group: by status (o)]`.
  - Each toast reads `Grouping: by project` / `Grouping: by date` / `Grouping: by status`.

## Out of scope

- Renaming the `STANDARD` enum member to `BY_PROJECT` in `agent_groups.py`. The user-visible label is what's
  inconsistent; the enum name is internal and the rename would touch ~13 files (`grouping_mode_state.py`,
  `_loading_finalize.py`, `_core.py`, `_grouping.py`, `_agent_list_rendering.py`, etc.). Doable but a separate refactor;
  do it if/when the inconsistency starts costing real cognitive load on the code side.
- Re-tinting the project-banner glyphs or any other use of `#5FAFFF` to keep the badge color globally unique. The
  banner-color reuse is the _point_ of picking that color, not a bug.

## Open question

**Color pick — sibling sky-blue (`#5FAFFF`) or a non-blue accent for visual contrast?** I'm leaning sibling-blue for the
project-banner thematic tie-in. Happy to swap to `#D787AF` (pink/magenta) if the user wants the three labels to read as
three clearly different hues at a glance.
