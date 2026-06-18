# Research: `#with_q_and_a` xprompt

**Date:** 2026-06-18
**Author:** Agent research pass
**Status:** Research / recommendation (no code changes)

## Goal

Design a new `#with_q_and_a` xprompt that takes **one or more question/answer pairs** plus **a base
prompt** as inputs and produces the prompt an agent should run with after the user has answered.

Two hard requirements from the request:

1. The xprompt must **perfectly replicate the requirements for the agents we run when the user
   answers an agent's question(s)** — i.e. byte-for-byte the same follow-up prompt the runner builds
   today.
2. We also want to **use this xprompt internally as the actual logic triggered when the user answers
   an agent's question(s)**, so parity must be guaranteed by construction (not by two copies that can
   drift).

This document reverse-engineers both the question-answer flow and the xprompt machinery, then
recommends an implementation that satisfies both requirements.

---

## 1. The parity target: what happens today when a user answers a question

The internal flow that we must replicate lives in the agent execution loop.

### 1.1 Entry point

`src/sase/axe/run_agent_exec_questions.py` → `handle_questions_marker(q_data, ctx, state)`
(lines 75–237). It is invoked when an agent leaves a `sase questions` marker. The relevant steps:

1. Normalize/finalize the interrupted phase's artifacts.
2. Resolve **base meta** from the *interrupted phase's* `agent_meta.json`
   (`_interrupted_phase_meta`, lines 45–62) so the follow-up inherits the concrete worker
   model/provider that ran the interrupted phase — **not** the planner metadata.
3. Notify the user and poll for the answer (`handle_questions_flow`).
4. Build a `QARound` from the questions + the user's response and append it to `state.qa_rounds`.
5. Render the **merged** Q&A section across *all* accumulated rounds.
6. Allocate the follow-up agent's family suffix/role and create its artifacts (inheriting base meta +
   question relationship metadata).
7. **Assemble the follow-up prompt** (the line we care about most):

```python
# src/sase/axe/run_agent_exec_questions.py:219
state.current_prompt = state.question_base_prompt + "\n\n" + merged_qa_text
```

8. Store the follow-up prompt artifact and update the SDD prompt snapshot.

### 1.2 The two pieces of the follow-up prompt

**(a) `question_base_prompt`** — `src/sase/axe/run_agent_exec_types.py:71,80-82`

> "Base prompt for question continuations: the currently executing phase's prompt before merged Q&A
> is appended. Refreshed on phase transitions … Defaults to the initial prompt at loop start."

It is set to `state.current_prompt` at phase transitions
(`run_agent_exec_plan.py:231`, `run_agent_exec_plan_accept.py:468`) and defaults to
`original_prompt`. Crucially it **carries the phase's `%model` directive verbatim** — the code's own
comment (lines 217-219) says a code-phase question "keeps the code prompt and its `%model`
directive." This is the prompt-level mechanism for model inheritance.

**(b) `merged_qa_text`** — `src/sase/axe/run_agent_helpers_questions.py:149-154`

```python
def merge_qa_for_prompt(rounds: list[QARound]) -> str:
    """Render accumulated Q&A rounds as a single prompt-bound section."""
    from sase.main.qa_markdown import build_merged_qa_markdown
    body = build_merged_qa_markdown(rounds)
    return f"%xprompts_enabled:false\n{body}\n%xprompts_enabled:true"
```

So the merged text is the rendered markdown wrapped in `%xprompts_enabled:false` …
`%xprompts_enabled:true` markers.

### 1.3 The Q&A markdown renderer (single source of truth)

`src/sase/main/qa_markdown.py`:

- `QARound` dataclass (lines 21-33): `questions: list[dict]`, `answers: list[dict]`,
  `global_note: str | None`.
- `build_merged_qa_markdown(rounds)` (lines 94-128): emits exactly one `### Questions and Answers`
  header, flattens every round's questions into one monotonic numbering (`#### Q1`, `#### Q2`, …),
  renders each question as a blockquote with checkbox-style options, and appends the *last non-empty*
  global note after a `---` separator line.
- `build_qa_markdown(...)` (lines 131-155): thin single-round wrapper used by the TUI live preview.

