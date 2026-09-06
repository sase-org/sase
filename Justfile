# sase task runner

venv_dir := ".venv"
venv_bin := venv_dir / "bin"
venv_dir_abs := if venv_dir =~ "^/" { venv_dir } else { justfile_directory() / venv_dir }
venv_bin_abs := venv_dir_abs / "bin"
demo_venv_dir := ".venv-demos"
demo_venv_bin := demo_venv_dir / "bin"
demo_venv_dir_abs := justfile_directory() / demo_venv_dir
keep_sorted_version := "v0.8.0"
keep_sorted_bin := venv_bin / "keep-sorted"
prettier_bin := "node_modules/.bin/prettier"

# Linked Rust core repo. CI can override this with SASE_CORE_DIR after
# checking out sase-core inside the Actions workspace. SASE-launched agents
# provide workspace-matched linked checkouts via SASE_LINKED_REPO_SASE_CORE_DIR
# and primary host checkouts via SASE_LINKED_REPO_SASE_CORE_PRIMARY_DIR. Trust
# workspace-scoped env paths only when they point under this Justfile checkout;
# otherwise a shell inherited from another numbered workspace must use the
# primary checkout or the checkout-relative fallback.
workspace_sase_core_dir := "sase/repos/linked/sase-core"
fallback_sase_core_dir := if path_exists(workspace_sase_core_dir) == "true" { workspace_sase_core_dir } else { "../sase-core" }
justfile_directory_abs := clean(justfile_directory())
linked_sase_core_dir := env_var_or_default("SASE_LINKED_REPO_SASE_CORE_DIR", "")
linked_sase_core_dir_abs := if linked_sase_core_dir != "" { clean(absolute_path(linked_sase_core_dir)) } else { "" }
current_linked_sase_core_dir := if linked_sase_core_dir_abs != "" { if linked_sase_core_dir_abs =~ "^" + justfile_directory_abs + "(/|$)" { linked_sase_core_dir } else { "" } } else { "" }
sibling_sase_core_dir := env_var_or_default("SASE_SIBLING_REPO_SASE_CORE_DIR", "")
sibling_sase_core_dir_abs := if sibling_sase_core_dir != "" { clean(absolute_path(sibling_sase_core_dir)) } else { "" }
current_sibling_sase_core_dir := if sibling_sase_core_dir_abs != "" { if sibling_sase_core_dir_abs =~ "^" + justfile_directory_abs + "(/|$)" { sibling_sase_core_dir } else { "" } } else { "" }
legacy_sibling_core_dir := env_var_or_default("SASE_SIBLING_REPO_CORE_DIR", "")
legacy_sibling_core_dir_abs := if legacy_sibling_core_dir != "" { clean(absolute_path(legacy_sibling_core_dir)) } else { "" }
current_legacy_sibling_core_dir := if legacy_sibling_core_dir_abs != "" { if legacy_sibling_core_dir_abs =~ "^" + justfile_directory_abs + "(/|$)" { legacy_sibling_core_dir } else { "" } } else { "" }
linked_sase_core_primary_dir := env_var_or_default("SASE_LINKED_REPO_SASE_CORE_PRIMARY_DIR", "")
sibling_sase_core_primary_dir := env_var_or_default("SASE_SIBLING_REPO_SASE_CORE_PRIMARY_DIR", "")
legacy_sibling_core_primary_dir := env_var_or_default("SASE_SIBLING_REPO_CORE_PRIMARY_DIR", "")
sase_core_dir := env_var_or_default("SASE_CORE_DIR", if current_linked_sase_core_dir != "" { current_linked_sase_core_dir } else if current_sibling_sase_core_dir != "" { current_sibling_sase_core_dir } else if current_legacy_sibling_core_dir != "" { current_legacy_sibling_core_dir } else if linked_sase_core_primary_dir != "" { linked_sase_core_primary_dir } else if sibling_sase_core_primary_dir != "" { sibling_sase_core_primary_dir } else if legacy_sibling_core_primary_dir != "" { legacy_sibling_core_primary_dir } else { fallback_sase_core_dir })

# Prefer the workspace-matched sase-github checkout for demo recordings. The
# PyPI package remains the fallback for source trees without a linked checkout.
workspace_sase_github_dir := "sase/repos/linked/sase-github"
fallback_sase_github_dir := if path_exists(workspace_sase_github_dir) == "true" { workspace_sase_github_dir } else { "../sase-github" }
sase_github_dir := env_var_or_default("SASE_GITHUB_DIR", env_var_or_default("SASE_LINKED_REPO_SASE_GITHUB_DIR", env_var_or_default("SASE_SIBLING_REPO_SASE_GITHUB_DIR", fallback_sase_github_dir)))

# Dev installs build sase_core_rs from the local checkout or install the
# SASE_CORE_WHEEL supplied by CI, so the published sase-core-rs version window
# in pyproject.toml must not constrain (or downgrade) that build during
# dependency resolution. In either case editable install recipes pass a uv
# overrides file that lifts the window.
core_overrides_file := venv_dir / "sase-core-rs-overrides.txt"

# The pinned renderer stack makes exact PNG equality the default in every
# visual-bearing lane. The SASE_VISUAL_PNG_* environment variables remain
# available as explicit escape hatches for renderer investigations and local
# iteration on non-canonical platforms.

default:
    @just --list

# Bootstrap .venv if it doesn't exist.
_venv:
    @[ -x {{ venv_bin }}/python ] || uv venv {{ venv_dir }}

# Print the `--overrides <file>` argument that lifts the published
# sase-core-rs version window for dev installs. Prints nothing when no
# buildable sase-core checkout or explicit SASE_CORE_WHEEL exists, keeping the
# pyproject constraint authoritative for normal published-wheel resolution.
_core-overrides-arg:
    @if [ -n "${SASE_CORE_WHEEL:-}" ] || { [ -f "{{ sase_core_dir }}/Cargo.toml" ] && command -v cargo > /dev/null 2>&1; }; then \
        printf "sase-core-rs\n" > "{{ core_overrides_file }}"; \
        printf -- "--overrides {{ core_overrides_file }}"; \
    fi

# Bootstrap .venv and install editable dev dependencies. Build the local
# Rust extension first when a source checkout and Rust toolchain are
# available, because `sase[dev]` depends on the `sase-core-rs` distribution.
# validate_test_environment caches and dispatches validate_sase_core_rs_version,
# validate_sase_core_rs, validate_dependency_group, and validate_editable_metadata.
_setup: _venv
    @validation_status=0; \
    check_core=""; \
    if [ -n "${SASE_CORE_WHEEL:-}" ]; then \
        if [ ! -f "$SASE_CORE_WHEEL" ]; then \
            printf "error: SASE_CORE_WHEEL does not name a wheel file: %s\n" "$SASE_CORE_WHEEL" >&2; \
            exit 2; \
        fi; \
        printf "[setup] Installing prebuilt sase_core_rs wheel from %s.\n" "$SASE_CORE_WHEEL"; \
        uv pip install --python {{ venv_bin }}/python "$SASE_CORE_WHEEL"; \
    elif [ -d "{{ sase_core_dir }}" ] && [ ! -f "{{ sase_core_dir }}/Cargo.toml" ]; then \
        printf "[setup] sase-core checkout at {{ sase_core_dir }} has no Cargo.toml; treating as absent and using the published sase-core-rs wheel.\n"; \
    elif [ -f "{{ sase_core_dir }}/Cargo.toml" ] && command -v cargo > /dev/null 2>&1; then \
        just --set venv_dir "{{ venv_dir }}" --set sase_core_dir "{{ sase_core_dir }}" _refresh-sase-core-checkout; \
        check_core="--check-core"; \
    fi; \
    {{ venv_bin }}/python tools/validate_test_environment \
        --venv-dir "{{ venv_dir_abs }}" \
        --pyproject pyproject.toml \
        --uv-lock uv.lock \
        --sase-core-dir "{{ sase_core_dir }}" \
        $check_core --check-editable --group dev || validation_status=$?; \
    if [ "$validation_status" -ge 64 ]; then \
        exit "$validation_status"; \
    fi; \
    if [ $((validation_status & 16)) -ne 0 ]; then \
        if [ "${SASE_ALLOW_STALE_CORE:-}" = "1" ]; then \
            printf "[setup] WARNING: the sase-core checkout at {{ sase_core_dir }} is behind the sase-core-rs floor in pyproject.toml; proceeding because SASE_ALLOW_STALE_CORE=1.\n"; \
        else \
            printf "[setup] ERROR: the sase-core checkout is behind the sase-core-rs floor in\npyproject.toml; the extension built from it will not satisfy sase's tests.\nIn a SASE workspace run 'sase repo open sase-core'; otherwise update the checkout\ndirectly. Then rerun 'just install'.\nSet SASE_ALLOW_STALE_CORE=1 to proceed anyway (intentional bisects only).\n" >&2; \
            exit "$validation_status"; \
        fi; \
    fi; \
    if [ $((validation_status & 1)) -ne 0 ]; then \
        printf "[setup] Note: the sase-core checkout is ahead of the published sase-core-rs window in pyproject.toml; dev installs build from {{ sase_core_dir }} regardless. This is normal — the release-branch reconciler ratchets the published window at release time, so no action is needed here.\n"; \
    fi; \
    if [ $((validation_status & 2)) -ne 0 ]; then \
        printf "[setup] Rebuilding stale or missing sase_core_rs from {{ sase_core_dir }} before Python dependency resolution.\n"; \
        just --set venv_dir "{{ venv_dir }}" --set sase_core_dir "{{ sase_core_dir }}" rust-install "{{ venv_dir_abs }}"; \
        {{ venv_bin }}/python tools/validate_sase_core_rs --sase-core-dir "{{ sase_core_dir }}" || exit $?; \
    fi; \
    if [ $((validation_status & 12)) -ne 0 ]; then \
        uv pip install --python {{ venv_bin }}/python --no-sources $(just _core-overrides-arg) --reinstall-package mypy -e ".[dev]"; \
    fi
    @just --set venv_dir "{{ venv_dir }}" _setup-required-plugins

