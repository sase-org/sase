---
create_time: 2026-06-18
updated_time: 2026-06-18
status: research
---

# `#with_q_and_a` XPrompt Research

## Scope

This consolidates the two prior research passes:

- `sdd/research/202606/with_q_and_a_xprompt_research.md`
- `sdd/research/202606/with_q_and_a_xprompt.md`

The request is to design a `#with_q_and_a` xprompt that accepts a base prompt plus one or more answered question
rounds, and that matches the prompt produced when an agent resumes after the user answers `/sase_questions`.

The key conclusion from both agents is correct: parity should be achieved by sharing the same prompt-construction
helper between the runner and the xprompt, not by reimplementing Q&A rendering in a markdown/Jinja template.

## Current Parity Target

The runtime path is `handle_questions_marker()` in `src/sase/axe/run_agent_exec_questions.py`.

After the user response arrives, the runner:

- Records question metadata and chat history.
- Builds one `QARound` from the original questions plus response.
- Appends that round to `state.qa_rounds`.
- Renders all accumulated rounds through `merge_qa_for_prompt(state.qa_rounds)`.
- Creates follow-up artifacts, suffixes, family roles, and relationships.
- Rebuilds the follow-up prompt as:

```python
state.current_prompt = state.question_base_prompt + "\n\n" + merged_qa_text
```

That expression at `run_agent_exec_questions.py:217-219` is the byte-level prompt target for `#with_q_and_a`.

`question_base_prompt` is not always the original planner prompt. `LoopState` defaults it to `original_prompt`, but
code and feedback phase transitions refresh it to the exact phase prompt. This preserves code-agent prompt text and
its resolved `%model` directive when a code-phase agent asks a question.

The xprompt should own prompt assembly only. The following are runner concerns and should stay in
`handle_questions_marker()`:

- Finalizing the interrupted artifacts.
- Recording `questions_submitted_at`, request/response paths, and session id.
- Saving chat history.
- Allocating family suffixes and roles.
- Creating follow-up artifacts.
- Updating the SDD prompt snapshot.
- Dismissing notifications or changing TUI row status.

## Existing Renderer

The existing renderer is already close to the desired shared implementation:

- `QARound` and `build_merged_qa_markdown()` live in `src/sase/main/qa_markdown.py`.
- `build_qa_round()` and `merge_qa_for_prompt()` live in `src/sase/axe/run_agent_helpers_questions.py`, with facade
  exports in `run_agent_helpers.py`.
- The TUI preview uses `build_qa_markdown()`, a single-round wrapper around the same merged renderer.

Important behavior to preserve:

- `build_qa_round()` aligns answers by index when answer count equals question count; otherwise it matches by exact
  question text. This matters because the TUI writes one answer slot per question, while mobile can answer one indexed
  question.
- `build_merged_qa_markdown()` emits exactly one `### Questions and Answers` section for all rounds.
- Question numbering is continuous across rounds.
- `header` renders as the `#### QN: header` suffix.
- Question text renders as blockquote text.
- All original options render, checked or unchecked, so the agent sees selected choices in context.
- Unknown selected labels render as synthetic checked options so stale response data is not dropped.
- `"Other"` plus `custom_feedback` renders as a quoted checked custom option.
- `multiSelect` adds the `*Multi-select*` marker.
- Only the latest non-empty `global_note` renders, after a literal `---` divider.
- `merge_qa_for_prompt()` wraps the markdown in one `%xprompts_enabled:false` / `%xprompts_enabled:true` pair so
  `#foo` text inside questions or answers is not expanded as an xprompt.

The renderer has focused tests in `tests/test_qa_format.py`, including answer alignment, continuous numbering,
single wrapper pair, TUI preview parity, and disabled-region protection.

## Question And Response Shapes

The question command validates agent-submitted questions as a non-empty list of objects with:

```json
[
  {
    "question": "Full question text",
    "header": "Optional short label",
    "options": [{"label": "Option label", "description": "Optional detail"}],
    "multiSelect": false
  }
]
```

`handle_questions_flow()` writes `question_request.json` with that list, a `session_id`, and a timestamp. It waits for
`question_response.json` and then annotates the loaded response with `_question_request_path`,
`_question_response_path`, and `_question_session_id`.

The response shape produced by the TUI is:

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

Mobile produces the same top-level response shape, but normally with one answer for the selected indexed question.
That is why the canonical input must preserve original `questions` alongside the response, rather than using a lossy
pair list.

## XPrompt Constraints

Relevant xprompt findings from the prior work are also verified:

- XPrompt inputs are primitive typed values: `word`, `line`, `text`, `path`, `int`, `bool`, and `float`.
- A pure `.md` xprompt would have to parse strings or duplicate renderer logic in Jinja. That violates the parity
  requirement.
- A `.yml` workflow can run a hidden `python` pre-step and then emit a `prompt_part`.
- Embedded workflow pre-step output is available to the `prompt_part`, so the workflow can call Python helpers and
  substitute the combined prompt.
- `#name(args):: trailing text` maps trailing text to an argument. Keep `prompt` as the first input so
  `#with_q_and_a(qa_file=/tmp/rounds.json):: prompt text` remains ergonomic.
- Inline `[[...]]` text blocks are useful but fragile for raw JSON because any nested `]]` closes the block. A path to
  a JSON file is the safest public contract.

The Q&A markdown can contain a runtime `---` divider for the global note. That divider is safe if the
`#with_q_and_a` template itself has no static top-level `---`:

- Launch paths split raw prompts before normal xprompt expansion.
- Multi-agent xprompt re-splitting is based on whether the xprompt's static body contains a top-level `---`.
- Therefore a `---` produced at runtime by the Python renderer is not used for fan-out.

## Input Contract

Use structured rounds as the parity contract.

Canonical public xprompt input should be a `qa_file` path. The file should contain accumulated rounds, preferably as:

```json
{
  "rounds": [
    {
      "questions": [
        {
          "question": "Which DB?",
          "header": "Database",
          "options": [{"label": "PostgreSQL"}, {"label": "SQLite"}],
          "multiSelect": false
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
        "global_note": "Prefer the lower-risk path."
      }
    }
  ]
}
```

The loader can also accept these normalizations:

- A single-round object: `{"questions": [...], "response": {...}}`.
- Already-normalized round objects: `{"questions": [...], "answers": [...], "global_note": "..."}`.
- A top-level list of normalized rounds.

Simple `{"question": "...", "answer": "..."}` pairs may be useful as convenience sugar, but they are not the parity
contract. They lose headers, options, unchecked alternatives, multi-select state, text-match alignment, and global note
semantics. If supported, normalize them into `QARound` objects and still route through the same renderer.

## Recommended Implementation

Add a small shared prompt-construction API, preferably in `src/sase/main/qa_markdown.py` or a sibling
`src/sase/main/qa_prompt.py` so public xprompt code does not import runner internals:

```python
def build_qa_round(questions: list[dict[str, Any]], response: dict[str, Any]) -> QARound:
    ...

def merge_qa_for_prompt(rounds: list[QARound]) -> str:
    body = build_merged_qa_markdown(rounds)
    return f"%xprompts_enabled:false\n{body}\n%xprompts_enabled:true"

def assemble_question_followup_prompt(base_prompt: str, rounds: list[QARound]) -> str:
    return base_prompt + "\n\n" + merge_qa_for_prompt(rounds)

def qa_rounds_from_payload(payload: object) -> list[QARound]:
    ...
```

Keep compatibility wrappers in `src/sase/axe/run_agent_helpers_questions.py` / `run_agent_helpers.py` during the move.

Then change `handle_questions_marker()` to call:

```python
state.current_prompt = assemble_question_followup_prompt(
    state.question_base_prompt,
    state.qa_rounds,
)
```

Implement `src/sase/xprompts/with_q_and_a.yml` as an embeddable workflow:

```yaml
description: Append answered SASE user questions to a prompt using the same renderer as agent follow-ups.

input:
  - name: prompt
    type: text
    description: Base prompt for the follow-up agent.
  - name: qa_file
    type: path
    description: JSON file containing one or more Q&A rounds.

steps:
  - name: render
    hidden: true
    python: |
      import json
      from pathlib import Path
      from sase.main.qa_prompt import assemble_question_followup_prompt, qa_rounds_from_payload

      payload = json.loads(Path({{ qa_file | tojson }}).read_text(encoding="utf-8"))
      rounds = qa_rounds_from_payload(payload)
      combined = assemble_question_followup_prompt({{ prompt | tojson }}, rounds)
      print(json.dumps({"combined": combined}))
    output: { combined: text }

  - name: emit
    prompt_part: |
      {{ render.combined }}
```

Usage:

```text
#with_q_and_a(qa_file=/tmp/qa_rounds.json):: Implement the requested change.
```

or, when avoiding shorthand ambiguity:

```text
#with_q_and_a(prompt=[[Implement the requested change.]], qa_file=/tmp/qa_rounds.json)
```

Do not make the xprompt launch a follow-up agent directly. That would require reproducing family suffix allocation,
artifact mutation, workflow metadata, notification handling, and chat bookkeeping outside the runner context. The
xprompt should produce the prompt; the runner should keep the runner-only side effects.

## Tests To Add

Add focused tests rather than broad end-to-end coverage:

- `qa_rounds_from_payload()` accepts multi-round, single-round, normalized, and mobile one-answer payloads.
- `assemble_question_followup_prompt(base, rounds)` is byte-identical to the current
  `base + "\n\n" + merge_qa_for_prompt(rounds)` expression.
- Embedded `#with_q_and_a` expansion equals direct `assemble_question_followup_prompt()` for a fixture containing
  multi-round questions, global note, `Other`, unknown labels, and `#literal` answer text.
- `handle_questions_marker()` still rebuilds code-phase questions from `state.question_base_prompt` and keeps one
  Q&A section across repeated rounds.
- A fixture with a global note proves the runtime `---` does not create multiple launch segments.

Existing tests to extend include `tests/test_qa_format.py` and
`tests/test_axe_run_agent_exec_plan_followup_questions.py`.

## Recommended Solution

Implement `#with_q_and_a` as an embeddable YAML workflow whose hidden Python step calls a shared
`assemble_question_followup_prompt(base_prompt, rounds)` helper. Move or expose the pure Q&A prompt helpers outside
runner-specific modules, make `handle_questions_marker()` call the same helper directly, and pin both entry points with
a parity test.

Use `qa_file` containing structured rounds as the canonical public input. Support simple pairs only as optional
normalization sugar, not as the internal contract. This preserves byte-for-byte prompt parity, protects xprompt
references inside user answers, avoids inline JSON delimiter hazards, and leaves artifact/metadata/family-lineage work
in the runner where that context already exists.
