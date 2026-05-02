---
create_time: 2026-04-22 16:38:10
status: done
prompt: sdd/prompts/202604/plan_review_title_provider_model.md
---

# Plan: Show LLM Provider / Model in Plan Review Panel Title

## Motivation

When a plan is ready for review inside the TUI, the modal's current title only shows the filename:

```
Plan Review  20260422_143012_my_feature_plan.md
```

The reviewer has no way to tell at a glance which runtime produced the plan. This matters because:

- Agents on different providers/models produce plans with different strengths (Opus vs. Sonnet vs. a Gemini model vs.
  Codex). Knowing the author lets the reviewer calibrate scrutiny and expectations.
- The same reviewer often has several planner agents running against the same project simultaneously, and the filename
  alone doesn't disambiguate.
- The provider/model will also be the runtime that continues as the coder if the user selects "Approve" without changing
  the model — so it's useful to confirm it before acting.

The data is already wired end-to-end into the notification payload; only the modal's title rendering (and the two call
sites that instantiate the modal) need to change.

## Current State

**File:** `src/sase/ace/tui/modals/plan_approval_modal.py` lines 86–90

```python
yield Static(
    f"[bold cyan]Plan Review[/bold cyan]  [dim]{plan_name}[/dim]",
    id="plan-approval-title",
)
```

`PlanApprovalModal.__init__` takes only `plan_file` and `pending_approve_state`. It has no knowledge of which
agent/runtime produced the plan.

**Provider/model data flow (already in place):**

1. `AgentExecContext` (`src/sase/axe/run_agent_exec.py`) carries `agent_model` and `agent_llm_provider`.
2. `handle_plan_approval` in `src/sase/llm_provider/_plan_utils.py` forwards them to `notify_plan_approval`.
3. `notify_plan_approval` (`src/sase/notifications/senders.py` lines 148–190) stores them in `notification.action_data`
   under the keys `"model"` and `"llm_provider"`.
4. `handle_plan_approval` in `src/sase/ace/tui/actions/agents/_notification_modals.py` reads the notification and
   **instantiates `PlanApprovalModal` without passing those fields through** (lines 226 and 390).

So: everything reaches the notification, then stops. The modal is the only gap.

## Target Behavior

The title becomes something like:

```
Plan Review  CLAUDE(opus)  20260422_143012_my_feature_plan.md
```

…with provider-themed coloring for the `PROVIDER(model)` label that matches the palette already used in the prompt panel
header (`src/sase/ace/tui/widgets/prompt_panel/_helpers.py::append_model_field`):

- `CLAUDE(<model>)` — orange (`#FF5F00` name, `#FFAF00` model)
- `CODEX(<model>)` — lime (`#87FF00` name, `#AFFF5F` model)
- `GEMINI(<model>)` — Google blue (`#4285F4` name, `#87AFFF` model)
- Unknown/other — neutral muted color (fallback to `format_provider_model_label` output without special styling)

When the notification lacks provider/model fields (older notifications, edge cases, explicit `None`), the title renders
exactly as it does today — no badge, no layout change. This keeps the change non-breaking and graceful.

### Placement

Proposed ordering: `Plan Review  <PROVIDER(model)>  <filename>`. Rationale:

- The "Plan Review" label stays as the first anchor (what kind of modal is this).
- The provider/model badge comes next because it's the most useful identity cue for the reviewer — more informative than
  the timestamped filename.
- The filename remains as dim trailing context.

Alternatives worth calling out in review:

- Trailing badge: `Plan Review  <filename>  <PROVIDER(model)>` — keeps filename adjacent to the label. Slightly less
  prominent.
- Prefix: `[CLAUDE(opus)]  Plan Review  <filename>` — reads as a tag but clashes with the existing
  `[bold cyan]Plan Review[/bold cyan]` styling.

Recommend the middle placement; easy to adjust if preference differs.

## Design

### 1. Modal constructor

Extend `PlanApprovalModal.__init__` with two optional parameters:

```python
def __init__(
    self,
    plan_file: str,
    pending_approve_state: PendingApproveState | None = None,
    *,
    llm_provider: str | None = None,
    model: str | None = None,
) -> None:
```

These names mirror the notification `action_data` keys for zero-translation wiring. Both keyword-only to keep the
positional signature stable and avoid ambiguity with the existing `pending_approve_state` positional.