# Bootstrap keep-sorted into the project venv so lint/fix do not depend on a
# user-global Go bin directory being present on PATH.
_setup-keep-sorted: _venv
    @if [ ! -x "{{ keep_sorted_bin }}" ]; then \
        if command -v keep-sorted > /dev/null 2>&1; then \
            printf "[setup] Linking keep-sorted from PATH into {{ keep_sorted_bin }}.\n"; \
            ln -sf "$(command -v keep-sorted)" "{{ keep_sorted_bin }}"; \
        elif command -v go > /dev/null 2>&1; then \
            printf "[setup] Installing keep-sorted {{ keep_sorted_version }} into {{ venv_bin }}.\n"; \
            GOBIN="{{ venv_bin_abs }}" CGO_ENABLED=0 go install github.com/google/keep-sorted@{{ keep_sorted_version }}; \
        else \
            printf "error: keep-sorted is required. Install it or install Go so this recipe can bootstrap github.com/google/keep-sorted@{{ keep_sorted_version }}.\n" >&2; \
            exit 127; \
        fi; \
    fi

# Bootstrap repo-local Prettier so Markdown formatting does not depend on a
# user-global or CI-global npm installation.
_setup-prettier:
    @if [ ! -x "{{ prettier_bin }}" ]; then \
        printf "[setup] Installing repo-local Prettier from package-lock.json.\n"; \
        npm ci --no-audit --no-fund; \
    fi

# Print a box header for a top-level command (private helper)
_header NAME:
    @printf "\n"
    @printf "┌───────────────────────────────────────────────────────┐\n"
    @printf "│                RUNNING: just %-25s│\n" "{{ NAME }}"
    @printf "└───────────────────────────────────────────────────────┘\n"

# Install in editable mode with dev dependencies. If a local sase-core
# checkout is present and a Rust toolchain is on PATH, build and install
# `sase_core_rs` from source first so the pyproject dependency on
# `sase-core-rs` is satisfied before editable resolution. Released `sase`
# wheels resolve the same dependency from the published `sase-core-rs`
# distribution instead.
install: _venv
    @if [ -n "${SASE_CORE_WHEEL:-}" ]; then \
        if [ ! -f "$SASE_CORE_WHEEL" ]; then \
            printf "error: SASE_CORE_WHEEL does not name a wheel file: %s\n" "$SASE_CORE_WHEEL" >&2; \
            exit 2; \
        fi; \
        printf "[install] Installing prebuilt sase_core_rs wheel from %s.\n" "$SASE_CORE_WHEEL"; \
        uv pip install --python {{ venv_bin }}/python "$SASE_CORE_WHEEL"; \
    elif [ -d "{{ sase_core_dir }}" ] && command -v cargo > /dev/null 2>&1; then \
        printf "[install] Installing local sase_core_rs from {{ sase_core_dir }} for local dev.\n"; \
        just --set venv_dir "{{ venv_dir }}" --set sase_core_dir "{{ sase_core_dir }}" rust-install "{{ venv_dir_abs }}"; \
    fi
    uv pip install --python {{ venv_bin }}/python --no-sources $(just _core-overrides-arg) -e ".[dev]"
    @just --set venv_dir "{{ venv_dir }}" _setup-required-plugins

# Install this project's plugins.required into the active venv, verified.
# Reads plugins.required from sase/sase.yml (not a hard-coded name list) and
# resolves each entry from a linked/sibling checkout or PyPI, then imports
# it in the target interpreter to catch a dangling or stale install that uv's
# already-satisfied fast path would otherwise let slide. See its docstring.
_setup-required-plugins:
    {{ venv_bin }}/python tools/setup_required_plugins

# Install in editable mode with dev and visual-test dependencies.
install-visual: _venv
    @if [ -n "${SASE_CORE_WHEEL:-}" ]; then \
        if [ ! -f "$SASE_CORE_WHEEL" ]; then \
            printf "error: SASE_CORE_WHEEL does not name a wheel file: %s\n" "$SASE_CORE_WHEEL" >&2; \
            exit 2; \
        fi; \
        printf "[install-visual] Installing prebuilt sase_core_rs wheel from %s.\n" "$SASE_CORE_WHEEL"; \
        uv pip install --python {{ venv_bin }}/python "$SASE_CORE_WHEEL"; \
    elif [ -d "{{ sase_core_dir }}" ] && command -v cargo > /dev/null 2>&1; then \
        printf "[install-visual] Installing local sase_core_rs from {{ sase_core_dir }} for local dev.\n"; \
        just --set venv_dir "{{ venv_dir }}" --set sase_core_dir "{{ sase_core_dir }}" rust-install "{{ venv_dir_abs }}"; \
    fi
    uv pip install --python {{ venv_bin }}/python --no-sources $(just _core-overrides-arg) -e ".[dev,visual]"

# Bootstrap visual-test dependencies without making them part of the default
# development install.
_setup-visual: _setup
    @validation_status=0; \
    {{ venv_bin }}/python tools/validate_test_environment \
        --venv-dir "{{ venv_dir_abs }}" \
        --pyproject pyproject.toml \
        --uv-lock uv.lock \
        --sase-core-dir "{{ sase_core_dir }}" \
        --group visual || validation_status=$?; \
    if [ "$validation_status" -ge 64 ]; then \
        exit "$validation_status"; \
    fi; \
    if [ $((validation_status & 4)) -ne 0 ]; then \
        uv pip install --python {{ venv_bin }}/python --no-sources $(just _core-overrides-arg) -e ".[dev,visual]"; \
    fi

# The fan-out demo uses an isolated venv so its sase-github install cannot
# change provider discovery for the main test run. The main venv still installs
# plugins.required (see _setup-required-plugins) because memory init / validate
# fail closed without those distributions.
_setup-demos:
    @[ -x {{ demo_venv_bin }}/python ] || uv venv {{ demo_venv_dir }}
    @if [ -f "{{ sase_core_dir }}/Cargo.toml" ] && command -v cargo > /dev/null 2>&1; then \
        if ! {{ demo_venv_bin }}/python tools/validate_sase_core_rs; then \
            printf "[setup-demos] Rebuilding sase_core_rs from {{ sase_core_dir }} for the demo venv.\n"; \
            just --set venv_dir "{{ demo_venv_dir }}" --set sase_core_dir "{{ sase_core_dir }}" rust-install "{{ demo_venv_dir_abs }}"; \
            {{ demo_venv_bin }}/python tools/validate_sase_core_rs; \
        fi; \
    fi
    uv pip install --python {{ demo_venv_bin }}/python --no-sources $(just --set venv_dir "{{ demo_venv_dir }}" _core-overrides-arg) -e .
    @if [ -f "{{ sase_github_dir }}/pyproject.toml" ]; then \
        printf "[setup-demos] Installing workspace-matched sase-github from %s.\n" "{{ sase_github_dir }}"; \
        uv pip install --python {{ demo_venv_bin }}/python --no-deps -e "{{ sase_github_dir }}"; \
    else \
        uv pip install --python {{ demo_venv_bin }}/python sase-github; \
    fi

# Install in editable mode with dev and real-terminal smoke-test dependencies.
install-terminal-smoke: _venv
    @if [ -n "${SASE_CORE_WHEEL:-}" ]; then \
        if [ ! -f "$SASE_CORE_WHEEL" ]; then \
            printf "error: SASE_CORE_WHEEL does not name a wheel file: %s\n" "$SASE_CORE_WHEEL" >&2; \
            exit 2; \
        fi; \
        printf "[install-terminal-smoke] Installing prebuilt sase_core_rs wheel from %s.\n" "$SASE_CORE_WHEEL"; \
        uv pip install --python {{ venv_bin }}/python "$SASE_CORE_WHEEL"; \
    elif [ -d "{{ sase_core_dir }}" ] && command -v cargo > /dev/null 2>&1; then \
        printf "[install-terminal-smoke] Installing local sase_core_rs from {{ sase_core_dir }} for local dev.\n"; \
        just --set venv_dir "{{ venv_dir }}" --set sase_core_dir "{{ sase_core_dir }}" rust-install "{{ venv_dir_abs }}"; \
    fi
    uv pip install --python {{ venv_bin }}/python --no-sources $(just _core-overrides-arg) -e ".[dev,terminal-smoke]"

