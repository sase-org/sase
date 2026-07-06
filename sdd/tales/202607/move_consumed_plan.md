---
create_time: 2026-07-06 10:45:56
status: done
prompt: sdd/prompts/202607/move_consumed_plan.md
---
# Move consumed `sase plan propose` files

## Context

`sase plan propose <plan_file>` currently validates the submitted Markdown file, formats it in place, archives it
through `save_plan_to_sase()`, writes a `.sase_plan_pending` marker, pulses ACE, and terminates the agent runner. The
archive helper in `src/sase/llm_provider/_plan_utils.py` strips the `sase_plan_` prefix, picks a sharded
`~/.sase/plans/YYYYMM/` destination with the existing dedup counter behavior, and then copies the source file with
`shutil.copy2()`.

The proposed-plan marker uses the archived `plan_file` path for downstream approval and handoff work. Its
`original_file` field is not consumed elsewhere today, so it can remain as provenance even after the scratch
`sase_plan_*.md` file is moved away.

## Desired behavior

After a successful `sase plan propose sase_plan_feature.md`, the plan should live only in the machine-local archive as
`~/.sase/plans/YYYYMM/feature.md` or a deduplicated sibling such as `feature_1.md`. The scratch file submitted to the
command should no longer exist. The marker should continue to point `plan_file` at the archived path so approval, ACE,
auto-approval, SDD commit, and plan search behavior keep using the durable archive copy.

## Implementation plan

1. Change the archive operation used by `sase plan propose` from copy semantics to move semantics while preserving the
   current destination rules:
   - keep `sase_plan_` prefix stripping;
   - keep sharded `~/.sase/plans/YYYYMM/` placement;
   - keep the existing dedup counter behavior when an archived plan with the target name already exists;
   - use `shutil.move()` so same-filesystem moves are renames and cross-filesystem moves still copy then unlink.

2. Make the utility contract explicit. Either rename the helper to move-oriented language or add a move-specific helper
   and update `plan_propose_handler` to call it. Avoid leaving handler code that appears to copy when the command now
   consumes the input.

3. Keep `.sase_plan_pending` schema stable:
   - `plan_file` remains the archived path and is the only live path downstream code should rely on;
   - `original_file` can remain the resolved submitted path for debugging/provenance, even though it is no longer
     expected to exist after a successful proposal.

4. Add focused test coverage:
   - utility-level coverage that a `sase_plan_*.md` input is moved into the archive, renamed without the prefix, and
     removed from its original location;
   - utility-level coverage that dedup still works when the archive already has the target basename;
   - handler-level coverage that `sase plan propose` writes the marker with an existing archived `plan_file`, deletes
     the consumed source file, and archives the formatted content;
   - update the repeat pulse test so it creates a fresh scratch plan before the second invocation, because the first
     invocation should consume the original.

5. Keep documentation changes minimal. The existing user-facing docs already describe `sase plan propose` as submitting
   a file for approval and `~/.sase/plans/` as the local archive; this behavior change probably does not need new CLI
   docs unless tests reveal a more specific description already claims copy semantics.

## Verification

Run `just install` first, then focused tests for the changed surface:

```bash
pytest tests/test_plan_command_handler.py tests/test_plan_utils.py
```

After implementation file changes, run the required repository check:

```bash
just check
```