The docstring is explicit that this formatter is "used by both the user-question TUI modal (live
preview) and the follow-up agent prompt section, so the two cannot drift apart." This is the existing
**single-source-of-truth pattern** we should extend, not break.

Example rendered output:

```markdown
### Questions and Answers

#### Q1: Which approach?

> What color should we use?

- [x] **Blue** — Cooler color
- [ ] **Red** — Warmer color
- [x] **Other:** "Purple gradient"

---

> **Global Note:** Prefer accessibility-friendly colors
```

### 1.4 How a round is built from raw inputs

`src/sase/axe/run_agent_helpers_questions.py` → `build_qa_round(questions, response)`
(lines 123-146) aligns the response's `answers` to the question list (by index if lengths match,
else by question text) and returns a `QARound`. Inputs:

- `questions`: list of dicts shaped `{header, question, options:[{label,description}], multiSelect}`
  (from `question_request.json`).
- `response`: `{answers:[{question, selected:[labels], custom_feedback}], global_note}`
  (from `question_response.json`).

### 1.5 What is prompt-level vs launcher-level

Separating these matters for scoping the xprompt:

| Requirement | Where it lives | In the prompt text? |
|---|---|---|
| Base phase prompt (incl. `%model`) | `question_base_prompt` | ✅ yes |
| Merged Q&A markdown | `merge_qa_for_prompt` / `build_merged_qa_markdown` | ✅ yes |
| `%xprompts_enabled:false/true` wrapper | `merge_qa_for_prompt` | ✅ yes |
| Worker model/provider inheritance | `_interrupted_phase_meta` + `%model` in base prompt | partly (via `%model`) |
| Agent-family suffix/role lineage | `allocate_agent_family_child_suffix`, `create_followup_artifacts` | ❌ no |
| Question relationship metadata, chat history, SDD snapshot | `handle_questions_marker` | ❌ no |

**Conclusion:** the *prompt* an xprompt can own is exactly
`base_prompt + "\n\n" + merge_qa_for_prompt(rounds)`. The family-lineage / artifacts / metadata are
mid-loop launcher scaffolding that is not part of the prompt and should stay in
`handle_questions_marker`. Model selection is already captured at the prompt level via the inherited
`%model` directive, so prompt-level parity also captures model parity for the agent.

---

## 2. How xprompts work (the building blocks available)

### 2.1 Two forms

- **Simple xprompt (`.md`)**: front matter + body → a single `prompt_part` step
  (`src/sase/xprompt/models.py`).
- **Workflow xprompt (`.yml`)**: multiple typed steps (`prompt`/`agent`, `bash`, `python`,
  `prompt_part`, `use`, `parallel`). Schema: `src/sase/xprompts/workflow.schema.json`.

### 2.2 Typed inputs

Both forms declare typed `input` args (`InputType`: `word`, `line`, `text`, `path`, `int`, `bool`,
`float`). Longform (`[{name, type, default, description}]`) or shortform (`{name: type}`) — see
`loader_parsing.parse_inputs_from_front_matter` and the schema's `inputDefinitions`.

### 2.3 Argument call syntax (`src/sase/xprompt/processor.py`, `_parsing_args.py`)

- Parenthesis: `#foo(a, b)`, `#foo(name=value)`, positional + named.
- Colon: `#foo:word`, `#foo: multi-line text`.
- Plus: `#foo+` ≡ `#foo:true`.
- **Text blocks**: `#foo([[ … multi-line … ]])` and `#foo(name=[[ … ]])` — preserve newlines and
  commas/equals. **Caveat:** a `[[ … ]]` block is delimited by `]]`, so embedding raw JSON that ends
  in nested `]]` (e.g. `[["x"]]`) can prematurely close the block. Prefer paths or command
  substitution for JSON payloads.
- Command substitution: `#foo:$(cmd)` / `#foo(a, $(cmd))`.

### 2.4 `python` / `bash` steps and inter-step data flow

(`src/sase/xprompt/workflow_executor_steps_script.py`, `workflow_executor_utils.py`)

- The step body is **Jinja2-rendered against the workflow context** (inputs + prior step outputs +
  globals) before execution.
- A `python` step runs under `sys.executable` (the sase venv), so `import sase.*` works — it can call
  the exact internal renderer.