# Bootstrap real-terminal smoke-test dependencies without making them part of
# the default development install.
_setup-terminal-smoke: _setup
    @validation_status=0; \
    {{ venv_bin }}/python tools/validate_test_environment \
        --venv-dir "{{ venv_dir_abs }}" \
        --pyproject pyproject.toml \
        --uv-lock uv.lock \
        --sase-core-dir "{{ sase_core_dir }}" \
        --group terminal-smoke || validation_status=$?; \
    if [ "$validation_status" -ge 64 ]; then \
        exit "$validation_status"; \
    fi; \
    if [ $((validation_status & 4)) -ne 0 ]; then \
        uv pip install --python {{ venv_bin }}/python --no-sources $(just _core-overrides-arg) -e ".[dev,terminal-smoke]"; \
    fi

# Run linters (ruff + mypy + feature flags + pyscripts + test waits + changelog + terminology audit + symvision + toobig + keep-sorted)
lint: _setup (_header "lint") lint-keep-sorted
    @printf "\n---------- Running ruff linter on Python files... ----------\n"
    @just _lint-ruff
    @printf "\n---------- Running mypy type checker... ----------\n"
    @just _lint-mypy
    @printf "\n---------- Checking feature flag registry integrity... ----------\n"
    @just _lint-flags
    @printf "\n---------- Validating scripts/tools directory structure... ----------\n"
    @just _lint-pyscripts
    @printf "\n---------- Checking retired test wait helpers... ----------\n"
    @just _lint-test-waits
    @printf "\n---------- Validating generated changelog structure... ----------\n"
    @just _lint-changelog
    @printf "\n---------- Auditing Patch/stitch terminology... ----------\n"
    @just _lint-patch-stitch-terminology
    @printf "\n---------- Checking for unused Python definitions... ----------\n"
    @just _lint-symvision
    @printf "\n---------- Checking Python file line counts... ----------\n"
    @just _lint-toobig

# Run ruff linter on Python files (private, extracted for per-stage wrapping)
_lint-ruff: _setup
    {{ venv_bin }}/ruff check src/ tests/

# Run mypy type checker (private, extracted for per-stage wrapping)
_lint-mypy: _setup
    {{ venv_bin }}/mypy
    {{ venv_bin }}/python tools/typecheck_extensionless_tools --mypy {{ venv_bin }}/mypy

# Check feature-flag registry integrity and flag-bead status.
# A future `_lint-backcompat` recipe should register a second marker source on
# this same checker rather than ship another bead-aware expiry linter.
_lint-flags: _setup
    SASE_SYMVISION_BEAD_STATUS_ONLY=1 BD_COMMAND=tools/sase_bead {{ venv_bin }}/python tools/check_feature_flags

# Rewrite the generated feature_flags JSON Schema block from the registry.
sync-feature-flags-schema: _setup
    {{ venv_bin }}/python tools/sync_feature_flags_schema --write

# Rewrite the checked-in structural completion spec snapshot from the argparse tree.
sync-completion-spec: _setup
    {{ venv_bin }}/python tools/sync_completion_spec --write

# Compare legacy bead note blobs with the structured note projection.
check-bead-note-migration *args: _setup
    {{ venv_bin }}/python tools/check_bead_note_migration {{ args }}

# Validate scripts/tools directory structure (private, extracted for per-stage wrapping)
_lint-pyscripts: _setup
    {{ venv_bin }}/python tools/pyscripts-260801

# Check that retired ad-hoc bounded-wait helpers stay retired.
_lint-test-waits: _setup
    {{ venv_bin }}/python tools/check_test_wait_helpers

# Check that CHANGELOG.md contains only release-please sections (private, extracted for per-stage wrapping)
_lint-changelog: _setup
    {{ venv_bin }}/python tools/validate_changelog

# Check canonical Patch/stitch terminology (private, extracted for per-stage wrapping)
_lint-patch-stitch-terminology: _setup
    {{ venv_bin }}/python tools/audit_patch_stitch_terminology --repo-root . --allow-missing-linked-repos

# Check for unused Python definitions (private, extracted for per-stage wrapping)
_lint-symvision *args: _setup
    SASE_SYMVISION_BEAD_STATUS_ONLY=1 BD_COMMAND=tools/sase_bead {{ venv_bin }}/symvision src/sase \
        --exclude-decorator gate_command_entrypoint \
        --exclude-decorator builtin_chop \
        --epic-symbol "sase-n4(get_usage_limit_config)" \
        --epic-symbol "sase-x8(query_artifact_context)" \
        --epic-symbol "sase-x8(ArtifactContextProducerGroup)" \
        {{ args }}

# Check Python file line counts (private, extracted for per-stage wrapping)
_lint-toobig *args:
    {{ venv_bin }}/toobig src {{ if args == "" { "1000 850 700" } else { args } }}
    {{ venv_bin }}/toobig tests {{ if args == "" { "1000 850 700" } else { args } }}

# Auto-fix all code (format + keep-sorted)
fix: (_header "fix") fmt-py fmt-docs fmt-md fix-keep-sorted

# Auto-format all code
fmt: (_header "fmt") fmt-py fmt-docs fmt-md

# Auto-format Python code
fmt-py: _setup
    @printf "\n---------- Formatting Python with ruff... ----------\n"
    {{ venv_bin }}/ruff format src/ tests/
    @printf "\n---------- Fixing Python with ruff... ----------\n"
    {{ venv_bin }}/ruff check --fix src/ tests/

# Auto-format Markdown files
fmt-md: _setup-prettier
    @printf "\n---------- Formatting Markdown with prettier... ----------\n"
    {{ prettier_bin }} --write "**/*.md"

# Render generated Markdown blocks
fmt-docs: _setup
    @printf "\n---------- Rendering generated docs... ----------\n"
    {{ venv_bin }}/python tools/render_model_alias_docs

# Auto-fix keep-sorted blocks in YAML files
fix-keep-sorted: _setup-keep-sorted
    @printf "\n---------- Fixing keep-sorted blocks in YAML files... ----------\n"
    git ls-files -z '*.yml' '*.yaml' | xargs -0 -r sh -c 'for path do [ ! -e "$path" ] || printf "%s\0" "$path"; done' sh | xargs -0 -r {{ keep_sorted_bin }}

# Lint keep-sorted blocks in YAML files (CI mode)
lint-keep-sorted: _setup-keep-sorted
    @printf "\n---------- Checking keep-sorted blocks in YAML files... ----------\n"
    git ls-files -z '*.yml' '*.yaml' | xargs -0 -r sh -c 'for path do [ ! -e "$path" ] || printf "%s\0" "$path"; done' sh | xargs -0 -r {{ keep_sorted_bin }} --mode lint

# Check all formatting (CI mode)
fmt-check: (_header "fmt-check") fmt-py-check fmt-md-check

# Check Python formatting (CI mode)
fmt-py-check: _setup
    @printf "\n---------- Checking Python formatting with ruff... ----------\n"
    {{ venv_bin }}/ruff format --check src/ tests/

# Check Markdown formatting (CI mode)
fmt-md-check: _setup-prettier
    @printf "\n---------- Checking Markdown formatting with prettier... ----------\n"
    {{ prettier_bin }} --check "**/*.md"

# Fast parallel test run, no coverage (use test-cov to enforce coverage gate).
# Excludes the slow and PNG visual snapshot suites; use test-visual for those.
# The runner ignores visual test directories before collection, so this lane
# does not need the pinned visual renderer stack.
[positional-arguments]
test *args: _setup (_header "test")
    @printf "\n---------- Running pytest (parallel, no coverage)... ----------\n"
    @SASE_JUST_INVOCATION_DIR="{{ invocation_directory() }}" {{ venv_bin }}/python tools/run_pytest fast "$@"

# Run the default fast suite with opt-in cost attribution, then print the
# latest attribution report. This loads the heavier cost plugin only for this
# lane; ordinary fast/cov/scoped runs keep the cheap timing recorder.
[positional-arguments]
test-cost *args: _setup (_header "test-cost")
    @printf "\n---------- Running pytest cost attribution lane... ----------\n"
    @SASE_JUST_INVOCATION_DIR="{{ invocation_directory() }}" {{ venv_bin }}/python tools/run_pytest cost "$@"
    @{{ venv_bin }}/python tools/test_cost_report
    @{{ venv_bin }}/python tools/check_test_cost_budgets

# Check the latest test-cost recording against committed suite-cost budgets.
[positional-arguments]
test-cost-budget *args: _setup
    @printf "\n---------- Checking pytest cost budgets... ----------\n"
    @{{ venv_bin }}/python tools/check_test_cost_budgets "$@"

