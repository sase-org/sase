---
create_time: 2026-06-19 09:49:19
status: done
prompt: sdd/prompts/202606/fork_implies_wait.md
---
# Plan: Make `#fork:<name>` Imply `%w:<name>`

## Context

Users currently need prompts like `#fork:<name> %w:<name>` when they want a new agent to fork a running agent's chat and
wait for that agent before starting. This duplicated directive text leaks into multiple UI/copy surfaces:

- ACE Agents-tab fork action pre-fills `#fork:<name> %w:<name>` for running named agents.
- Telegram launch notification buttons and `/fork` buttons copy `#fork:<name> %w:<name>`.
- Telegram still has separate wait-only buttons, which should continue to copy `%w:<name>` because they are not fork
  actions.

The requested behavior is that a prompt containing top-level `#fork:<name>` should automatically behave as if
`%w:<name>` were also present. If the user also provides other `%w` or `%wait` directives, the launched agent should
wait for all explicitly specified dependencies plus the fork target.

## Proposed Behavior

1. `#fork:<name> Continue` extracts wait metadata `wait_for=["<name>"]`.
2. `#fork:<name> %w:other Continue` extracts `wait_for=["other", "<name>"]`.
3. `#fork:<name> %w:<name> Continue` extracts `wait_for=["<name>"]`, not a duplicate.
4. `#fork` without an explicit name keeps the existing bare-fork behavior and should not create a new implicit wait,
   because the target is resolved dynamically by the fork workflow and may intentionally use "most recent previous
   agent" semantics.
5. `#fork_by_chat:<path>` and legacy `#resume` behavior remain unchanged.
6. Fork-derived naming keeps priority: a fork prompt should still get `<name>.fN` naming even when implicit wait
   metadata is added.
7. Explicit multi-wait prompts should continue to avoid wait-derived naming when more than one dependency exists.

## Main Repo Implementation

1. Add a small fork-target extraction helper near the existing fork/resume parsing helpers.
   - Reuse the established top-level parsing behavior from `sase.agent.names._resume.first_resume_agent_name`.
   - Protect fenced blocks and `%xprompts_enabled:false` disabled regions.
   - Resolve agent-name template references the same way explicit fork references already do.
   - Exclude `#fork_by_chat` and bare `#fork`.

2. Apply implicit fork waits in the directive extraction path.
   - In `src/sase/axe/run_agent_directives.py`, after `extract_prompt_directives(expanded_for_directives)`, inspect
     `raw_resolved_prompt` for an explicit `#fork:<name>` target.
   - Append the fork target to `directives.wait` if it is not already present.
   - Keep this as runner metadata behavior rather than rewriting user prompt text. That preserves prompt history and
     submitted/raw xprompt artifacts while making all launch surfaces behave consistently.
   - Use a local `wait_names` list for metadata, `AgentInfo`, and wait-derived naming decisions so the frozen
     `PromptDirectives` dataclass does not need to grow mutation-specific behavior.

3. Preserve naming precedence.
   - Keep `resume_name = first_resume_agent_name(raw_resolved_prompt)` as the source for fork-derived `.fN` naming.
   - Use the augmented `wait_names` for `agent_meta["wait_for"]`, `AgentInfo.wait_names`, and `wait_for_dependencies`.
   - Only set `wait_name` for wait-derived naming when there is exactly one augmented wait target and no fork-derived
     `resume_name`, preserving current multiple-wait fallback behavior.

4. Update ACE fork prompt prefill.
   - Change the running-named-agent branch in `src/sase/ace/tui/actions/agents/_wait_resume.py` from
     `#fork:<name> %w:<name> ` to `#fork:<name> `.
   - Leave explicit wait actions (`action_wait_for_agent`, bulk wait, edit wait target) unchanged because those are
     wait-specific workflows.

5. Consider repeat and multi-prompt planned naming interactions.
   - Verify that `single_wait_agent_name` and `PlannedNameAllocator` continue to prefer fork-derived naming where fork
     is present.
   - Add regression coverage if any allocator path would accidentally derive `.wN` from the implicit wait instead of
     `.fN`.

## Telegram Repo Implementation

Use the numbered sibling workspace opened with:

```bash
sase workspace open -p sase-telegram 13
```

1. Update copy text that represents a fork action to only copy `#fork:<name>`.
   - `src/sase_telegram/scripts/sase_tg_inbound.py`
     - Launch notification "Fork" button: `#fork:<name> `
     - `/fork` command buttons: `#fork:<name> `
   - Preserve VCS prefixes such as `#gh:sase ` exactly as today.

2. Leave wait-only buttons alone.
   - Launch notification "Wait" buttons should still copy `%w:<name>`.
   - This keeps a direct wait workflow available when the user does not want to fork chat history.

3. `src/sase_telegram/formatting.py` already appears to copy only `#fork:<name>`, so keep it unchanged unless further
   tests reveal another `%w`-bearing fork copy path.

## Tests

Main repo:

1. Add directive/runner metadata tests around `extract_directives_and_write_meta`.
   - `raw_resolved_prompt="#fork:foo do stuff"` writes `wait_for=["foo"]` and still names the agent `foo.f1`.
   - `prompt="%wait:bar expanded prompt"`, `raw_resolved_prompt="#fork:foo\n%wait:bar do stuff"` writes
     `wait_for=["bar", "foo"]` and names the agent `foo.f1`.
   - Existing explicit duplicate `#fork:foo %wait:foo` writes a single `foo` wait.
   - Bare `#fork` does not add implicit wait.

2. Update ACE tests for running-agent fork prefill.
   - Running named agent fork prefill should be `#fork:<name> `.
   - Finished/family-root fork prefill tests should remain unchanged.

3. Run focused tests first:
   - `pytest tests/test_agent_names_extract.py tests/ace/tui/test_agent_wait_resume.py tests/ace/tui/test_agent_marking_wait_fork.py`

4. Because source files in the main repo changed, finish with:
   - `just install`
   - `just check`

Telegram repo:

1. Update tests currently expecting `#fork:<name> %w:<name>`.
   - `tests/test_inbound.py` launch/fork copy-text assertions.
   - Keep wait-button assertions expecting `%w:<name>`.

2. Run focused Telegram tests:
   - `pytest tests/test_inbound.py tests/test_formatting.py`

3. Run the Telegram repo's standard check command if defined after inspecting its project docs/Justfile.

## Risks and Notes

- The implicit wait should be metadata-only. Rewriting the prompt text would make history noisier and would fight the
  user's explicit request that copy/prefill surfaces stop emitting `%wait`.
- Bare `#fork` is intentionally excluded from implicit waits. It resolves late and can choose a previous agent by
  context; adding an automatic wait there risks self-wait or surprising waits.
- The behavior belongs in the Python runner/directive layer for this change. The Rust core workspace currently exposes
  xprompt catalogs and artifact scan wire behavior, but not prompt directive extraction or fork runtime semantics.
