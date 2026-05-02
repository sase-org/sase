---
create_time: 2026-04-25 09:47:48
status: done
prompt: sdd/prompts/202604/full_qa_in_prompt.md
---
# Plan: Include Full Question Data in Q&A Prompt Section

## Problem

When an agent invokes `sase questions`, the user answers via the TUI modal, and a follow-up agent is launched with the
original prompt plus a `### Questions and Answers` section. Today that section collapses each question into a single
line that shows only the _selected_ answer, with the selected list rendered as Python `repr`:

```
### Questions and Answers

**Q: Skip recording for which case?** A: Selected '['B: Individual path starts with /']'
```

This is a bug for two reasons:

1. **Lost context.** The follow-up agent can no longer see the other options the user was choosing between. Choices like
   "B" only make sense in light of the rejected siblings ("A: Whole prompt starts with /", "C: Never skip", etc.).
   Without the full multiple-choice ballot the answer often reads as a non sequitur.
2. **Mangled rendering.** `selected` is a `list[str]` (multi-select capable) but the formatter interpolates it directly
   into an f-string, producing the literal `'['B: ...']'` you see above. Even single-select looks broken.

The TUI modal already builds a much richer markdown rendering of the same data (`_build_qa_markdown` in
`src/sase/ace/tui/modals/user_question_modal.py`) — question header, blockquoted question text, every option with
`[x]`/`[ ]` checkboxes, multi-select indicator, custom "Other" feedback, global note. The follow-up-prompt formatter
should produce essentially the same artifact.

## Goal

Replace `format_qa_for_prompt()` so it emits the full question with all pre-filled options and check state, mirroring
the TUI's `_build_qa_markdown`, and surface that to the follow-up agent.

## Data Flow Recap

- Marker file `~/.../.sase_questions_pending` carries the **full** questions list (including `options`, `header`,
  `multiSelect`).
- The TUI writes `question_response.json` with **only** `{question, selected, custom_feedback}` per answer plus a
  `global_note`. Options are not duplicated into the response.
- `handle_questions_marker` in `src/sase/axe/run_agent_exec_plan.py:419` has both the marker (`q_data`) and the response
  in scope when it calls `format_qa_for_prompt(response)` (lines 460, 485).

So the original questions are already available at the call site — we do not need to widen the response schema or change
the modal handler.

## Approach

### 1. Rewrite `format_qa_for_prompt` to take questions + response

`src/sase/axe/run_agent_helpers.py:470`

New signature:

```python
def format_qa_for_prompt(
    questions: list[dict[str, Any]],
    response: dict[str, Any],
) -> str:
```

Output structure (matches the TUI's `_build_qa_markdown`):

```
### Questions and Answers

#### Q1: <header or "">
> question text line 1
> question text line 2

- [ ] **A: First option** — first description
- [x] **B: Selected option** — selected description
- [ ] **C: Third option**
- [x] **Other:** "free-form text from user"

*Multi-select*

#### Q2: ...

---

> **Global Note:** <global note>
```

Pairing strategy: zip questions with `response["answers"]` by index, falling back to question-text match if lengths
differ. (Length mismatch shouldn't happen in practice — the modal always produces one answer slot per question — but a
defensive fallback keeps us robust to future schema drift.)

`selected` is treated as `list[str]` of option labels. For backwards compatibility we also accept a bare string
(auto-approve currently writes one — see #3 below).

`custom_feedback` is rendered as the "Other" line when present, exactly as the TUI does.

### 2. Extract a shared helper (optional consolidation)

The TUI's `_build_qa_markdown` is the canonical formatter today. The new `format_qa_for_prompt` will be functionally
identical given the same inputs. To avoid two implementations drifting apart, move the pure markdown logic into a shared
module — proposed location: a new `src/sase/main/qa_markdown.py` exposing
`build_qa_markdown(questions, answers, global_note, other_text=None)`.

Then:

- `format_qa_for_prompt` is a thin wrapper that unpacks the response dict and calls it.
- `UserQuestionModal._build_qa_markdown` builds an in-memory `answers` list from `self._answers` (so the live "preview
  during answering" path still works) and delegates to the same helper.

This is a small refactor but pays off: the shared invariant ("how Q&A is rendered for humans/agents") is enforced in one
place. If the consolidation turns out to be awkward (e.g., the modal's helper needs internal state we don't want to
leak), drop it and keep the two implementations near identical, with a code comment cross-referencing each other.

### 3. Normalize auto-approve `selected` to a list

`handle_questions_flow` (auto-approve branch) at `src/sase/axe/run_agent_helpers.py:408` currently writes
`"selected": selected` where `selected` is a bare string. Everywhere else (the modal handler at
`src/sase/ace/tui/actions/agents/_notification_modals.py:153`) writes a `list[str]`. Normalize the auto-approve path to
also write a single-element list, so the formatter has one shape to handle. Keep a defensive "accept str too" branch in
the formatter for any in-flight responses.

### 4. Update both call sites

`src/sase/axe/run_agent_exec_plan.py`:

- Line 460 inside `save_chat_history(response=...)`: pass `q_data["questions"]` alongside `response`.
- Line 485 (`qa_text = format_qa_for_prompt(response)`): same.

`q_data` is in scope as the function parameter `q_data` to `handle_questions_marker`.

### 5. Tests

Cover in `tests/` (likely a new `tests/test_qa_format.py` or extending `tests/test_run_agent_helpers.py` if it exists):

- Single-select with two options: rendered options show one `[x]` and one `[ ]`.
- Multi-select with three options, two checked: two `[x]` plus the `*Multi-select*` marker.
- "Other" with custom feedback renders the quoted free-form line.
- Question with `header` shows `#### Q1: header`; without header shows `#### Q1`.
- Global note appears under a `---` divider.
- Auto-approve string `selected` (legacy shape) still renders correctly.
- Unknown selected label (e.g. response references an option that's no longer in the question) doesn't crash — render as
  `[ ]` for known options and append a synthetic `[x] **<label>**` for unknown ones, so no data is silently lost.

If we extract the shared `build_qa_markdown` helper, also assert that the TUI modal preview and the prompt-section
output are byte-identical for the same inputs.

## Out of Scope

- Changing the question_response.json schema. The marker file already carries the options, and duplicating them into the
  response would create a second source of truth.
- Reworking the SDD spec Q&A append path (`update_spec_with_qa` at `run_agent_exec_plan.py:494`). It already consumes
  the same `qa_text` and benefits automatically from the new formatter — no changes needed there beyond verifying the
  spec file still looks reasonable.
- Touching `is_auto_approve_active` semantics. Auto-approve still picks the first option; only the JSON shape of the
  synthetic response changes.

## Risk / Validation

- The TUI modal preview already produces this exact format and has been in use, so the rendering is known-good.
- The follow-up agent's prompt grows slightly (one block per option vs. one line per question) — fine; questions lists
  are small.
- `just check` covers lint + tests; new unit tests pin the format.

## Files Touched

- `src/sase/axe/run_agent_helpers.py` — rewrite `format_qa_for_prompt`, normalize auto-approve `selected`.
- `src/sase/axe/run_agent_exec_plan.py` — pass `q_data["questions"]` to both `format_qa_for_prompt` call sites.
- `src/sase/main/qa_markdown.py` — _(new, optional)_ shared formatter.
- `src/sase/ace/tui/modals/user_question_modal.py` — _(optional)_ delegate `_build_qa_markdown` to the shared helper.
- `tests/test_qa_format.py` or `tests/test_run_agent_helpers.py` — new cases.