# Run every test module migrated to AcePageGroup with forced fresh AcePage
# instances. This keeps the shared-page optimization honest without recording
# timings or selection-health evidence.
test-ace-page-group-isolated: _setup (_header "test-ace-page-group-isolated")
    @printf "\n---------- Running ACE shared-page forced-isolation lane... ----------\n"
    @SASE_JUST_INVOCATION_DIR="{{ invocation_directory() }}" {{ venv_bin }}/python tools/run_pytest ace-page-group-isolated

# Diff-scoped test lane: selects tests from the change set, runs them serially
# without taking a suite-gate lease, and escalates to the governed full lane
# when the selection is too large or a broadening rule fires.
#
# The middle gear is the one exception to the serial no-lease shape: a
# selection only the serial-runtime budget rejected asks the gate once for a
# small bundle of worker tokens and runs at the granted width instead of
# escalating. It never queues for one — a refused grant escalates.
#
# Depends on `_setup`, not `_setup-visual`, because the selector excludes
# `tests/ace/tui/visual/**` unconditionally, so nothing collected here imports
# Pillow. If that exclusion is ever removed, this recipe must go back to
# `_setup-visual`.
[positional-arguments]
test-scoped *args: _setup (_header "test-scoped")
    @printf "\n---------- Running diff-scoped pytest selection... ----------\n"
    @SASE_JUST_INVOCATION_DIR="{{ invocation_directory() }}" {{ venv_bin }}/python tools/run_pytest scoped "$@"

# Run slow tests (excluded from the default `just test` run)
[positional-arguments]
test-slow *args: _setup (_header "test-slow")
    @printf "\n---------- Running slow pytest subset... ----------\n"
    @SASE_JUST_INVOCATION_DIR="{{ invocation_directory() }}" {{ venv_bin }}/python tools/run_pytest slow "$@"

# Run ACE PNG visual regression tests. This suite is explicit because it uses
# committed PNG snapshot goldens and a PNG rasterizer dependency.
[positional-arguments]
test-visual *args: _setup-visual (_header "test-visual")
    @printf "\n---------- Running visual pytest subset... ----------\n"
    @SASE_JUST_INVOCATION_DIR="{{ invocation_directory() }}" {{ venv_bin }}/python tools/run_pytest visual "$@"

# Reproduce visual convergence flakes by running a fixed 26-worker pool on two
# CPUs (13x oversubscription). Pre-fix baseline, measured 2026-07-27:
# 116 failed, 246 passed, 1 skipped in 567.51s, including one convergence timeout.
# Convergence-only fix (sase-9y.2): 15 failed, 347 passed, 1 skipped in
# 566.68s, with no convergence timeout. Final exact-frame fix (sase-9y.3):
# 363 passed, 1 skipped in 9m37s under the same 26-worker/two-CPU contention,
# retaining exact PNG equality without regenerating goldens.
# Baseline refresh (sase-e9.3), measured 2026-08-02: 405 passed, 1 skipped in
# 605.72s (0:10:05) under the same 26-worker/two-CPU contention path, retaining
# exact PNG equality without regenerating goldens. The local run disabled only
# suite-gate admission because sibling workspaces were holding the shared pool.
# Override the CPU list or worker count with SASE_VISUAL_CONTENTION_CPUS and
# SASE_VISUAL_CONTENTION_WORKERS.
[positional-arguments]
test-visual-contention *args: _setup-visual (_header "test-visual-contention")
    @printf "\n---------- Running visual pytest contention harness... ----------\n"
    @command -v taskset >/dev/null || { printf "test-visual-contention requires taskset\\n" >&2; exit 1; }
    @taskset -c "${SASE_VISUAL_CONTENTION_CPUS:-0,1}" env SASE_PYTEST_WORKERS="${SASE_VISUAL_CONTENTION_WORKERS:-26}" SASE_JUST_INVOCATION_DIR="{{ invocation_directory() }}" {{ venv_bin }}/python tools/run_pytest visual "$@"

# Reproduce the default (non-visual) lane's timing flakes, the same way
# `test-visual-contention` reproduces the PNG lane's: a fixed 26-worker pool on
# two CPUs (13x oversubscription), repeated N times, with a per-node failure
# tally at the end. One pass is not evidence about a class whose base rate is
# under one node per run; the tally is what makes a fix falsifiable.
#
# This lane is an opt-in diagnostic. It takes no suite-gate lease and records
# nothing in the durable selection-health store, and it is deliberately
# unreachable from `just check` and `just check-full`. It starves the host on
# purpose, so other agents' runs on this machine will slow down while it runs.
#
# Pass paths or node IDs to restrict the soak -- a full-suite repeat is far too
# slow to iterate a fix against:
#   just test-contention -- tests/ace/tui/test_stall_watchdog_telemetry.py
#
# Pre-fix baseline (sase-h8.1), measured 2026-08-07 at 7bbd82a47 on the
# 64-core host: 26 workers on two CPUs, 4 repeats of 188 items drawn from 19
# files that own known reproducible-flake nodes, 480.4s total. 4 red repeats,
# 4 distinct nodes:
#   4/4  tests/test_contract_manifest.py::test_contract_set_serial_runtime_stays_within_budget
#   3/4  tests/ace/tui/test_agent_metadata_search.py::test_inline_metadata_search_commit_repeat_q_and_passthrough
#   3/4  tests/ace/tui/test_agent_metadata_search.py::test_inline_metadata_search_reverse_key_override
#   1/4  tests/ace/tui/util/test_stall_watchdog.py::test_watchdog_records_one_stall_with_stack_and_context
# The same selection is green unpinned (measured 12.6x faster), which is the
# point: the pinning, not the selection, is what makes the class deterministic.
# The contract-set runtime node named above was retired in favor of a
# deterministic manifest-entry guard; keep the line as historical baseline.
#
# Override the CPU list, worker count, or repeat count with
# SASE_CONTENTION_CPUS, SASE_CONTENTION_WORKERS, and SASE_CONTENTION_REPEAT.
[positional-arguments]
test-contention *args: _setup (_header "test-contention")
    @printf "\n---------- Running default-lane pytest contention harness... ----------\n"
    @command -v taskset >/dev/null || { printf "test-contention requires taskset\\n" >&2; exit 1; }
    @taskset -c "${SASE_CONTENTION_CPUS:-0,1}" env SASE_JUST_INVOCATION_DIR="{{ invocation_directory() }}" {{ venv_bin }}/python tools/run_pytest contention "$@"

# Regenerate the complete ACE PNG golden corpus. The visual-suite fingerprint
# fixture refuses updates outside the pinned renderer environment or canonical
# Linux platform.
update-visual-snapshots: _setup-visual
    @just test-visual -- --sase-update-visual-snapshots

# Run optional real-terminal ACE smoke coverage. This launches the TUI in a
# PTY, so keep it separate from the default and visual snapshot lanes.
[positional-arguments]
test-terminal-smoke *args: _setup-terminal-smoke (_header "test-terminal-smoke")
    @printf "\n---------- Running terminal smoke pytest subset... ----------\n"
    @SASE_JUST_INVOCATION_DIR="{{ invocation_directory() }}" {{ venv_bin }}/python tools/run_pytest terminal-smoke tests/ace/tui/terminal_smoke "$@"

# Parallel test run with coverage reports + 50% gate (used by CI). Excludes
# the visual snapshot suite before collection.
[positional-arguments]
test-cov *args: _setup (_header "test-cov")
    @printf "\n---------- Running pytest with coverage... ----------\n"
    @SASE_JUST_INVOCATION_DIR="{{ invocation_directory() }}" {{ venv_bin }}/python tools/run_pytest cov "$@"

# Record the per-test coverage baseline the diff-scoped selector consumes, and
# cache it host-locally so this host stops depending on the CI artifact alone.
# Line coverage only, no gate, no reports: `coverage_contexts.toml` explains
# why branch coverage is off here (906 MB of artifact against 49 MB, for an
# answer selection never asks). Full CI runs this on scheduled master runs and
# publishes
# `.coverage` as `sase-coverage-contexts-<sha>`; `just refresh-contexts-baseline`
# is how an agent gets that artifact instead. Set
# `SASE_TEST_SELECTION_INSTALL_CONTEXTS=0` to record without caching.
[positional-arguments]
test-contexts *args: _setup (_header "test-contexts")
    @printf "\n---------- Recording per-test coverage contexts... ----------\n"
    @SASE_JUST_INVOCATION_DIR="{{ invocation_directory() }}" {{ venv_bin }}/python tools/run_pytest cov-contexts "$@"
    @{{ venv_bin }}/python tools/install_coverage_contexts --if-enabled

# Run the default test suite and fail if it mutates the production sidecar
# bead store.
[positional-arguments]
test-bead-store-soak *args: _setup (_header "test-bead-store-soak")
    @printf "\n---------- Running bead-store soak check... ----------\n"
    @SASE_JUST_INVOCATION_DIR="{{ invocation_directory() }}" {{ venv_bin }}/python tools/check_bead_store_soak -- {{ venv_bin }}/python tools/run_pytest fast "$@"

# Run tests across all Python versions
test-tox: _setup
    {{ venv_bin }}/tox

# Run tests for a specific Python version (e.g., just test-py 312)
test-py VER: _setup
    {{ venv_bin }}/tox -e py{{ VER }}

