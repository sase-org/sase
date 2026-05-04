---
create_time: 2026-05-04 15:54:50
bead_id: sase-22
tier: epic
status: done
prompt: sdd/prompts/202605/resume_optional_name.md
---
# Plan: Optional `#resume` Name Input

## Goal

Make `#resume` usable without an explicit `name` argument while preserving deterministic behavior in multi-prompt
workflows.

Required behavior:

- `#resume:<name>` and `#resume(<name>)` keep their current behavior.
- Bare `#resume` defaults to the most recently launched named agent.
- Bare `#resume` inside a multi-prompt markdown workflow defaults to the previous agent in that same expanded segment
  list for every segment after the first.
- The multi-prompt default must be resolved before launching the child process so concurrently launched multi-prompt
  workflows cannot race through the global “most recent agent” lookup.
- The Python logic currently embedded in `src/sase/xprompts/resume.yml` should move into a new `agent_chat_from_name`
  Python script/module.
- Add focused tests for the new script and integration tests around the race-sensitive multi-prompt rewrite path.

## Phase 1: Extract Resume Chat Resolution

Files likely owned by this phase:

- `src/sase/scripts/agent_chat_from_name.py`
- `src/sase/scripts/__init__.py`
- `pyproject.toml`
- `src/sase/xprompts/resume.yml`
- `tests/scripts/test_agent_chat_from_name.py` or equivalent test module

Implementation outline:

1. Add `src/sase/scripts/agent_chat_from_name.py` with a small public function, for example
   `resolve_agent_chat_path(name: str | None) -> str`.
2. Preserve the existing lookup order:
   - For an explicit name, first use `find_named_agent(name, only_done=True)` and read `response_path` from `done.json`.
   - If no `response_path` exists, use `find_named_agent(name)` and read `chat_path` from `agent_meta.json`.
   - Raise a clear runtime error if the selected agent has no usable chat history.
3. Add omitted-name behavior:
   - If `name` is `None`, empty, or omitted, resolve the most recent named agent.
   - Exclude the current agent’s artifacts directory when `SASE_ARTIFACTS_DIR` is set, so bare `#resume` does not
     accidentally resume itself after its own metadata has been written.
   - Skip dismissed-prefixed names consistently with the existing bare `%wait` behavior.
4. Provide a `main()` entry point that prints exactly the workflow-friendly JSON shape: `{"path": "<chat-path>"}`.
5. Wire the script as an installable project script if needed, but keep `resume.yml` able to import and call the Python
   module directly from a `python` step.
6. Update `src/sase/xprompts/resume.yml` so the `name` input is explicitly optional, and replace the inline lookup code
   with a call to `agent_chat_from_name`.

Tests for this phase:

- Explicit completed agent uses `done.json.response_path`.
- Explicit running or non-done agent falls back to `agent_meta.json.chat_path`.
- Missing or malformed metadata is ignored and produces a clear failure when no chat path exists.
- Omitted name uses the most recent named agent.
- Omitted name excludes `SASE_ARTIFACTS_DIR` so the current agent is not selected as its own resume source.
- Omitted name fails clearly when there is no previous named agent.
- The script `main()` emits parseable JSON with the `path` key.

Verification for this phase:

- Run the new script tests directly.
- Run the existing agent-name tests that cover `get_most_recent_agent_name` and resume naming behavior.

## Phase 2: Deterministic Multi-Prompt Bare `#resume`

Files likely owned by this phase:

- `src/sase/agent/multi_prompt_launcher.py`
- `tests/test_multi_prompt_launcher_resume.py` or additions to existing multi-prompt launcher tests

Implementation outline:

1. Add helpers parallel to the existing bare `%wait` helpers:
   - Detect top-level bare `#resume` references with no argument.
   - Rewrite those bare references to explicit `#resume:<previous_agent_name>`.
   - Protect fenced blocks and disabled regions.
   - Do not rewrite `#resume:<name>`, `#resume(<name>)`, `#resume_by_chat`, or examples inside fences.
2. In `_spawn_segments_into`, treat a following segment with bare `#resume` the same way as a following segment with
   bare `%wait` for predecessor name planning.
3. Before launching segment `N > 0`, rewrite bare `#resume` in the segment to the previous agent’s planned or polled
   name.
4. If the previous segment’s name cannot be planned parent-side, poll the previous segment’s `agent_meta.json` before
   launching the next segment. This is required for bare `#resume`, not just bare `%wait`, because letting the child do
   a global default lookup would be race-prone.
5. Preserve current behavior for the first segment: bare `#resume` remains bare and is resolved by the script’s global
   “most recent previous agent” default.
6. Keep the existing multi-model and `%alt` semantics: when a segment fans out, the default for the next segment should
   be the last spawned agent in that segment’s fanout, matching the current `%wait` behavior.

Tests for this phase:

- `["%name:builder\nBuild", "#resume\nReview"]` launches the second prompt with `#resume:builder`.
- `["Build", "#resume\nReview"]` plans an auto name for the first segment via `SASE_AGENT_PLANNED_NAME` and rewrites the
  second segment to that name.
- A predecessor containing xprompt references, where parent-side naming is not safely knowable, polls `agent_meta.json`
  and rewrites the next bare `#resume` to the polled name.
- A first segment containing bare `#resume` is not rewritten.
- Explicit `#resume:foo` and `#resume(foo)` are not rewritten.
- Fenced and disabled-region `#resume` examples are not rewritten.
- Multi-model or `%alt` fanout rewrites a later bare `#resume` to the last generated agent name, matching existing bare
  `%wait` tests.

Verification for this phase:

- Run the new multi-prompt launcher tests.
- Run existing multi-prompt launcher tests to ensure `%wait`, VCS context, local xprompt serialization, and fanout
  behavior are unchanged.

## Phase 3: End-to-End Workflow Coverage And Cleanup

Files likely owned by this phase:

- `tests/test_xprompt_processor_workflow.py`, `tests/test_workflow_executor.py`, or a new focused workflow test file
- Documentation or catalog-facing files only if existing tests show optional input rendering needs adjustment

Implementation outline:

1. Add a focused workflow-level test that loads the real `src/sase/xprompts/resume.yml` and verifies that omitting
   `name` does not fail input validation.
2. Add a test that an embedded bare `#resume` ultimately uses the new resolver output and feeds `load_chat_for_resume`
   through the returned path. Mock the chat loader if a full transcript fixture would be noisy.
3. Check whether xprompt browsing/snippet/catalog rendering treats `name` as optional once `resume.yml` declares a
   default; update only if tests reveal stale required-input presentation.
4. Run broad validation:
   - `just install` first if this workspace has not been prepared recently.
   - Targeted pytest for script, multi-prompt, workflow-loader, workflow-executor, and agent-name tests.
   - `just check` before final handoff, per repo instructions.

## Risks And Design Notes

- The global default must not select the current agent. The safest practical boundary is excluding `SASE_ARTIFACTS_DIR`,
  since workflow execution sets it before embedded workflow steps run.
- Multi-prompt determinism should live in the parent launcher, not in the child `#resume` resolver. The parent has the
  only reliable in-memory ordering for “previous agent in this same markdown file”.
- Reusing the existing planned-name machinery keeps behavior aligned with bare `%wait` and avoids a second naming
  convention.
- The new script should be small and testable; `resume.yml` should only bridge workflow input to that script and leave
  chat loading to the existing `load_history` step.
