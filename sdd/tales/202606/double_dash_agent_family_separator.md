---
create_time: 2026-06-02 21:02:48
status: done
prompt: sdd/prompts/202606/double_dash_agent_family_separator.md
---
# Plan: Double-Dash Agent Family Separator

## Goal

Switch plan-family agent names from single-dash phase names such as `foo-plan`, `foo-2`, `foo-q`, and `foo-code` to
double-dash phase names such as `foo--plan`, `foo--2`, `foo--q`, and `foo--code`.

The user-visible rule should become: normal user agent names may contain single hyphens, but user-specified launch or
rename names containing `--` are invalid because `--` is reserved for generated agent-family phases.

## Scope

- Update the canonical naming behavior in `src/sase/plan_chain.py`.
- Keep older persisted artifacts readable by canonicalizing legacy `.plan`, `.2`, `.code`, and old single-dash `-plan`,
  `-2`, `-code` metadata to the new double-dash canonical suffixes.
- Update launch, mobile launch, TUI rename, and direct directive validation so explicit user names reject `--` with a
  clear error while allowing ordinary single-hyphen names.
- Keep indexed names (`build-@` -> `build-1`) working, and update their validation/docs so single-hyphen bases are not
  rejected solely because `-` is no longer reserved.
- Update docs, comments, and tests that describe or assert canonical plan-family suffixes.

## Compatibility Design

The new canonical separator will be `--`. New artifacts and generated follow-up names should store and render
`role_suffix` values such as `--plan`, `--2`, `--q`, and `--code`.

Legacy support should be read-only and normalization-based:

- `canonical_plan_chain_suffix("-plan")` and `canonical_plan_chain_suffix(".plan")` should return `--plan`.
- `canonical_plan_chain_suffix("-2")` and `canonical_plan_chain_suffix(".2")` should return `--2`.
- Metadata readers should continue recognizing old artifacts even if they only have `name: foo-code` plus
  `workflow_name: foo`.
- New generated names should never emit the old single-dash family separator.

Because user names can now contain single hyphens, code should avoid treating a plain name like `foo-code` as a family
child unless it is reading legacy plan-chain metadata or the row already carries plan-family metadata. Canonical
family-name parsing should prefer `--`; legacy single-dash parsing should be used only where needed for persisted
artifacts.

## Implementation Steps

1. Update `src/sase/plan_chain.py`:
   - Add a central family separator constant.
   - Change plan/question/coder/epic/legend/commit suffix constants to use `--`.
   - Change feedback suffix generation to return `--<round>`.
   - Canonicalize legacy dotted and single-dash suffixes to the new double-dash suffixes.
   - Add or adjust helpers so numeric feedback detection does not assume a one-character separator.

2. Update validation:
   - Change `AgentNameSyntaxError` and `validate_user_agent_name()` to reject `--`, not all `-`.
   - Rename or reword internal `allow_hyphenated_names` plumbing so it means “allow reserved family separator names” for
     trusted generated launches.
   - Preserve the existing internal bypass env var for compatibility.
   - Update mobile launch and TUI rename tests/messages to assert the new error text.

3. Update launch and workflow behavior:
   - Ensure `run_agent_exec_plan` and artifact helpers emit new double-dash generated names and `role_suffix` metadata
     via the shared helpers.
   - Update status override and prompt-panel phase-label helpers so `--2` displays as the expected feedback round.
   - Keep existing legacy `.plan`/`.code` and old `-plan`/`-code` fixtures readable.

4. Update indexed-name helpers:
   - Keep the `-@` indexed-template marker.
   - Allow single hyphens in indexed-name bases unless the base contains the reserved `--` separator or `@`.
   - Update related comments/tests so they no longer say arbitrary hyphenated user names are invalid.

5. Update references and docs:
   - Update `docs/ace.md` examples and phase descriptions from `a-plan` / `-plan` / `-code` to `a--plan` / `--plan` /
     `--code` where describing canonical new behavior.
   - Update code comments and test names that refer to canonical “hyphen suffixes” when they now mean double-dash family
     suffixes.
   - Leave unrelated CLI flags, VCS hyphen behavior, and non-agent-family suffixes alone.

6. Test:
   - Run focused suites for plan-chain naming, launch validation, mobile launch validation, agent-name lookup/resume,
     plan-exec chat names, wait chat resolution, status override/phase label behavior, and indexed names.
   - Then run `just install` if needed and `just check`, per repo guidance, before reporting completion.

## Risks and Mitigations

- Ambiguity with new user names like `foo-code`: mitigate by treating `--` as the canonical family separator and using
  old single-dash parsing only for legacy metadata compatibility.
- Large fixture churn: mitigate by updating focused assertions and comments, not unrelated strings that happen to
  contain hyphens.
- Hidden single-character separator assumptions: mitigate by adding helper coverage for `--2` and updating downstream
  phase-label/status helpers to use normalized feedback parsing rather than slicing off one character.