# Regenerate the committed contract-set manifest (tests/contract_manifest.txt)
# from the `contract` pytest marker. Run this after adding or removing
# `@pytest.mark.contract` from a test module.
refresh-contract-manifest: _setup
    @printf "\n---------- Regenerating contract test manifest... ----------\n"
    {{ venv_bin }}/python tools/refresh_contract_manifest

# Refresh the committed whole-suite shard timing table
# (tests/shard_timings.json) from this host's local per-test-file duration
# recordings, used to balance the master gate's SASE_TEST_SHARD split. Pass
# --check to verify without writing, or --print-plan N to preview an N-shard
# split.
[positional-arguments]
refresh-shard-timings *args: _setup
    @printf "\n---------- Refreshing shard timing table... ----------\n"
    {{ venv_bin }}/python tools/refresh_shard_timings "$@"

ratchet-core-window *args: _venv
    @{{ venv_bin }}/python tools/ratchet_core_window {{ args }}

# Propose moving sase-core-revision.txt (the pinned Rust core revision CI
# builds from) forward to sase-core's current remote HEAD. Pass --check to
# verify without writing, or --report-only to preview the pin change.
ratchet-core-revision *args: _venv
    @{{ venv_bin }}/python tools/ratchet_core_revision {{ args }}

audit-patch-stitch-terminology: _setup
    @printf "\n---------- Auditing Patch/stitch terminology... ----------\n"
    {{ venv_bin }}/python tools/audit_patch_stitch_terminology --repo-root .

# Download the newest per-test coverage-contexts baseline published by Full CI's
# coverage-contexts job into the host-local cache. Selection itself never
# touches the network: it reads whatever this recipe last cached, and falls back
# to the static import closure when the cache is empty.
[positional-arguments]
refresh-contexts-baseline *args: _setup (_header "refresh-contexts-baseline")
    @{{ venv_bin }}/python tools/fetch_coverage_contexts "$@"

# Summarize diff-scoped selection health from the durable, host-local record
# store: coverage, escalation rate, worker-seconds avoided, the broadening-rule
# histogram, and every false negative (a test that failed in a full run after a
# scoped run over an ancestor commit excluded it). Pass --json for the same
# numbers machine-readably.
[positional-arguments]
selection-health *args: _setup (_header "selection-health")
    @{{ venv_bin }}/python tools/selection_health "$@"

# Measure diff-scoped selection recall against per-test coverage ground truth by
# replaying real history: each of the last N commits is checked out into a
# throwaway detached worktree, its own diff against its parent becomes the
# change set, and the selection that produces is compared against the test files
# coverage recorded as executing those lines. Reports recall twice — closure
# only, and closure plus contexts — because the gap between them is exactly the
# exposure a workspace with no cached baseline runs with.
#
# This is a measurement tool, not a gate: it is deliberately absent from `check`
# and `check-full`, and `--execute` (which really runs the missed tests) is
# opt-in and must stay that way.
[positional-arguments]
selection-backtest *args: _setup (_header "selection-backtest")
    @{{ venv_bin }}/python tools/selection_backtest "$@"

# Agent default: whole-repo lint gates plus a diff-scoped test lane that never
# queues behind another agent's run — it is serial and takes no suite-gate
# lease, except for the middle gear's small non-blocking one (see
# `test-scoped`). Run `just check-full` instead before landing an epic's
# combined tree, when the change touches the broadening set (see
# `tools/select_tests --explain`), or whenever the scoped run escalated or
# reported an unusual selection.
#
# `tools/run_silent` discards the scoped stage's captured output on success,
# so `print_scoped_summary` runs as a separate step right after it returns —
# outside that captured region — and reads the selection manifest `test-scoped`
# just finished writing to show what the run decided either way.
check: _setup
    @tools/run_silent "fmt (python)"       just fmt-py-check
    @tools/run_silent "fmt (markdown)"     just fmt-md-check
    @tools/run_silent "lint (keep-sorted)" just lint-keep-sorted
    @tools/run_silent "lint (ruff)"        just _lint-ruff
    @tools/run_silent "lint (mypy)"        just _lint-mypy
    @tools/run_silent "lint (feature flags)" just _lint-flags
    @tools/run_silent "lint (pyscripts)"   just _lint-pyscripts
    @tools/run_silent "lint (test waits)"  just _lint-test-waits
    @tools/run_silent "lint (changelog)"   just _lint-changelog
    @tools/run_silent "lint (patch/stitch terminology)" just _lint-patch-stitch-terminology
    @tools/run_silent "lint (symvision)"   just _lint-symvision
    @tools/run_silent "lint (toobig)"      just _lint-toobig
    @tools/run_silent "SASE validation"     just validate
    @{{ venv_bin }}/python tools/probe_core_floor --advisory --sase-core-dir "{{ sase_core_dir }}"
    @tools/run_silent "committed plans"      just validate-committed-plans
    @tools/run_silent "test (scoped)"      just test-scoped
    @{{ venv_bin }}/python tools/print_scoped_summary

# Exhaustive verification: every whole-repo lint gate plus the full test
# suite. Run this before landing, and in CI.
check-full: _setup
    @tools/run_silent "fmt (python)"       just fmt-py-check
    @tools/run_silent "fmt (markdown)"     just fmt-md-check
    @tools/run_silent "lint (keep-sorted)" just lint-keep-sorted
    @tools/run_silent "lint (ruff)"        just _lint-ruff
    @tools/run_silent "lint (mypy)"        just _lint-mypy
    @tools/run_silent "lint (feature flags)" just _lint-flags
    @tools/run_silent "lint (pyscripts)"   just _lint-pyscripts
    @tools/run_silent "lint (test waits)"  just _lint-test-waits
    @tools/run_silent "lint (changelog)"   just _lint-changelog
    @tools/run_silent "lint (patch/stitch terminology)" just _lint-patch-stitch-terminology
    @tools/run_silent "lint (symvision)"   just _lint-symvision
    @tools/run_silent "lint (toobig)"      just _lint-toobig
    @tools/run_silent "SASE validation"     just validate
    @{{ venv_bin }}/python tools/probe_core_floor --advisory --sase-core-dir "{{ sase_core_dir }}"
    @tools/run_silent "committed plans"      just validate-committed-plans
    @tools/run_silent "test cost"          just test-cost
    @{{ venv_bin }}/python tools/check_test_cost_budgets --report-advisories
    @tools/run_silent "flake baseline"     just selection-health --fail-on-new-flake

# Render the scripted ACE demo videos (GIF + MP4), stamp
# demos/out/last_generated_date.txt, and offer to commit the results.
# Pass -y/--yes to skip the commit confirmation prompt.
[positional-arguments]
demos *args: _setup-visual _setup-demos
    #!/usr/bin/env bash
    set -euo pipefail

    auto_yes=false
    for arg in "$@"; do
        case "$arg" in
            -y|--yes) auto_yes=true ;;
            *) printf 'error: unknown argument: %s\n' "$arg" >&2; exit 2 ;;
        esac
    done

    vhs demos/tapes/sase_ace_prompt_input.tape
    vhs demos/tapes/sase_ace_agents_observability.tape
    vhs demos/tapes/sase_ace_prompt_history_stash.tape
    vhs demos/tapes/sase_ace_prs_pipeline.tape
    vhs demos/tapes/sase_ace_multi_model_fanout.tape
    just --justfile demos/Justfile postprocess
    just --justfile demos/Justfile check
    date +%Y-%m-%dT%H:%M:%S > demos/out/last_generated_date.txt

    if ! git status --porcelain -- demos/out | grep -q .; then
        printf '[demos] demos/out is unchanged; nothing to commit.\n'
        exit 0
    fi

    git status --short -- demos/out
    if [ "$auto_yes" = true ]; then
        reply=y
    elif [ -t 0 ]; then
        read -r -p "Commit regenerated demos/out artifacts? [y/N] " reply
    else
        reply=n
    fi

    case "$reply" in
        y|Y)
            git add -A -- demos/out
            git commit -m "doc: Regenerate ACE demo artifacts" -- demos/out
            ;;
        *) printf '[demos] Skipping commit; demos/out changes left in the working tree.\n' ;;
    esac

# Run the PyPI release smoke harness in a fresh Docker Compose environment.
pypi_smoke_compose := "docker compose --project-directory smoke/pypi -f smoke/pypi/docker-compose.yml"

pypi-smoke:
    {{ pypi_smoke_compose }} run --build --rm smoke check

pypi-smoke-shell:
    {{ pypi_smoke_compose }} run --build --rm smoke shell

pypi-smoke-clean:
    {{ pypi_smoke_compose }} down -v --rmi all --remove-orphans

# Build the MkDocs Material site with strict warnings-as-errors behavior.
# This target installs only docs tooling, because the docs build does not
# import the Python package and should not need the Rust core checkout.
docs-check: _venv
    uv pip install --python {{ venv_bin }}/python --no-sources "mkdocs-material>=9.7,<10" "mkdocs-rss-plugin>=1.18,<2"
    {{ venv_bin }}/mkdocs build --strict

