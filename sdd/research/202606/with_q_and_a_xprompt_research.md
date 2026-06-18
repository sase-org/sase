---
create_time: 2026-06-18
updated_time: 2026-06-18
status: research
---

# `#with_q_and_a` XPrompt Research

## Research Request

Design a new `#with_q_and_a` xprompt workflow that takes one or more question/answer records and a prompt, then
produces the same follow-up prompt an agent sees after the user answers `/sase_questions`.

The key requirement is parity: this workflow should match the logic used when agents ask questions, because the same
workflow or underlying logic may later become the internal path triggered by user answers.

## Current Question Workflow

The existing question flow has two distinct responsibilities:

1. User interaction and runner bookkeeping.
2. Prompt reconstruction.

The `sase questions '<json>'` command validates the agent-submitted question schema, writes
`.sase_questions_pending`, then terminates the runner group so the execution loop can handle the handoff
(`src/sase/main/questions_command_handler.py`).

The accepted question schema is:

```json
[
  {
    "question": "Full question text",
    "header": "Short label",
    "options": [{ "label": "Option label", "description": "Details" }],
    "multiSelect": false
  }
]
```

`handle_questions_flow()` then:

- Creates a session under `~/.sase/user_question/<uuid>/`.
- Writes `question_request.json`.
- Sends a `UserQuestion` notification with `response_dir`, `session_id`, and agent routing timestamps.
- Writes `pending_question.json` in the interrupted agent's artifacts directory.
- Polls for `question_response.json`.
- Deletes `pending_question.json` in a `finally` block after response or kill.
- Adds `_question_request_path`, `_question_response_path`, and `_question_session_id` to the loaded response before
  returning it.

The response schema written by the TUI is:

```json
{
  "answers": [
    {
      "question": "Full question text",
      "selected": ["Option label"],
      "custom_feedback": "Optional free-form text"
    }
  ],
  "global_note": "Optional steering note"
}
```

The mobile core path can also produce a compatible response (`sase-core`, `notifications/mobile.rs`). It may answer a
single indexed question at a time, so the runner must continue accepting response payloads whose `answers` list length
does not match the original `questions` list.

## Prompt Reconstruction Today

The current parity-critical prompt rendering is concentrated in three Python helpers:

- `QARound`, `build_merged_qa_markdown()`, and `build_qa_markdown()` in `src/sase/main/qa_markdown.py`.
- `build_qa_round()` in `src/sase/axe/run_agent_helpers_questions.py`.
- `merge_qa_for_prompt()` in `src/sase/axe/run_agent_helpers_questions.py`.

Important current behavior:

- `build_qa_round()` preserves the original question objects and aligns answers by list position when lengths match.
- If lengths differ, it matches answers back to questions by exact question text.
- `build_merged_qa_markdown()` emits exactly one `### Questions and Answers` section across all rounds.
- Question numbers are continuous across rounds.
- `header` becomes the `#### QN: header` suffix.
- `question` text is rendered as a blockquote.
- Every original option is rendered, checked or unchecked, so the agent sees the user's selection in context.
- Unknown selected labels are surfaced as checked synthetic options so stale response data is not lost.
- `multiSelect` adds a `*Multi-select*` marker.
- Only the latest non-empty `global_note` is rendered.
- `merge_qa_for_prompt()` wraps the rendered markdown in:

```text
%xprompts_enabled:false
...
%xprompts_enabled:true
```

That wrapper is not cosmetic. Tests verify that literal `#foo` text inside questions or custom feedback survives the
xprompt expansion pipeline and is stripped back to clean final prompt text.

The execution loop appends the rendered section with:

```python
state.current_prompt = state.question_base_prompt + "\n\n" + merged_qa_text
```

For code-phase questions, `question_base_prompt` is the interrupted code prompt, not the original planner prompt. This
preserves the concrete worker `%model:` directive, plan file reference, and implementation instructions. Repeated
questions rebuild from that one base plus one merged Q&A section, rather than appending duplicate sections.