- Step stdout is parsed by `parse_bash_output`: JSON first (`{...}`/`[...]`), then `key=value` lines,
  then `{"_output": text}`. **JSON output preserves multi-line strings (including literal `---`)
  verbatim**, which is what we need for the Q&A markdown.
- Output is stored at `self.context[step.name]` and is referenceable from later steps via
  `{{ step_name.field }}`.

### 2.5 Embeddable workflow → `prompt_part`, can follow a `python` step

(`src/sase/xprompt/workflow_executor_steps_embedded.py:230-288`,
`_resolve_tagged_workflow_content`)

When a workflow is referenced inline (`#foo(...)`), its **pre-steps execute first** to build a
context, then the `prompt_part` step's content is `render_template(content, tagged_ctx)`-rendered with
that context and substituted in place. **A `prompt_part` can therefore reference a prior `python`
step's output** — this is the key capability the recommendation relies on.

### 2.6 Expansion vs. multi-agent `---` splitting (critical for parity)

This was the riskiest interaction, because the Q&A markdown contains a literal `---` (global-note
separator) and is wrapped in `%xprompts_enabled:false`. Findings, verified against source:

1. **Launch order splits *before* expanding.** `launch_cwd_agents.py:88` calls
   `parse_multi_prompt(query)` on the *raw* user text first, then expands xprompts within each
   segment (`expand_multi_agent_xprompts_with_metadata`, lines 121-124). A user's
   `#with_q_and_a(...)` (with no literal `---` of their own) is a single segment at split time.

2. **Re-splitting after expansion only happens for *statically* multi-agent xprompts.**
   `expand_multi_agent_xprompts_with_metadata` builds the multi-agent set as:

   ```python
   # src/sase/agent/multi_agent_xprompt.py:580-581
   multi_agent_names = {
       name for name, xp in catalog.items() if xprompt_has_segment_separators(xp)
   }
   ```

   and `xprompt_has_segment_separators` (`src/sase/xprompt/segment_separators.py`) checks the
   xprompt's **static body** for a top-level `---`. The inline path `expand_single_xprompt`
   (`processor.py:183-193`) likewise only calls `split_segments_protecting_fences` *if*
   `xprompt_has_segment_separators(xprompt)` is true.

   **Therefore:** as long as `#with_q_and_a`'s own template has **no literal top-level `---`** (ours
   comes only from the runtime-rendered Q&A), it is never classified as multi-agent and its runtime
   `---` is never treated as a segment separator.

3. `%xprompts_enabled:false` regions are excluded from `#`-reference expansion
   (`_real_xprompt_references` in `multi_agent_xprompt.py:340-347` skips `disabled_region_ranges`), so
   any `#` characters in user answers won't expand. Note this protection is for `#`-expansion, **not**
   for `---` splitting — but per (2) the `---` is already safe by classification.

4. **`%`-directives** (`%model`, `%name`, `%wait`, `%group`, `%approve`, `%xprompts_enabled`, …) are
   extracted/stripped in `extract_prompt_directives` (`src/sase/xprompt/directives.py`) early in
   preprocessing and apply to the whole prompt regardless of appended text. So keeping the base prompt
   verbatim (with its `%model:`) preserves model selection.

**Net:** an embeddable `#with_q_and_a` workflow that produces `base + "\n\n" + wrapped_QA` is safe to
expand inline; the global-note `---` will not fan out into multiple agents.

---

## 3. Input-format options

The Q&A data is structured (questions carry options + multiSelect; answers carry selected labels +
custom feedback; rounds accumulate). The internal renderer requires that structure, so the canonical
input must preserve it.

| Option | Fidelity | Robustness | Internal-parity fit | Verdict |
|---|---|---|---|---|
| **A. Path to a rounds JSON file** (`[{questions, answers, global_note}, …]`) | full | high (no arg escaping) | high — runner already writes `question_request.json` / `question_response.json` | **recommended canonical** |
| B. Path to a `request.json` + `response.json` pair | full | high | highest — exactly the runner's artifacts | recommended convenience for single round |
| C. Inline JSON via `$(cat …)` or text block | full | medium (`]]`/quoting caveats) | medium | supported, documented caveat |
| D. Simple `(question, answer)` string pairs | lossy (no options/checkboxes) | high | low — would need a divergent render path | convenience adapter only |