# Build and validate the downloadable PDF handbook. This target installs only
# docs/PDF tooling, because docs-only CI does not check out or build the Rust
# core package required by editable `sase` installs. Keep versions in sync with
# the `docs-pdf` optional dependency group in pyproject.toml.
docs-pdf-check: _venv
    uv pip install --python {{ venv_bin }}/python --no-sources "mkdocs-material>=9.7,<10" "mkdocs-rss-plugin>=1.18,<2" "mkdocs-exporter>=6.2,<7" "pillow" "pypdf>=5,<7"
    @if [ "${CI:-}" = "true" ]; then \
        {{ venv_bin }}/python -m playwright install --with-deps chromium; \
    else \
        {{ venv_bin }}/python -m playwright install chromium; \
    fi
    @set -e; \
    pdf_site_dir="$(mktemp -d)"; \
    trap 'rm -rf "$pdf_site_dir"' EXIT; \
    SASE_PDF_BUILD_DATE="$(date -u +%Y-%m-%d)" {{ venv_bin }}/mkdocs build --strict -f mkdocs-pdf.yml --site-dir "$pdf_site_dir"; \
    {{ venv_bin }}/python tools/postprocess_docs_pdf --site-dir "$pdf_site_dir"; \
    {{ venv_bin }}/python tools/validate_docs_pdf --site-dir "$pdf_site_dir"; \
    mkdir -p site/downloads; \
    cp "$pdf_site_dir/downloads/sase-handbook.pdf" site/downloads/sase-handbook.pdf

# Verify the generated docs deploy artifact contains the normal site plus PDF.
docs-deploy-artifact-check:
    test -f site/index.html
    test -f site/_headers
    test -f site/downloads/sase-handbook.pdf
    test "$(head -c 4 site/downloads/sase-handbook.pdf)" = "%PDF"
    test -f site/blog/index.html
    test -f site/blog/posts/structured-agentic-software-engineering/index.html
    test "$(find site/blog/posts -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')" = "1"
    grep -Fq 'href="blog/posts/structured-agentic-software-engineering/"' site/index.html
    test ! -d site/blog/posts/hello-sase-your-first-15-minutes
    test ! -d site/blog/posts/why-coding-agents-need-orchestration
    test ! -d site/series/agentic-software-engineering
    @set -e; \
    draft_slugs='xprompts-in-depth axe-background-daemon beads-and-sdd commit-workflows-plugins changespecs-in-practice telegram-mobile-agents prompt-widget-and-nvim whats-next-memory-mobile-web'; \
    for slug in $draft_slugs; do \
        test ! -d "site/blog/posts/$slug"; \
        ! grep -R -F -q "/blog/posts/$slug/" site; \
        ! grep -R -F -q "blog/posts/$slug/" site; \
    done

# Validate SASE initialization and SDD prompt/plan frontmatter links.
validate: _setup
    {{ venv_bin }}/python tools/validate_sase_core_rs_version --pyproject pyproject.toml --published-minimum
    {{ venv_bin }}/python tools/check_feature_flags --static
    {{ venv_bin }}/sase validate

# Validate committed plans with the month-based schema cutover policy.
validate-committed-plans: _setup
    {{ venv_bin }}/python -m sase.scripts.validate_committed_plans

# Report the status of the last fully-completed GitHub Actions workflow set.
[positional-arguments]
workflow-status *args:
    @tools/last_workflow_set_status "$@"

# Fix code, run linters, and run tests.
all: fix lint test

# Find unused Python function/class definitions
symvision *args: (_header "symvision")
    @just _lint-symvision {{ args }}

# Check Python file line counts
toobig *args: (_header "toobig")
    @just _lint-toobig {{ args }}

