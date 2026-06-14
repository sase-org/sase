---
create_time: 2026-06-14 17:06:34
status: done
prompt: sdd/prompts/202606/remove_plan_directive_1.md
---
# Remove the Legacy Manual Planning Directive

## Context

SASE now uses the `/sase_plan` skill plus the `sase plan` approval pipeline for explicit planning, and `%epic` still
uses that same pipeline for SDD epic approval. The old manual planning xprompt directive (the percent-prefixed `plan`
token, with the one-letter percent-prefixed `p` alias) should be removed as a supported user-facing directive.

Initial inspection shows the live behavior is concentrated in:

- `src/sase/xprompt/_directive_types.py`: known directive table, alias table, and `PromptDirectives.plan`.
- `src/sase/xprompt/directives.py`: extraction into `PromptDirectives`.
- `src/sase/axe/run_agent_directives.py`: metadata writes that set `agent_meta["plan"]` and `AgentInfo.plan`.
- `src/sase/ace/tui/widgets/directive_completion.py`: prompt completion metadata.
- `src/sase/history/prompt_metadata.py`: prompt-history control-token summaries, indirectly via the known directive
  tables.
- Tests and visual fixtures that currently expect the legacy directive to be recognized.
- Docs/blog/SDD text that still presents the old directive as available.

Sibling workspace checks for workspace 10 found no literal legacy directive references in `sase-github`,
`sase-telegram`, or `sase-nvim`. `sase-core` only carries generic plan-approval metadata such as
`auto_approve_plan_action`, which should remain because `%epic` and the plan approval workflow still use it.

## Goals

- Remove the legacy manual planning directive and its short alias from all active parsing, launch, completion,
  prompt-history, and documentation surfaces.
- Keep `/sase_plan`, `sase plan propose`, `sase plan approve`, plan approval notifications, follow-up coder launches,
  and `%epic` behavior intact.
- Keep the persisted `agent_meta["plan"]` concept intact for submitted plans and `%epic` agents; remove only the
  obsolete directive as a way to set it.
- Remove or reword stale references in docs and SDD material so the repository no longer advertises or tests the removed
  directive.
- Preserve unrelated uses of the letter `p`, especially ACE keybindings such as copy prompt/project spec.

## Implementation Plan

1. Remove parser support.
   - Delete the `plan` entry from `_KNOWN_DIRECTIVES`.
   - Delete the `p -> plan` alias from `_DIRECTIVE_ALIASES`.
   - Remove `plan: bool` from `PromptDirectives`.
   - Remove `plan="plan" in expanded_args` from directive extraction.
   - Add/adjust tests so the removed directive token and alias are treated like unknown percent-prefixed text: they
     remain in the prompt and do not set metadata or duplicate-directive errors.

2. Update launch metadata.
   - Change `run_agent_directives.py` so `agent_meta["plan"]` and `AgentInfo.plan` are driven by `%epic` only.
   - Keep `auto_approve_plan_action: "epic"` behavior unchanged.
   - Update tests around `AgentInfo.plan`, `agent_meta["plan"]`, and enrichment comments so they describe plan-review
     metadata rather than the removed directive.

3. Update prompt completion and prompt history.
   - Remove the removed directive from completion candidates, argument hints, descriptions, and alias summaries by
     relying on the updated directive tables.
   - Update completion tests so the alias no longer completes to a planning directive.
   - Update prompt-history tests and visual fixtures to use surviving directives such as `%model`, `%name`, `%group`, or
     `%epic` where the test needs a recognized directive, and to assert that the removed directive is not summarized as
     metadata.
   - Run visual snapshot tests if fixture text changes affect prompt-history screenshots; update snapshots only if the
     changed text intentionally alters the baseline.

4. Update VCS tag parsing/replacement tests.
   - Existing tests use the removed directive as a representative skipped directive before a VCS tag. Replace those
     examples with surviving directives, usually `%name` or `%model`.
   - Add one negative case if useful: the removed directive no longer participates in known-directive stripping or
     summary behavior.

5. Update documentation and generated/reference docs.
   - Remove the removed directive from `docs/xprompt.md`, `docs/ace.md`, active blog posts, configuration docs, and any
     directive tables or examples.
   - Remove the stale `SASE_AGENT_PLAN_MODE` environment documentation because inspection found no live code references.
   - Rephrase plan workflow docs around `/sase_plan`, `sase plan propose`, `sase plan approve`, and `%epic`.
   - Reword SDD/research/tale references that enumerate available directives or show the old directive as a current
     example, while avoiding edits to protected memory files.

6. Verify and clean up.
   - Run focused tests first: directive parsing, directive completion, prompt metadata/history modal, VCS tag
     parsing/replacement, expand-for-spec, launch directive metadata, and plan/epic follow-up tests.
   - Run `just install` if needed, then `just check` because code/docs/test files will have changed.
   - Finish with exact repository searches for the removed directive token, its directive alias context,
     `directives.plan`, `PromptDirectives.plan`, and `SASE_AGENT_PLAN_MODE`.
   - Manually inspect remaining hits to confirm they are unrelated `p` keybindings, generic planning workflow names, or
     historical plan-approval metadata that must stay.

## Risks and Mitigations

- Risk: deleting `agent_meta["plan"]` entirely would break plan approval and `%epic` status rendering. Mitigation: keep
  the metadata field, but make `%epic` and actual plan submission paths the remaining producers.
- Risk: prompt-history behavior changes for old saved prompts containing the removed directive. Mitigation: treat the
  removed token as ordinary prompt text after removal; tests should make that behavior explicit.
- Risk: broad text search may catch unrelated plan workflow docs and ACE `%p` keybindings. Mitigation: classify hits by
  semantic role before editing, and preserve unrelated references.
- Risk: SDD files are historical records. Mitigation: only reword stale references that advertise or enumerate the
  removed directive as current behavior; do not modify memory files.

## Validation Commands

```bash
pytest tests/test_directives_flags.py tests/test_directives_extract.py tests/ace/tui/widgets/test_directive_completion.py tests/history/test_prompt_metadata.py tests/ace/tui/modals/test_prompt_history_modal.py tests/test_xprompt_vcs_tag_parsing.py tests/test_xprompt_vcs_tag_replacement.py tests/test_expand_for_spec.py
pytest tests/test_enrich_agent_plan_meta.py tests/test_core_agent_scan_records.py tests/test_plan_utils.py tests/test_axe_run_agent_exec_plan_followup_approvals.py
just install
just check
rg -n --hidden --glob '!.git' '<removed directive literal>|SASE_AGENT_PLAN_MODE|directives\.plan|PromptDirectives\.plan|plan=\"plan\"'
```
