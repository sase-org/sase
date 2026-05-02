---
create_time: 2026-04-24 18:06:26
status: done
prompt: sdd/prompts/202604/plan_review_g_G_scroll.md
---
# Plan: `g` / `G` Scroll-to-Top / Scroll-to-Bottom in the Plan Review Panel

## Product context

The plan review panel (`PlanApprovalModal`) is the modal shown to the user when an agent-generated plan file needs
approval before the coder runs. Today it supports half-page scrolling via `ctrl+d` / `ctrl+u`, but there is no way to
jump directly to the top or bottom of the plan. For long plans this is inconvenient — users have to mash `ctrl+d` to get
to the final sections (e.g. "Test plan", "Risks") before deciding whether to approve.

Vim users (the target audience) expect `g` to jump to the top and `G` to jump to the bottom. These keys are already the
established convention elsewhere in the TUI for the same action (app-level `scroll_to_top` / `scroll_to_bottom` are
bound to `g` / `G` in `default_config.yml`), so adding them here closes a consistency gap rather than introducing a new
convention.

Neither letter is currently used by the modal, so there is no conflict:

- `a`/`A` → Approve / Options
- `r`, `f`, `e`, `E` → Reject / Feedback / Edit / Epic
- `y`/`Y` → Copy plan / copy path
- `q`, `escape` → Cancel
- `ctrl+d`/`ctrl+u` → Scroll

## Scope

**In scope**

1. Add two new modal-level bindings to `PlanApprovalModal`:
   - `g` → `action_scroll_to_top` — scroll the plan viewport to the very top.
   - `G` (shift+g) → `action_scroll_to_bottom` — scroll the plan viewport to the very bottom.
2. Implement the two corresponding `action_*` methods on the modal, targeting the existing `#plan-approval-scroll`
   `VerticalScroll` container and using Textual's `scroll_home(animate=False)` / `scroll_end(animate=False)` (the same
   pattern already used by `_reset_output_scroll` / `_scroll_output_to_end` in `task_queue_modal.py`).
3. Update the hint footer string in `compose()` to surface the new shortcuts alongside the existing "Ctrl+D/U to scroll"
   hint so discoverability is preserved.
4. Add a focused unit test covering that the modal's `BINDINGS` list includes the two new entries bound to the right
   actions. (A full Textual scroll-behavior integration test is out of scope — the action methods are thin passthroughs
   to well-tested Textual APIs.)

**Out of scope**

- Wiring the plan-review bindings into the `default_config.yml` keymap registry. The existing scroll bindings (`ctrl+d`
  / `ctrl+u`) and all other modal bindings are hardcoded in `BINDINGS`; making this one entry configurable would be
  inconsistent and is a larger refactor best done separately.
- Adding `g`/`G` to other modals (e.g. `ApproveOptionsModal`, `NotificationModal`, `TaskQueueModal`). Those can follow
  as separate work if desired; this change is intentionally limited to the "plan review" modal the user asked about.
- Any changes to app-level `AppKeymaps`, the keymap loader, or help-modal documentation (the plan-review modal's footer
  hints are its own documentation surface).

## Design

### File to change

`src/sase/ace/tui/modals/plan_approval_modal.py` — single file, ~15 lines added in total.

### Binding additions

Append two rows to the existing `BINDINGS` list (around line 98):

```python
("g", "scroll_to_top", "Top"),
("G", "scroll_to_bottom", "Bottom"),
```

Textual's `Binding` parser treats `"G"` as shift+g, matching the behavior users expect and matching how
`default_config.yml` already uses `"G"`.

### Action methods

Add two new methods near the existing scroll actions (after `action_scroll_up`, around line 197):

```python
def action_scroll_to_top(self) -> None:
    """Scroll the content to the very top."""
    scroll = self.query_one("#plan-approval-scroll", VerticalScroll)
    scroll.scroll_home(animate=False)

def action_scroll_to_bottom(self) -> None:
    """Scroll the content to the very bottom."""
    scroll = self.query_one("#plan-approval-scroll", VerticalScroll)
    scroll.scroll_end(animate=False)
```

`animate=False` matches the existing `action_scroll_down` / `action_scroll_up` choice (they use
`scroll_relative(animate=False)`) and keeps the jump instantaneous, which is what vim users expect from `g`/`G`.

### Footer hint update

In `compose()` (lines 138–145), extend the trailing scroll hint from:

```
[dim]q[/dim]=Cancel  |  Ctrl+D/U to scroll
```

to something like:

```
[dim]q[/dim]=Cancel  |  Ctrl+D/U / g / G to scroll
```

Keeping the hint short preserves the modal footer's visual weight.

## Testing

- Add a unit test in `tests/test_plan_approval_modal_title.py` (or a new `tests/test_plan_approval_modal_bindings.py` if
  preferred) asserting that `PlanApprovalModal.BINDINGS` contains tuples for `("g", "scroll_to_top", …)` and
  `("G", "scroll_to_bottom", …)`. This catches accidental removal or key-collision regressions.
- Run `just check` before finishing (lint + type + fast tests).

## Risks / notes

- **Key collision risk** — confirmed none: no existing binding uses `g` or `G`.
- **Modal focus** — the modal steals focus on push, so `g`/`G` will route to `PlanApprovalModal` bindings rather than
  bleed to app-level bindings while the modal is open. No extra guard needed.
- **No config wiring** — intentional; tracked in the "Out of scope" section. If the team later decides all modal
  bindings should be user-configurable, that should be done as a uniform pass across every modal rather than a one-off
  here.