# Remove build artifacts
clean:
    rm -rf build/ dist/ site/ *.egg-info src/*.egg-info .tox/ .mypy_cache/ .ruff_cache/ .pytest_cache/ htmlcov/ .coverage

# Build wheel and sdist
build: _setup
    {{ venv_bin }}/python -m build

# Build and verify package (CI mode)
build-check: build
    {{ venv_bin }}/twine check dist/*

# Activate venv in subshell
dev-shell:
    @echo "Entering dev shell... (exit to return)"
    @VIRTUAL_ENV="$(pwd)/.venv" PATH="$(pwd)/.venv/bin:$$PATH" $SHELL

# Fast-forward a clean sase-core checkout that is strictly behind origin.
# Used by `_setup` and `rust-install` so a stale auto-cloned workspace
# checkout does not rebuild missing bindings from outdated source.
# No-op when SASE_ALLOW_STALE_CORE=1 (intentional bisects).
_refresh-sase-core-checkout:
    @if [ "${SASE_ALLOW_STALE_CORE:-}" = "1" ]; then \
        exit 0; \
    fi; \
    if [ ! -x "{{ venv_bin }}/python" ]; then \
        exit 0; \
    fi; \
    "{{ venv_bin }}/python" "{{ justfile_directory() }}/tools/refresh_linked_checkout" "{{ sase_core_dir }}" || true

# --- Optional Rust backend (../sase-core) ---
# Rust-only helper targets are no-ops when the configured sase-core
# checkout is absent.

# Build and install the optional `sase_core_rs` PyO3 extension into a venv
# (defaults to the repo `.venv`). Requires `cargo` and installs `maturin`
# into the target venv on demand. Pass an explicit venv path to install
# into any other venv (e.g. `just rust-install /path/to/venv`); see also
# `rust-install-uv-tool` for the uv-tool case.
rust-install VENV=venv_dir_abs: _venv
    @if [ ! -d "{{ sase_core_dir }}" ]; then \
        printf "[rust-install] %s not found; skipping (Rust backend is optional).\n" "{{ sase_core_dir }}"; \
        exit 0; \
    fi
    @if ! command -v cargo > /dev/null 2>&1; then \
        printf "[rust-install] cargo not on PATH; install rustup to build the Rust backend.\n"; \
        exit 1; \
    fi
    @if [ ! -x "{{ VENV }}/bin/python" ]; then \
        printf "[rust-install] target venv %s has no bin/python; aborting.\n" "{{ VENV }}"; \
        exit 1; \
    fi
    @if [ "${SASE_ALLOW_STALE_CORE:-}" != "1" ]; then \
        just --set venv_dir "{{ venv_dir }}" --set sase_core_dir "{{ sase_core_dir }}" _refresh-sase-core-checkout; \
    fi
    @status=0; \
    "{{ VENV }}/bin/python" tools/validate_sase_core_rs_version --sase-core-dir "{{ sase_core_dir }}" --pyproject pyproject.toml || status=$?; \
    if [ "$status" -eq 3 ]; then \
        if [ "${SASE_ALLOW_STALE_CORE:-}" = "1" ]; then \
            printf "[rust-install] WARNING: the sase-core checkout at {{ sase_core_dir }} is behind the sase-core-rs floor in pyproject.toml; proceeding because SASE_ALLOW_STALE_CORE=1.\n"; \
        else \
            printf "[rust-install] ERROR: the sase-core checkout is behind the sase-core-rs floor in\npyproject.toml; the extension built from it will not satisfy sase's tests.\nIn a SASE workspace run 'sase repo open sase-core'; otherwise update the checkout\ndirectly. Then rerun 'just install'.\nSet SASE_ALLOW_STALE_CORE=1 to proceed anyway (intentional bisects only).\n" >&2; \
            exit 1; \
        fi; \
    elif [ "$status" -ne 0 ]; then \
        printf "[rust-install] Note: the sase-core checkout is ahead of the published sase-core-rs window in pyproject.toml; dev builds from {{ sase_core_dir }} ignore it. This is normal — the release-branch reconciler ratchets the published window at release time, so no action is needed here.\n"; \
    fi
    # Harden cargo crate downloads against transient crates.io flakiness.
    # CI has hit `curl ... [16] Error in the HTTP2 framing layer` while
    # maturin's `cargo metadata` fetches deps; disabling HTTP/2 multiplexing
    # and raising the retry count makes the download resilient. Both are
    # overridable from the environment.
    @cached_wheel="$("{{ VENV }}/bin/python" "{{ justfile_directory() }}/tools/sase_core_wheel_cache" lookup --sase-core-dir "{{ sase_core_dir }}" --python "{{ VENV }}/bin/python" || true)"; \
    if [ -n "$cached_wheel" ]; then \
        printf "[rust-install] Installing cached sase_core_rs wheel from %s.\n" "$cached_wheel"; \
        uv pip install --python "{{ VENV }}/bin/python" --reinstall-package sase-core-rs "$cached_wheel"; \
    else \
        "{{ VENV }}/bin/maturin" --version > /dev/null 2>&1 || uv pip install --python "{{ VENV }}/bin/python" maturin; \
        marker="$(mktemp)"; \
        trap 'rm -f "$marker"' EXIT; \
        touch "$marker"; \
        cd "{{ sase_core_dir }}/crates/sase_core_py" && \
            VIRTUAL_ENV="{{ VENV }}" \
            PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
            CARGO_NET_RETRY="${CARGO_NET_RETRY:-10}" \
            CARGO_HTTP_MULTIPLEXING="${CARGO_HTTP_MULTIPLEXING:-false}" \
            "{{ VENV }}/bin/maturin" develop --release && \
        "{{ VENV }}/bin/python" "{{ justfile_directory() }}/tools/purge_sase_core_rs_extensions" --exclude-newer-than "$marker"; \
        build_status=$?; \
        if [ "$build_status" -ne 0 ]; then \
            exit "$build_status"; \
        fi; \
        "{{ VENV }}/bin/python" "{{ justfile_directory() }}/tools/sase_core_wheel_cache" store --sase-core-dir "{{ sase_core_dir }}" --python "{{ VENV }}/bin/python" --maturin "{{ VENV }}/bin/maturin" || true; \
    fi
    # Keep the LSP server in lockstep with the extension: both are built
    # from the same sase-core checkout, and the ACE/LSP parity tests
    # compare their directive contracts.
    @just --set venv_dir "{{ venv_dir }}" --set sase_core_dir "{{ sase_core_dir }}" rust-lsp-install "{{ VENV }}"

# Build and install `sase_core_rs` into the uv-tool venv for `sase`
# (typically ~/.local/share/uv/tools/sase). Use this when you installed
# sase via `uv tool install` and want `sase ...` to work outside this
# repo's `.venv` against a local sase-core checkout.
rust-install-uv-tool:
    @if ! command -v uv > /dev/null 2>&1; then \
        printf "[rust-install-uv-tool] uv not on PATH; install uv to use this target.\n"; \
        exit 0; \
    fi
    @TOOL_VENV="$(uv tool dir)/sase"; \
     if [ ! -x "$TOOL_VENV/bin/python" ]; then \
         printf "[rust-install-uv-tool] no uv-tool venv for sase at %s; run 'uv tool install sase' first.\n" "$TOOL_VENV"; \
         exit 0; \
     fi; \
     just rust-install "$TOOL_VENV"

# Build the local `sase_core_rs` extension and `sase-xprompt-lsp` with the
# dev-update Cargo profile and target-isolated caches, then install both into a venv.
rust-dev-install VENV=venv_dir_abs: _venv
    @if [ ! -d "{{ sase_core_dir }}" ]; then \
        printf "[rust-dev-install] %s not found; skipping (Rust backend is optional).\n" "{{ sase_core_dir }}"; \
        exit 0; \
    fi
    @if ! command -v cargo > /dev/null 2>&1; then \
        printf "[rust-dev-install] cargo not on PATH; install rustup to build the Rust backend.\n"; \
        exit 1; \
    fi
    @if [ ! -x "{{ VENV }}/bin/python" ]; then \
        printf "[rust-dev-install] target venv %s has no bin/python; aborting.\n" "{{ VENV }}"; \
        exit 1; \
    fi
    @if [ "${SASE_ALLOW_STALE_CORE:-}" != "1" ]; then \
        just --set venv_dir "{{ venv_dir }}" --set sase_core_dir "{{ sase_core_dir }}" _refresh-sase-core-checkout; \
    fi
    @status=0; \
    "{{ VENV }}/bin/python" tools/validate_sase_core_rs_version --sase-core-dir "{{ sase_core_dir }}" --pyproject pyproject.toml || status=$?; \
    if [ "$status" -eq 3 ]; then \
        if [ "${SASE_ALLOW_STALE_CORE:-}" = "1" ]; then \
            printf "[rust-dev-install] WARNING: the sase-core checkout at {{ sase_core_dir }} is behind the sase-core-rs floor in pyproject.toml; proceeding because SASE_ALLOW_STALE_CORE=1.\n"; \
        else \
            printf "[rust-dev-install] ERROR: the sase-core checkout is behind the sase-core-rs floor in\npyproject.toml; the extension built from it will not satisfy sase's tests.\nIn a SASE workspace run 'sase repo open sase-core'; otherwise update the checkout\ndirectly. Then rerun 'just install'.\nSet SASE_ALLOW_STALE_CORE=1 to proceed anyway (intentional bisects only).\n" >&2; \
            exit 1; \
        fi; \
    elif [ "$status" -ne 0 ]; then \
        printf "[rust-dev-install] Note: the sase-core checkout is ahead of the published sase-core-rs window in pyproject.toml; dev builds from {{ sase_core_dir }} ignore it. This is normal — the release-branch reconciler ratchets the published window at release time, so no action is needed here.\n"; \
    fi
    @"{{ VENV }}/bin/maturin" --version > /dev/null 2>&1 || uv pip install --python "{{ VENV }}/bin/python" maturin
    # Harden cargo crate downloads against transient crates.io flakiness.
    # CI has hit `curl ... [16] Error in the HTTP2 framing layer` while
    # maturin's `cargo metadata` fetches deps; disabling HTTP/2 multiplexing
    # and raising the retry count makes the download resilient. Both are
    # overridable from the environment.
    @sase_core_abs="$(cd "{{ sase_core_dir }}" && pwd -P)"; \
    py_target_dir="$sase_core_abs/target/uv-tool-py"; \
    profile="${SASE_RUST_DEV_PROFILE:-dev-update}"; \
    marker="$(mktemp)"; \
    trap 'rm -f "$marker"' EXIT; \
    touch "$marker"; \
    cd "$sase_core_abs/crates/sase_core_py" && \
        VIRTUAL_ENV="{{ VENV }}" \
        PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
        CARGO_TARGET_DIR="$py_target_dir" \
        CARGO_NET_RETRY="${CARGO_NET_RETRY:-10}" \
        CARGO_HTTP_MULTIPLEXING="${CARGO_HTTP_MULTIPLEXING:-false}" \
        "{{ VENV }}/bin/maturin" develop --profile "$profile" && \
    "{{ VENV }}/bin/python" "{{ justfile_directory() }}/tools/purge_sase_core_rs_extensions" --exclude-newer-than "$marker"
    @sase_core_abs="$(cd "{{ sase_core_dir }}" && pwd -P)"; \
    lsp_target_dir="$sase_core_abs/target/uv-tool-lsp"; \
    profile="${SASE_RUST_DEV_PROFILE:-dev-update}"; \
    cd "$sase_core_abs" && \
        CARGO_TARGET_DIR="$lsp_target_dir" \
        CARGO_NET_RETRY="${CARGO_NET_RETRY:-10}" \
        CARGO_HTTP_MULTIPLEXING="${CARGO_HTTP_MULTIPLEXING:-false}" \
        cargo build --profile "$profile" -p sase_xprompt_lsp
    @dest="{{ VENV }}/bin/sase-xprompt-lsp"; \
    sase_core_abs="$(cd "{{ sase_core_dir }}" && pwd -P)"; \
    profile="${SASE_RUST_DEV_PROFILE:-dev-update}"; \
    src="$sase_core_abs/target/uv-tool-lsp/$profile/sase-xprompt-lsp"; \
    tmp="$dest.tmp.$$"; \
    trap 'rm -f "$tmp"' EXIT; \
    cp "$src" "$tmp"; \
    chmod +x "$tmp"; \
    mv -f "$tmp" "$dest"; \
    printf "[rust-dev-install] installed %s\n" "$dest"

# Build and install the target-isolated Rust dev artifacts into the uv-tool
# venv for `sase` (typically ~/.local/share/uv/tools/sase).
rust-dev-install-uv-tool:
    @if ! command -v uv > /dev/null 2>&1; then \
        printf "[rust-dev-install-uv-tool] uv not on PATH; install uv to use this target.\n"; \
        exit 0; \
    fi
    @TOOL_VENV="$(uv tool dir)/sase"; \
     if [ ! -x "$TOOL_VENV/bin/python" ]; then \
         printf "[rust-dev-install-uv-tool] no uv-tool venv for sase at %s; run 'uv tool install sase' first.\n" "$TOOL_VENV"; \
         exit 0; \
     fi; \
     just rust-dev-install "$TOOL_VENV"

# Build and install the xprompt LSP server into a venv (defaults to the
# repo `.venv`). The binary is copied into the target venv's bin directory
# so `sase lsp` can prefer the update-managed server over stale PATH copies.
rust-lsp-install VENV=venv_dir_abs: _venv
    @if [ ! -d "{{ sase_core_dir }}" ]; then \
        printf "[rust-lsp-install] %s not found; skipping (xprompt LSP is optional).\n" "{{ sase_core_dir }}"; \
        exit 0; \
    fi
    @if ! command -v cargo > /dev/null 2>&1; then \
        printf "[rust-lsp-install] cargo not on PATH; install rustup to build the xprompt LSP server.\n"; \
        exit 1; \
    fi
    @if [ ! -x "{{ VENV }}/bin/python" ]; then \
        printf "[rust-lsp-install] target venv %s has no bin/python; aborting.\n" "{{ VENV }}"; \
        exit 1; \
    fi
    @cd "{{ sase_core_dir }}" && \
        CARGO_NET_RETRY="${CARGO_NET_RETRY:-10}" \
        CARGO_HTTP_MULTIPLEXING="${CARGO_HTTP_MULTIPLEXING:-false}" \
        cargo build --release -p sase_xprompt_lsp
    @dest="{{ VENV }}/bin/sase-xprompt-lsp"; \
    src="{{ sase_core_dir }}/target/release/sase-xprompt-lsp"; \
    tmp="$dest.tmp.$$"; \
    trap 'rm -f "$tmp"' EXIT; \
    cp "$src" "$tmp"; \
    chmod +x "$tmp"; \
    mv -f "$tmp" "$dest"; \
    printf "[rust-lsp-install] installed %s\n" "$dest"

# Build and install `sase-xprompt-lsp` into the uv-tool venv for `sase`
# (typically ~/.local/share/uv/tools/sase).
rust-lsp-install-uv-tool:
    @if ! command -v uv > /dev/null 2>&1; then \
        printf "[rust-lsp-install-uv-tool] uv not on PATH; install uv to use this target.\n"; \
        exit 0; \
    fi
    @TOOL_VENV="$(uv tool dir)/sase"; \
     if [ ! -x "$TOOL_VENV/bin/python" ]; then \
         printf "[rust-lsp-install-uv-tool] no uv-tool venv for sase at %s; run 'uv tool install sase' first.\n" "$TOOL_VENV"; \
         exit 0; \
     fi; \
     just rust-lsp-install "$TOOL_VENV"

# Run `cargo test --workspace` in ../sase-core.
rust-test: _venv
    @if [ ! -d "{{ sase_core_dir }}" ]; then \
        printf "[rust-test] %s not found; skipping.\n" "{{ sase_core_dir }}"; \
        exit 0; \
    fi
    PY_LIBDIR="$({{ venv_bin_abs }}/python -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR") or "")')"; \
    cd {{ sase_core_dir }} && \
        VIRTUAL_ENV={{ venv_dir_abs }} \
        LD_LIBRARY_PATH="$PY_LIBDIR:${LD_LIBRARY_PATH:-}" \
        PYO3_PYTHON={{ venv_bin_abs }}/python \
        cargo test --workspace

# Auto-format Rust sources in ../sase-core.
rust-fmt:
    @if [ ! -d "{{ sase_core_dir }}" ]; then \
        printf "[rust-fmt] %s not found; skipping.\n" "{{ sase_core_dir }}"; \
        exit 0; \
    fi
    cd {{ sase_core_dir }} && cargo fmt --all

# Verify Rust sources are formatted (CI mode).
rust-fmt-check:
    @if [ ! -d "{{ sase_core_dir }}" ]; then \
        printf "[rust-fmt-check] %s not found; skipping.\n" "{{ sase_core_dir }}"; \
        exit 0; \
    fi
    cd {{ sase_core_dir }} && cargo fmt --all -- --check

# Run clippy with warnings-as-errors in ../sase-core.
rust-clippy: _venv
    @if [ ! -d "{{ sase_core_dir }}" ]; then \
        printf "[rust-clippy] %s not found; skipping.\n" "{{ sase_core_dir }}"; \
        exit 0; \
    fi
    cd {{ sase_core_dir }} && \
        VIRTUAL_ENV={{ venv_dir_abs }} \
        PYO3_PYTHON={{ venv_bin_abs }}/python \
        cargo clippy --workspace --all-targets -- -D warnings

# Run the Rust direct-parser benchmark (no Python in the loop).
rust-bench *args:
    @if [ ! -d "{{ sase_core_dir }}" ]; then \
        printf "[rust-bench] %s not found; skipping.\n" "{{ sase_core_dir }}"; \
        exit 0; \
    fi
    cd {{ sase_core_dir }} && cargo run --release --example bench_parse -- {{ args }}

# Combined Rust check (fmt-check + clippy + tests). No-op when linked repo absent.
rust-check: rust-fmt-check rust-clippy rust-test

# Run the Python parse_project_bytes benchmark against the Rust facade
# (the only path that ships post-Phase-8). Historical Python/dual-run
# rows have been removed.
bench-core *args: _setup
    {{ venv_bin }}/python tests/perf/bench_core_parse.py {{ args }}

# Run the Python query parse/evaluate benchmark. Times parse-only and
# parse+evaluate at 100/1k/10k specs through the optimized facade path
# so Phase 2F has a baseline to compare a future Rust query backend
# against.
bench-query *args: _setup
    {{ venv_bin }}/python tests/perf/bench_core_query.py {{ args }}

# Run the Python agent-artifact scan benchmark. Times the new scan
# facade against the existing direct loaders (find_named_agent,
# list_running_agents, list_all_agents, TUI artifact/workflow
# loaders) so Phase 3 has a baseline to compare a future Rust scan
# backend against.
bench-agent-scan *args: _setup
    {{ venv_bin }}/python tests/perf/bench_agent_scan.py {{ args }}

# Run the Python agent-launch benchmark. Uses fake subprocesses and temp
# ProjectSpec files so launch planning/spawn baselines do not start LLM CLIs.
bench-agent-launch *args: _setup
    {{ venv_bin }}/python tests/perf/bench_agent_launch.py {{ args }}

# Run the fresh-process prompt-search benchmark on disposable synthetic stores.
bench-prompt-search *args: _setup
    {{ venv_bin }}/python tests/perf/bench_prompt_search.py {{ args }}

# Run the Rust-backed agent-launch regression check against the Phase 1 baseline.
launch-perf-check *args: _setup
    @printf "\n---------- Agent launch regression floor (sase-1r.9) ----------\n"
    {{ venv_bin }}/python tests/perf/check_agent_launch_regression.py {{ args }}

# Run the Agents-tab view-hints regression floor against the committed baseline.
view-hints-perf-check *args: _setup
    @printf "\n---------- Agents view-hints regression floor (sase-a5.6) ----------\n"
    {{ venv_bin }}/python tests/perf/check_view_hints_regression.py {{ args }}

# Run the Agents-tab disk-load operation-count regression floor.
agent-disk-load-ops-check *args: _setup
    @printf "\n---------- Agents disk-load operation-count floor (sase-n7.5) ----------\n"
    {{ venv_bin }}/python tests/perf/check_agent_disk_load_ops_regression.py {{ args }}

# Run the Updates > Plugins catalog-scale regression floor (sase-qn.5).
plugin-catalog-scale-check *args: _setup
    @printf "\n---------- Plugins catalog scale regression floor (sase-qn.5) ----------\n"
    {{ venv_bin }}/python tests/perf/check_plugin_catalog_scale_regression.py {{ args }}

# Run a tiny bead benchmark as a CI smoke. This records the Rust-backed
# shell/facade/work-plan path without enforcing workstation-sensitive latency
# thresholds.
bead-perf-smoke *args: _setup
    @printf "\n---------- Bead backend performance smoke (sase-1u) ----------\n"
    mkdir -p sdd/plans/202605/perf_artifacts
    {{ venv_bin }}/python tests/perf/bench_bead.py \
        --runs 1 \
        --issues 50 \
        --dependencies 25 \
        --output sdd/plans/202605/perf_artifacts/bead_perf_smoke.json \
        {{ args }}

# Run the Python status state machine benchmark. Times the pure
# line-based helpers (read_status_from_lines, apply_status_update,
# is_valid_transition, remove_workspace_suffix) and the
# transition_changespec_status orchestrator so Phase 4A can decide
# whether the status state machine is worth porting to Rust.
bench-status-state-machine *args: _setup
    {{ venv_bin }}/python tests/perf/bench_status_state_machine.py {{ args }}

# Plugins catalog scale bench (sase-qn.1 / sase-qn.5). Records p50/p95/max
# at 10/250/1000/2000 entries and enforces filter/j p95 plus the
# fetch/enrich operation-count curves (O(installed) eager fetches,
# sub-quadratic scan work, no silent 1000-result truncation).
bench-plugin-catalog-scale *args: _setup
    @printf "\n---------- Plugins catalog scale (sase-qn.5) ----------\n"
    {{ venv_bin }}/pytest -s -m slow \
        tests/perf/bench_plugin_catalog_scale.py \
        tests/ace/tui/bench_plugins_catalog_scale.py \
        {{ args }}

# Run the Git query-op parsers benchmark. Times parse_git_name_status_z
# on synthetic NUL streams (small/medium/large), the smaller normalizers
# (branch name, workspace name, conflicted files, local changes), and
# real `git diff --name-status -z` invocations so Phase 5A can compare
# parse cost to subprocess fork+exec cost.
bench-git-query-ops *args: _setup
    {{ venv_bin }}/python tests/perf/bench_git_query_ops.py {{ args }}

# Phase 7E regression floor (sase-1e.5). Runs the stable subset of
# Phase 7B core-operation benchmarks against the recorded ceiling and
# fails on regression. The JSON report lands at
# `sdd/plans/202604/perf_artifacts/rust_backend_phase7_floor_check.json`
# so CI can upload it on failure.
phase7-perf-check *args: _setup
    @printf "\n---------- Phase 7E regression floor (sase-1e.5) ----------\n"
    {{ venv_bin }}/python tests/perf/phase7_check_regression.py {{ args }}