## Bookkeeping That A Pure XPrompt Cannot Replace

The prompt text is only part of the current workflow. `handle_questions_marker()` also:

- Finalizes the interrupted phase artifacts.
- Records `questions_submitted_at` and question request/response paths in metadata.
- Saves a chat history entry for the question handoff.
- Allocates the next family suffix, such as `--1`, `--2`, or code-phase `--code-0`.
- Promotes the root row to a workflow when needed.
- Creates follow-up artifacts with inherited provider/model metadata from the interrupted phase.
- Stores the full follow-up prompt artifact.
- Updates the SDD prompt snapshot with the merged Q&A block when an SDD spec path exists.

Those side effects are runner responsibilities. An embeddable xprompt workflow can replicate prompt composition, but it
should not be asked to own artifact mutation, suffix allocation, root/child status synchronization, notification
dismissal, or chat metadata.

## XPrompt Engine Constraints

The xprompt engine gives us a good implementation hook, but not through a pure markdown template:

- Markdown xprompts support primitive typed inputs only: `word`, `line`, `text`, `path`, `int`, `bool`, and `float`.
- Jinja rendering can loop over values already in context, but inline markdown xprompt inputs arrive as strings.
- The normal xprompt Jinja environment does not expose a `fromjson` filter.
- YAML workflows can run hidden `python` or `bash` pre-steps before a `prompt_part`.
- A YAML workflow with a `prompt_part` is embeddable and referenced with `#name`, not `#!name`.
- Embedded workflow pre-step outputs are available to the `prompt_part` template.
- The `#name(args):: trailing text` shorthand appends trailing text as a positional argument.

The last point affects the input ordering. If the workflow supports:

```yaml
input:
  prompt: text
  qa_json: text
```

then callers can write:

```text
#with_q_and_a(qa_json=[[{"questions":[...],"response":{"answers":[...]}}]])::
Original prompt text here.
```

The trailing text becomes the first positional argument and maps to `prompt`; `qa_json` is supplied by name.

If `qa_json` were the first input, that convenient syntax would not work because the trailing text would try to map to
`qa_json`.

## Input Shape Options

### Option 1: Simple Pair List

Example:

```json
[
  {"question": "Which DB?", "answer": "PostgreSQL"}
]
```

Pros:

- Easy to type by hand.
- Matches the user's initial "question-answer pairs" wording.

Cons:

- Cannot perfectly represent the existing agent question workflow.
- Loses `header`, `options`, unchecked alternatives, `multiSelect`, and `global_note`.
- Free-form answers do not naturally render through the existing markdown function unless the implementation invents
  synthetic options.
- Not suitable as the internal runner contract.

This can be supported as optional sugar, but it should not be the primary format.

### Option 2: Full Single-Round Payload

Example:

```json
{
  "questions": [
    {
      "question": "Which DB?",
      "header": "Database",
      "options": [
        {"label": "PostgreSQL", "description": "Relational, mature"},
        {"label": "SQLite", "description": "Embedded, simple"}
      ]
    }
  ],
  "response": {
    "answers": [
      {
        "question": "Which DB?",
        "selected": ["PostgreSQL"],
        "custom_feedback": null
      }
    ],
    "global_note": "Prefer the lowest-risk path."
  }
}
```

Pros:

- Mirrors `q_data["questions"]` plus the `handle_questions_flow()` response.
- Reuses `build_qa_round()` exactly.
- Handles TUI and mobile response shapes.
- Good for the first implementation.

Cons:

- Verbose.
- Multi-round use needs either repeated xprompt calls or an outer structure.

### Option 3: Full Multi-Round Payload

Example:

```json
{
  "rounds": [
    {
      "questions": [
        {
          "question": "Which DB?",
          "options": [{"label": "PostgreSQL"}, {"label": "SQLite"}]
        }
      ],
      "response": {
        "answers": [{"question": "Which DB?", "selected": ["PostgreSQL"]}],
        "global_note": ""
      }
    },
    {
      "questions": [
        {
          "question": "Use migrations?",
          "options": [{"label": "Yes"}, {"label": "No"}]
        }
      ],
      "response": {
        "answers": [{"question": "Use migrations?", "selected": ["Yes"]}],
        "global_note": "Keep schema changes reversible."
      }
    }
  ]
}
```

Pros:

- Exactly matches `state.qa_rounds`.
- Preserves continuous numbering and last-global-note-wins semantics.
- Suitable for both public `#with_q_and_a` use and internal question follow-up prompt reconstruction.

Cons:

- Most verbose hand-written form.

This should be the primary stable contract. The single-round form can be accepted as shorthand for
`{"rounds": [payload]}`.

## Implementation Options

### Option A: Pure Markdown XPrompt

This would be a file like `src/sase/xprompts/with_q_and_a.md` with Jinja loops.

Reject this option.

It would require hand-parsing strings or inventing delimiters in template space. It would also duplicate the renderer
already tested in `qa_markdown.py`, which is exactly what the parity requirement is trying to avoid.

### Option B: YAML Embeddable Workflow With Hidden Python Pre-Step

This would be a file like `src/sase/xprompts/with_q_and_a.yml`:

```yaml
description: Append answered SASE user questions to a prompt using the same Q&A renderer as agent follow-ups.
input:
  prompt:
    type: text
    description: Prompt to run after the answered question section is appended.
  qa_json:
    type: text
    description: JSON Q&A payload. Prefer {"rounds":[{"questions":[...],"response":{...}}]}.
steps:
  - name: render_qa
    hidden: true
    python: |
      import json
      from sase.main.qa_markdown import qa_rounds_from_payload, merge_qa_for_prompt

      payload = json.loads({{ qa_json | tojson }})
      print(json.dumps({"qa": merge_qa_for_prompt(qa_rounds_from_payload(payload))}))
    output: { qa: text }

  - name: inject
    prompt_part: |
      {{ prompt }}

      {{ render_qa.qa }}
```

The exact helper names above are illustrative. Today `merge_qa_for_prompt()` lives in `sase.axe.run_agent_helpers`, and
`build_qa_round()` lives in `sase.axe.run_agent_helpers_questions`. For a packaged xprompt workflow, those should move
to `sase.main.qa_markdown` or a small adjacent module so the workflow does not import runner internals.

Pros:

- Uses the existing workflow engine correctly.
- Keeps the public surface as `#with_q_and_a`.
- Calls the same renderer as the internal runner.
- Can parse JSON safely with Python instead of delimiter tricks.
- Can accept multi-round and single-round payloads.

Cons:

- Still Python-owned; if this becomes a cross-frontend API, the Rust-core boundary should be revisited.
- Calling it from the runner through the full workflow executor would be unnecessary overhead for the hot internal
  handoff path.

This is the best near-term implementation.

### Option C: Move Q&A Rendering To Rust Core First

The project memory says shared backend/domain behavior belongs in `sase-core` when a web app, CLI, editor integration,
or other frontend needs matching behavior. This Q&A renderer is a candidate because the TUI, mobile, runner, and future
gateway clients all care about the same response shape.

Pros:

- Best long-term ownership if mobile/gateway need to render or preview the exact follow-up prompt.
- Aligns with existing Rust ownership of mobile question action response planning and pending-question scan metadata.

Cons:

- Larger migration than needed to add `#with_q_and_a`.
- The current xprompt workflow engine and markdown renderer are Python-owned.
- Adds binding work and parity tests before the public workflow exists.

This is the right longer-term direction if Q&A prompt composition becomes an external API, but it is not necessary for
the first `#with_q_and_a` workflow.

## Recommended Refactor Before Adding The XPrompt

Move the pure prompt-construction helpers out of `sase.axe` into the existing renderer module:

```python
# src/sase/main/qa_markdown.py
def build_qa_round(questions: list[dict[str, Any]], response: dict[str, Any]) -> QARound: ...
def merge_qa_for_prompt(rounds: list[QARound]) -> str: ...
def qa_rounds_from_payload(payload: object) -> list[QARound]: ...
```

Keep compatibility imports in `src/sase/axe/run_agent_helpers_questions.py` so existing callers and tests continue to
work during the transition.

`qa_rounds_from_payload()` should accept:

- Primary multi-round shape: `{"rounds": [{"questions": [...], "response": {...}}]}`.
- Single-round shorthand: `{"questions": [...], "response": {...}}`.
- Legacy-ish shorthand: `{"questions": [...], "answers": [...], "global_note": "..."}`.

It may optionally accept `{"pairs": [{"question": "...", "answer": "..."}]}` for human convenience, but that sugar
must normalize into full `QARound` objects and should not be used by the internal question-answer path.

## Internal Runner Integration

For internal parity, do not make `handle_questions_marker()` shell out to `sase run` or instantiate a full xprompt
workflow just to build a string.

Instead:

1. Make `#with_q_and_a` call the shared helper from its hidden Python pre-step.
2. Make `handle_questions_marker()` call the same helper directly.
3. Add a focused test proving that the workflow expansion output equals the direct helper output for the same payload.

That gives stronger parity than having two separate implementations, while keeping runner side effects in runner code.

The internal trigger can later be described conceptually as "the same logic as `#with_q_and_a`" because the workflow and
the handler share the exact same helper. If hard workflow reuse is still desired later, add a small non-agent workflow
render API that expands an embeddable workflow in-process with explicit inputs, but only after the direct-helper parity
test exists.

## Test Plan

Add tests at three levels:

1. Renderer/payload tests:
   - Multi-round payload renders one `### Questions and Answers` section.
   - Single-round payload equals direct `build_qa_round()` plus `merge_qa_for_prompt()`.
   - Mobile-style one-answer response aligns by question text when lengths differ.
   - `#literal` in question text and custom feedback is protected by disabled-region markers.

2. Workflow expansion tests:
   - The shorthand form `#with_q_and_a(qa_json=[[...]]):: prompt` expands to
     `prompt + "\n\n" + merge_qa_for_prompt(...)`.
   - Named `prompt=` and `qa_json=` form works.
   - Invalid JSON fails with a useful workflow error.

3. Runner parity tests:
   - `handle_questions_marker()` and the workflow helper produce byte-identical prompt text for one round.
   - Repeated rounds still produce one section and continuous numbering.
   - Code-phase `question_base_prompt` remains the base before appending Q&A.

Existing tests in `tests/test_qa_format.py`, `tests/test_axe_run_agent_exec_plan_followup_questions.py`, and
`tests/test_user_question_response.py` already cover much of the behavior and should be extended rather than replaced.

## Recommended Solution

Implement `#with_q_and_a` as an embeddable YAML workflow backed by a shared Python Q&A prompt-construction helper.

Use this stable public input contract:

```text
#with_q_and_a(qa_json=[[{"rounds":[{"questions":[...],"response":{"answers":[...],"global_note":""}}]}]])::
Prompt to run next.
```

Also support named-input form:

```text
#with_q_and_a(
  prompt=[[Prompt to run next.]],
  qa_json=[[{"questions":[...],"response":{"answers":[...],"global_note":""}}]]
)
```

Move `build_qa_round()` and `merge_qa_for_prompt()` into `sase.main.qa_markdown`, add `qa_rounds_from_payload()`, and
make both the workflow and `handle_questions_marker()` call those same helpers. Keep runner-only artifact, metadata,
suffix, chat, and status behavior in `handle_questions_marker()`.

Do not make the primary contract a simple question-answer pair list. It is too lossy for perfect parity. Pair-list
syntax can be accepted later as convenience sugar, but the internal agent-answer workflow should use the full
`questions` plus `response` payload shape.
