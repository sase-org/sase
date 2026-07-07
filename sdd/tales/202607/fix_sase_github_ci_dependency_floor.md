---
create_time: 2026-07-07 12:47:25
status: done
prompt: sdd/prompts/202607/fix_sase_github_ci_dependency_floor.md
---
# Fix failing sase-github GitHub Actions CI (sase version-floor resolution failure)

## Problem

Every CI job in `sase-org/sase-github` that installs dependencies is failing on master (run 28880828118, commit
`73e3c4b` "fix: preserve canonical refs in GitHub resolution"):

- `lint` — fails at "Install dependencies"
- `test (3.13)` — fails at "Install dependencies"
- `test (3.12)` — cancelled by fail-fast

The failing step output:

```
× No solution found when resolving dependencies:
╰─▶ Because only sase<=0.10.2 is available and sase-github==0.1.6 depends on
    sase>=0.10.3, we can conclude that sase-github==0.1.6 cannot be used.
```

## Root Cause

Three facts collide:

1. Commit `73e3c4b` raised sase-github's dependency floor from `sase>=0.6.0` to `sase>=0.10.3` because the change needs
   the new shared `ResolvedRef` field, which exists on sase master but has not shipped in any release yet.
2. sase master's `pyproject.toml` still declares `version = "0.10.2"` — release-please only bumps the version when a
   release PR merges. The currently pending release-please PR for sase is for **0.11.0** (there are feat commits since
   0.10.2), so version `0.10.3` will _never exist_.
3. sase-github CI installs sase from a checkout of `sase-org/sase@master` (at `SASE_CORE_PATH=.ci/sase`). The `Justfile`
   `install` recipe does `uv pip install -e "${SASE_CORE_PATH}"` (installs `sase==0.10.2` from source), then
   `uv pip install -e ".[dev]"` — and uv's resolver correctly rejects the environment because no available sase
   satisfies `>=0.10.3`.

This is also a _structural_ problem, not just a one-off: the entire point of the `.ci/sase` master checkout is to test
sase-github against unreleased sase. Any time a sase-github change legitimately raises its sase floor ahead of the next
sase release, CI will break in exactly this way, because master's version metadata always lags the next release.

## Fix (all changes in the sase-github linked repo)

### 1. `Justfile` — make the install recipe immune to unreleased-sase version lag

When `SASE_CORE_PATH` is set, use a uv **overrides file** to replace the `sase` requirement with an editable install
from the checkout path, so the declared version floor is bypassed for source installs (that is exactly what overrides
are for — the source checkout is authoritative in CI):

```just
install:
    @[ -x {{ venv_bin }}/python ] || uv venv {{ venv_dir }}
    @if [ -n "${SASE_CORE_PATH:-}" ]; then \
        printf -- '-e %s\n' "$(realpath "${SASE_CORE_PATH}")" > {{ venv_dir }}/sase-overrides.txt; \
        uv pip install --overrides {{ venv_dir }}/sase-overrides.txt -e ".[dev]"; \
    else \
        uv pip install -e ".[dev]"; \
    fi
```

Notes:

- The separate up-front `uv pip install -e "${SASE_CORE_PATH}"` step becomes unnecessary: the override itself pulls sase
  in editable from the checkout during the single `.[dev]` install. (Empirically verified: fresh venv + single install
  with the editable override resolves cleanly, installs sase editable from the source checkout, and the full sase-github
  test suite passes — 92/92.)
- The override file is written inside `{{ venv_dir }}` so it is gitignored and cleaned up with the venv.
- `realpath` is used because requirement paths in override files must be unambiguous regardless of resolution cwd;
  `SASE_CORE_PATH` is relative (`.ci/sase`) in CI.
- No workflow YAML changes are needed — `ci.yml` and `publish.yml` already set `SASE_CORE_PATH` and call `just install`.

### 2. `pyproject.toml` — correct the dependency floor to a version that will exist

Change `dependencies = ["sase>=0.10.3"]` to `dependencies = ["sase>=0.11.0"]`.

The intent of `73e3c4b` was "the release that provides `ResolvedRef`"; per the pending sase release-please PR, that
release is 0.11.0. `0.10.3` will never be published, so the current floor is wrong metadata even though `>=0.10.3` would
technically be satisfied by 0.11.0 once released.

## Verification

1. In the sase-github workspace: `just install` with `SASE_CORE_PATH` pointing at a sase master checkout → must resolve
   and install cleanly (this reproduces the CI path; the failure is currently reproducible locally with the same error).
2. `just install` _without_ `SASE_CORE_PATH` unset behavior unchanged (plain `uv pip install -e ".[dev]"`).
3. `just check` (ruff + mypy + pytest) in the sase-github repo passes.
4. After the fix lands on sase-github master, confirm the CI run goes green (lint + test 3.12/3.13 jobs all reach past
   "Install dependencies").

## Caveats / follow-ups (no action in this change)

- **Release ordering:** sase-github's next release (0.1.7) must not be merged/published from its release-please PR until
  sase 0.11.0 is actually released to the package index, otherwise the published sase-github would be uninstallable
  (`sase>=0.11.0` unsatisfiable). CI itself is unaffected thanks to the override.
- The plain-`uv pip install` (no `SASE_CORE_PATH`) path will also fail today because the index has no sase ≥0.11.0 yet;
  that resolves itself when sase 0.11.0 ships and is the semantically correct behavior (sase-github master genuinely
  requires unreleased sase features).