Rounds accumulate in the real flow (`merge_qa_for_prompt(state.qa_rounds)` renders *all* rounds), so
the input must be a **list of rounds**; single-round manual use is just a one-element list.

---

## 4. Recommended solution

### 4.1 Principle: one renderer, two entry points

Keep a **single source of truth** for prompt assembly and expose it through the xprompt. Concretely:

1. Extract the existing assembly expression into one shared helper (next to the existing renderers),
   e.g. in `src/sase/axe/run_agent_helpers_questions.py` (or `qa_markdown.py`):

   ```python
   def assemble_question_followup_prompt(base_prompt: str, rounds: list[QARound]) -> str:
       """The follow-up prompt the runner uses after a user answers questions."""
       return base_prompt + "\n\n" + merge_qa_for_prompt(rounds)
   ```

2. Change `handle_questions_marker` line 219 to call it:

   ```python
   state.current_prompt = assemble_question_followup_prompt(
       state.question_base_prompt, state.qa_rounds
   )
   ```

3. Implement `#with_q_and_a` as a **workflow xprompt whose `python` step calls the same helper**.
   Because both paths call `assemble_question_followup_prompt` → `merge_qa_for_prompt` →
   `build_merged_qa_markdown`, parity is guaranteed by construction and cannot drift.

This honors "use this xprompt workflow internally": the workflow and the runner are the *same logic*.
The runner keeps the launcher scaffolding (family lineage, artifacts, metadata) that is not part of
the prompt; the xprompt owns exactly the portable prompt-assembly contract.

### 4.2 The xprompt file (`xprompts/with_q_and_a.yml`)

An embeddable, prompt-producing workflow. The `python` step renders via the shared helper and emits
JSON (preserving multiline + `---`); the `prompt_part` step substitutes it in place.

```yaml
description: >
  Append a rendered Questions-and-Answers section to a base prompt, exactly as the
  runner does after a user answers an agent's question(s).

input:
  prompt:
    type: text
    description: Base prompt the follow-up agent should run (kept verbatim, incl. %model).
  qa_file:
    type: path
    description: >
      Path to a JSON file holding the accumulated Q&A rounds:
      [{ "questions": [...], "answers": [...], "global_note": "..." }, ...].
      Shapes match the runner's question_request.json (questions) and
      question_response.json (answers + global_note).

steps:
  - name: _render
    hidden: true
    python: |
      import json
      from sase.main.qa_markdown import QARound
      # Single source of truth — same call the runner uses:
      from sase.axe.run_agent_helpers_questions import assemble_question_followup_prompt

      with open(r"{{ qa_file }}", encoding="utf-8") as f:
          raw_rounds = json.load(f)
      rounds = [
          QARound(
              questions=r.get("questions", []),
              answers=r.get("answers", []),
              global_note=r.get("global_note"),
          )
          for r in raw_rounds
      ]
      combined = assemble_question_followup_prompt(r"""{{ prompt }}""", rounds)
      print(json.dumps({"combined": combined}))
    output:
      combined: text

  - name: emit
    prompt_part: |
      {{ _render.combined }}
```

Notes:
- The template body contains **no top-level `---`**, so it is never classified as a multi-agent
  xprompt (§2.6). The runtime `---` inside the rendered Q&A is therefore safe.
- The `python` step imports the shared helper rather than re-formatting markdown, so there is exactly
  one renderer.
- `qa_file` (a `path`) sidesteps the `[[…]]`/quoting fragility of inline JSON (§2.3). For quick manual
  use, `qa_file=$(... )` or a small temp file both work.

### 4.3 Usage

Manual:

```
#with_q_and_a(prompt=[[ Implement the feature as discussed. ]], qa_file=/tmp/rounds.json)
```

where `/tmp/rounds.json` is:

```json
[
  {
    "questions": [
      {"header": "Approach", "question": "Which color?",
       "options": [{"label": "Blue", "description": "Cooler"},
                   {"label": "Red", "description": "Warmer"}],
       "multiSelect": false}
    ],
    "answers": [{"question": "Which color?", "selected": ["Blue"], "custom_feedback": null}],
    "global_note": "Prefer accessibility-friendly colors"
  }
]
```

