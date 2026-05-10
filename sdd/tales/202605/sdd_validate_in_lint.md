---
create_time: 2026-05-09 20:19:28
status: done
prompt: sdd/prompts/202605/sdd_validate_in_lint.md
---
# Plan: Run SDD Validation From `just lint`

## Context

The repository already has a `sdd-validate` Just recipe:

```just
sdd-validate: _setup
    {{ venv_bin }}/sase sdd validate
```

The public `lint` target currently runs keep-sorted, ruff, mypy, tool layout validation, and pyvision. It does not run
SDD link validation. The CI lint job compensates by running `just sdd-validate` as a dedicated step before `just lint`.

The full local `just check` target does not invoke `just lint`; it expands the lint stages manually through
`tools/run_silent` to keep agent output compact. Therefore, changing only the public `lint` recipe would make
`just lint` stricter but leave `just check` with weaker coverage than the lint target. That would be surprising in this
repo, because `just check` is the required final gate after code changes.

## Goals

- Make `sase sdd validate` run whenever a developer runs `just lint`.
- Preserve `just sdd-validate` as the focused command for SDD link validation.
- Keep `just check` at least as strong as `just lint` by adding the same SDD validation stage to its wrapped lint
  sequence.
- Avoid duplicate SDD validation in CI once `just lint` owns that responsibility.
- Keep the change small and in the existing Justfile/CI style.

## Implementation

1. Update `Justfile` comments for `lint` so they mention SDD validation alongside the existing lint gates.

2. Add a SDD validation stage to the public `lint` recipe by invoking the existing focused recipe:

   ```just
   @printf "\n---------- Validating SDD frontmatter links... ----------\n"
   @just sdd-validate
   ```

   This reuses the existing `_setup` dependency and avoids duplicating the command body.

3. Add the same gate to `just check` using the established compact wrapper:

   ```just
   @tools/run_silent "lint (sdd validate)" just sdd-validate
   ```

   Place it with the other lint stages, before tests. A good ordering is after keep-sorted or after pyvision; either is
   functionally equivalent. Keeping it near the other static checks makes failures easy to categorize.

4. Remove the dedicated `.github/workflows/ci.yml` step named `Validate SDD links`, because the later `Lint` step will
   now run `just lint`, and `just lint` will include SDD validation. This avoids running the same validation twice in
   the lint job.

5. Leave the standalone `sdd-validate` recipe intact for targeted local and CI debugging.

## Verification

Run these commands after editing:

```bash
just install
just sdd-validate
just lint
just check
```

Expected results:

- `just sdd-validate` passes as the focused validation command.
- `just lint` output includes the new SDD validation section and passes.
- `just check` prints a compact success line for the new SDD validation stage and passes.
- CI no longer has a separate SDD validation step, but the `Lint` step still covers SDD links through `just lint`.

## Risks and Mitigations

- **Runtime increase in `just lint`:** SDD validation scans the SDD tree, but it is already running in CI today and is a
  static validation gate. The cost is acceptable for lint.
- **Duplicate setup work:** Calling `just sdd-validate` from `lint` re-enters `_setup`, as the existing lint subrecipes
  do. This matches the current Justfile pattern and keeps each focused recipe independently runnable.
- **`just check` divergence:** Explicitly adding the `sdd-validate` stage to `check` prevents `just check` from becoming
  a weaker gate than `just lint`.