### 2. Title rendering

In `compose()`, build the title using Rich markup. Either:

**Option A (recommended):** Small inline helper in the same module that returns a Rich markup string:

```python
def _provider_badge_markup(provider: str | None, model: str | None) -> str:
    """Return themed markup like '[bold #FF5F00]CLAUDE[/]...(opus)...' or ''."""
    ...
```

Keeps the change local and testable; no new cross-module dependency.

**Option B:** Build a `rich.text.Text` and render via `Static(text)` the way `mentor_review_modal.py::_update_title`
does. More verbose but matches that modal's convention.

Either way, when provider/model are both missing, the helper returns an empty string and the title collapses to its
current form.

### 3. Pass data at both instantiation sites

In `src/sase/ace/tui/actions/agents/_notification_modals.py`:

- **Initial push (line 390):** extract `"llm_provider"` and `"model"` from `notification.action_data` and pass as
  keyword arguments.
- **Edit re-push (line 226):** thread the same two values through. The simplest approach is to capture them into local
  variables at the top of `handle_plan_approval` so both call sites use the same source:

```python
llm_provider = notification.action_data.get("llm_provider")
model = notification.action_data.get("model")
```

Then both `PlanApprovalModal(...)` calls pass `llm_provider=llm_provider, model=model`.

### 4. Styling utility reuse

The codebase already has:

- `sase.llm_provider.registry.format_provider_model_label(provider, model)` — returns `"CLAUDE(opus)"` or graceful
  fallback strings.
- `sase.ace.tui.widgets.prompt_panel._helpers.append_model_field` — appends provider-themed styling to a
  `rich.text.Text`. This one is coupled to the `Model: ` prefix and the `Text` mutation style, so not directly reusable
  for modal-title markup.

Plan: use `format_provider_model_label` for the plain-text rendering and introduce the small `_provider_badge_markup`
helper in the modal file to produce Rich markup with the same provider color scheme. Do NOT refactor
`append_model_field` in this change — the two helpers serve different contexts (Text append vs. markup string) and
unifying them is out of scope.

## Out of Scope

- Notification payload shape (already includes `llm_provider` and `model`).
- Agent execution / plan generation pipeline.
- Other modals (`ApproveOptionsModal` already shows model info; `MentorReviewModal` is unrelated).
- Older notifications that were serialized without provider/model fields: they gracefully fall back to current behavior;
  no migration needed.
- A global styling helper shared between `_helpers.py` and the modal — tempting but a separate refactor that would
  expand this change without product value.

## Validation

1. `just check` to confirm lint + typecheck + tests pass.
2. Manual TUI verification with three scenarios:
   - A plan produced by a Claude agent (should show orange `CLAUDE(<model>)`).
   - A plan produced by a Codex or Gemini agent (themed accordingly).
   - A legacy notification without provider/model (title unchanged).
3. Light unit coverage: a test that constructs `PlanApprovalModal` with and without the new keyword args and asserts the
   composed title string contains (or omits) the badge. The existing `test_plan_rejection_response.py` shows the pattern
   for exercising the modal's result dataclass without running the full TUI.

## Risks / Considerations

- **Title overflow:** Adding a badge makes the title longer. On narrow terminals this could truncate the filename. The
  filename is the least important piece and is already `[dim]`, so truncation is acceptable; no layout change needed.
- **`action_data` contract drift:** The notification keys `"llm_provider"` and `"model"` are set in one place
  (`notify_plan_approval`) and read in one place (the modal handler). If these keys are ever renamed, both sites must
  move together. Calling out here so it isn't overlooked during future refactors.
- **Test brittleness:** Unit tests that assert exact markup strings are fragile. Prefer asserting on substring presence
  (e.g. `"CLAUDE"` in the title text) rather than exact markup tags.

## Summary of Files to Touch

| File                                                      | Change                                                                                                                     |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/ace/tui/modals/plan_approval_modal.py`          | Extend `__init__` with `llm_provider` / `model` kwargs; update `compose()` title; add `_provider_badge_markup` helper.     |
| `src/sase/ace/tui/actions/agents/_notification_modals.py` | Read provider/model from `notification.action_data`; pass to both `PlanApprovalModal(...)` call sites (lines 226 and 390). |
| `tests/` (new or existing)                                | Add a small test covering the title-with-badge and title-without-badge paths.                                              |

No other files should need to change.