Internal: `handle_questions_marker` already has `state.question_base_prompt` and `state.qa_rounds`;
it calls `assemble_question_followup_prompt(...)` directly (the workflow's `python` step is the same
call), so no behavior change — only deduplication.

### 4.4 Optional convenience adapter (form D)

For lightweight manual use without crafting full question dicts, add an alternate `python` branch (or
a sibling `_qa_from_pairs` helper) that maps simple `{question, answer}` pairs into single-option
selected `QARound`s:

```python
# answer "Blue" → a question whose single option label is "Blue", selected.
QARound(
    questions=[{"question": q, "options": [{"label": a, "description": ""}], "multiSelect": False}],
    answers=[{"question": q, "selected": [a], "custom_feedback": None}],
    global_note=None,
)
```

This still routes through `build_merged_qa_markdown`, so it renders consistently
(`- [x] **Blue**`). Keep it as an explicit convenience path; the canonical structured input remains
the parity contract.

---

## 5. Alternatives considered

- **Pure `.md` (single `prompt_part`) xprompt that re-implements the markdown in Jinja.** Rejected:
  duplicates the renderer → guaranteed eventual drift, violating requirement (1). Jinja also cannot
  faithfully reproduce the alignment / last-non-empty-global-note / unknown-label-surfacing logic in
  `build_merged_qa_markdown` without becoming a second implementation.

- **A `.yml` whose `python` step launches the follow-up agent directly** (à la
  `xprompts/pylimit_split.yml`'s `launch_agent_from_cwd`). Rejected as the primary shape: it changes
  semantics from "produce a prompt" to "spawn an agent," and it would have to reproduce the runner's
  family-lineage/model-inheritance/artifact scaffolding, which is mid-loop context the xprompt does
  not have. A prompt-producing embeddable workflow keeps the xprompt composable and the scaffolding
  where it belongs.

- **Inline JSON via text blocks as the canonical input.** Rejected as canonical due to the `]]`
  delimiter collision with nested JSON arrays (§2.3); supported as a documented convenience.

---

## 6. Risks / open questions

1. **Import cost & circulars.** The `python` step imports `assemble_question_followup_prompt` from
   `sase.axe.run_agent_helpers_questions`. Confirm that module is import-safe in a bare `python -c`
   subprocess (it currently does lazy imports of `qa_markdown`, which is fine). If the dependency
   graph is awkward, host the shared helper in `sase.main.qa_markdown` instead (it already owns the
   renderer and has no heavy deps).
2. **Multi-round semantics.** The canonical input is a *list* of rounds because the runner renders all
   accumulated rounds each time. Verify manual callers understand "one element per round" and that the
   last non-empty `global_note` wins.
3. **`%xprompts_enabled` nesting.** If a caller already wraps their base prompt in
   `%xprompts_enabled:false`, the appended Q&A adds a second nested pair. Confirm
   `protect_disabled_regions` tolerates this (it uses non-greedy matching) or document that the base
   prompt should not pre-wrap.
4. **Generated-skill / CLI contract.** xprompts can surface as skills; if `#with_q_and_a` should be
   user-invocable as a skill, review `memory/generated_skills.md` for the skill-generation contract.
5. **Tests.** Add a parity test asserting
   `assemble_question_followup_prompt(base, rounds)` equals the workflow's emitted `combined` for a
   shared fixture set (including multi-round + global-note + "Other" + unknown-label cases), so the two
   entry points are pinned together.

---

## 7. Recommendation (summary)

Implement `#with_q_and_a` as an **embeddable `.yml` workflow** whose single `python` step calls a new
shared helper `assemble_question_followup_prompt(base_prompt, rounds)` — itself a one-liner over the
existing `merge_qa_for_prompt` / `build_merged_qa_markdown` renderer — and emits the combined prompt
through a `prompt_part`. Refactor `run_agent_exec_questions.py:219` to call the same helper. Take the
canonical input as a **path to a rounds JSON file** (shapes matching the runner's
`question_request.json` / `question_response.json`), with a documented convenience adapter for simple
pairs.

This gives byte-for-byte parity by construction (one renderer, two entry points), keeps the global
-note `---` safe from multi-agent fan-out (the template has no static `---`), preserves model
selection via the base prompt's `%model` directive, and cleanly leaves launcher scaffolding
(family lineage, artifacts, metadata) where it already lives.
