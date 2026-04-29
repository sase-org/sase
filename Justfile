# sase task runner

venv_dir := ".venv"
venv_bin := venv_dir / "bin"
venv_dir_abs := justfile_directory() / venv_dir
venv_bin_abs := justfile_directory() / venv_bin

# Sibling Rust core repo. Phase 1 Rust backend is opt-in; targets that
# operate on it print a friendly message and exit 0 when the repo is
# missing so pure-Python contributors are never blocked.
sase_core_dir := "../sase-core"

default:
    @just --list

# Bootstrap .venv if it doesn't exist
_setup:
    @[ -x {{ venv_bin }}/python ] || uv venv {{ venv_dir }}
    @{{ venv_bin }}/mypy --version > /dev/null 2>&1 || uv pip install --reinstall-package mypy -e ".[dev]"

# Print a box header for a top-level command (private helper)
_header NAME:
    @printf "\n"
    @printf "┌───────────────────────────────────────────────────────┐\n"
    @printf "│                RUNNING: just %-25s│\n" "{{ NAME }}"
    @printf "└───────────────────────────────────────────────────────┘\n"

# Install in editable mode with dev dependencies. If a sibling
# `../sase-core` checkout is present and a Rust toolchain is on PATH,
# build and install `sase_core_rs` from source first so the pyproject
# dependency on `sase-core-rs` is satisfied without round-tripping
# through PyPI. Released `sase` wheels resolve the same dependency
# from the published `sase-core-rs` distribution instead.
install: _setup
    @if [ -d "{{ sase_core_dir }}" ] && command -v cargo > /dev/null 2>&1; then \
        printf "[install] Building sase_core_rs from {{ sase_core_dir }} for local dev.\n"; \
        just rust-install; \
    fi
    uv pip install -e ".[dev]"

# Run linters (ruff + mypy + pyscripts + pyvision + keep-sorted)
lint: _setup (_header "lint") lint-keep-sorted
    @printf "\n---------- Running ruff linter on Python files... ----------\n"
    @just _lint-ruff
    @printf "\n---------- Running mypy type checker... ----------\n"
    @just _lint-mypy
    @printf "\n---------- Validating scripts/tools directory structure... ----------\n"
    @just _lint-pyscripts
    @printf "\n---------- Checking for unused Python definitions... ----------\n"
    @just _lint-pyvision

# Run ruff linter on Python files (private, extracted for per-stage wrapping)
_lint-ruff: _setup
    {{ venv_bin }}/ruff check src/ tests/

# Run mypy type checker (private, extracted for per-stage wrapping)
_lint-mypy: _setup
    {{ venv_bin }}/mypy

# Validate scripts/tools directory structure (private, extracted for per-stage wrapping)
_lint-pyscripts: _setup
    {{ venv_bin }}/python tools/pyscripts-260314

# Check for unused Python definitions (private, extracted for per-stage wrapping)
_lint-pyvision: _setup
    BD_COMMAND=tools/sase_bead {{ venv_bin }}/python tools/pyvision-260225 src/sase

# Auto-fix all code (format + keep-sorted)
fix: (_header "fix") fmt-py fmt-md fix-keep-sorted

# Auto-format all code
fmt: (_header "fmt") fmt-py fmt-md

# Auto-format Python code
fmt-py: _setup
    @printf "\n---------- Formatting Python with ruff... ----------\n"
    {{ venv_bin }}/ruff format src/ tests/
    @printf "\n---------- Fixing Python with ruff... ----------\n"
    {{ venv_bin }}/ruff check --fix src/ tests/

# Auto-format Markdown files
fmt-md:
    @printf "\n---------- Formatting Markdown with prettier... ----------\n"
    prettier --write --prose-wrap=always --print-width=120 "**/*.md"

# Auto-fix keep-sorted blocks in YAML files
fix-keep-sorted:
    @printf "\n---------- Fixing keep-sorted blocks in YAML files... ----------\n"
    git ls-files '*.yml' '*.yaml' | xargs keep-sorted

# Lint keep-sorted blocks in YAML files (CI mode)
lint-keep-sorted:
    @printf "\n---------- Checking keep-sorted blocks in YAML files... ----------\n"
    git ls-files '*.yml' '*.yaml' | xargs keep-sorted --mode lint

# Check all formatting (CI mode)
fmt-check: (_header "fmt-check") fmt-py-check fmt-md-check

# Check Python formatting (CI mode)
fmt-py-check: _setup
    @printf "\n---------- Checking Python formatting with ruff... ----------\n"
    {{ venv_bin }}/ruff format --check src/ tests/

# Check Markdown formatting (CI mode)
fmt-md-check:
    @printf "\n---------- Checking Markdown formatting with prettier... ----------\n"
    prettier --check --prose-wrap=always --print-width=120 "**/*.md"

# Fast parallel test run, no coverage (use test-cov to enforce coverage gate)
test *args: _setup (_header "test")
    @printf "\n---------- Running pytest (parallel, no coverage)... ----------\n"
    {{ venv_bin }}/pytest -n auto --dist=loadfile {{ args }}

# Run slow tests (excluded from the default `just test` run)
test-slow *args: _setup (_header "test-slow")
    @printf "\n---------- Running slow pytest subset... ----------\n"
    {{ venv_bin }}/pytest -n auto --dist=loadfile -m slow {{ args }}

# Parallel test run with coverage reports + 50% gate (used by CI)
test-cov *args: _setup (_header "test-cov")
    @printf "\n---------- Running pytest with coverage... ----------\n"
    {{ venv_bin }}/pytest -n auto --dist=loadfile \
        --cov=src/sase \
        --cov-branch \
        --cov-report=term-missing:skip-covered \
        --cov-report=html \
        --cov-report=xml \
        --cov-fail-under=50 \
        {{ args }}

# Run tests across all Python versions
test-tox: _setup
    {{ venv_bin }}/tox

# Run tests for a specific Python version (e.g., just test-py 312)
test-py VER: _setup
    {{ venv_bin }}/tox -e py{{ VER }}

# Run all checks (format check + lint + test) with context-efficient output for agents
check: _setup
    @tools/run_silent "fmt (python)"       just fmt-py-check
    @tools/run_silent "fmt (markdown)"     just fmt-md-check
    @tools/run_silent "lint (keep-sorted)" just lint-keep-sorted
    @tools/run_silent "lint (ruff)"        just _lint-ruff
    @tools/run_silent "lint (mypy)"        just _lint-mypy
    @tools/run_silent "lint (pyscripts)"   just _lint-pyscripts
    @tools/run_silent "lint (pyvision)"    just _lint-pyvision
    @tools/run_silent "test"               just test

# Fix code, run linters, and run tests.
all: fix lint pylimit test

# Find unused Python function/class definitions
pyvision *args: _setup (_header "pyvision")
    BD_COMMAND=tools/sase_bead {{ venv_bin }}/python tools/pyvision-260225 src/sase \
        {{ args }}

# Check Python file line counts
pylimit *args: (_header "pylimit")
    tools/pylimit-260221 src {{ if args == "" { "1000 850 700" } else { args } }}
    tools/pylimit-260221 tests {{ if args == "" { "1000 850 700" } else { args } }}

# Remove build artifacts
clean:
    rm -rf build/ dist/ *.egg-info src/*.egg-info .tox/ .mypy_cache/ .ruff_cache/ .pytest_cache/ htmlcov/ .coverage

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

# --- Optional Rust backend (../sase-core) ---
# These targets are no-ops when ../sase-core is absent so pure-Python
# installs (`just install`) keep working without a Rust toolchain.

# Build and install the optional `sase_core_rs` PyO3 extension into a venv
# (defaults to the repo `.venv`). Requires `cargo` and installs `maturin`
# into the target venv on demand. Pass an explicit venv path to install
# into any other venv (e.g. `just rust-install /path/to/venv`); see also
# `rust-install-uv-tool` for the uv-tool case.
rust-install VENV=venv_dir_abs: _setup
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
    @{{ VENV }}/bin/maturin --version > /dev/null 2>&1 || uv pip install --python "{{ VENV }}/bin/python" maturin
    cd {{ sase_core_dir }}/crates/sase_core_py && \
        VIRTUAL_ENV={{ VENV }} \
        PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
        {{ VENV }}/bin/maturin develop --release

# Build and install `sase_core_rs` into the uv-tool venv for `sase`
# (typically ~/.local/share/uv/tools/sase). Use this when you installed
# sase via `uv tool install` and want `SASE_CORE_BACKEND=rust sase ...`
# to work outside this repo's `.venv`.
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

# Run `cargo test --workspace` in ../sase-core.
rust-test:
    @if [ ! -d "{{ sase_core_dir }}" ]; then \
        printf "[rust-test] %s not found; skipping.\n" "{{ sase_core_dir }}"; \
        exit 0; \
    fi
    cd {{ sase_core_dir }} && cargo test --workspace

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
rust-clippy:
    @if [ ! -d "{{ sase_core_dir }}" ]; then \
        printf "[rust-clippy] %s not found; skipping.\n" "{{ sase_core_dir }}"; \
        exit 0; \
    fi
    cd {{ sase_core_dir }} && cargo clippy --workspace --all-targets -- -D warnings

# Run the Rust direct-parser benchmark (no Python in the loop).
rust-bench *args:
    @if [ ! -d "{{ sase_core_dir }}" ]; then \
        printf "[rust-bench] %s not found; skipping.\n" "{{ sase_core_dir }}"; \
        exit 0; \
    fi
    cd {{ sase_core_dir }} && cargo run --release --example bench_parse -- {{ args }}

# Combined Rust check (fmt-check + clippy + tests). No-op when sibling repo absent.
rust-check: rust-fmt-check rust-clippy rust-test

# Run the Python parse_project_bytes benchmark across all available
# backends. Reports Python-direct, Python-facade, Rust direct (if
# `sase_core_rs` is importable), Rust-facade, and dual-run overhead.
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

# Run the Python status state machine benchmark. Times the pure
# line-based helpers (read_status_from_lines, apply_status_update,
# is_valid_transition, remove_workspace_suffix) and the
# transition_changespec_status orchestrator so Phase 4A can decide
# whether the status state machine is worth porting to Rust.
bench-status-state-machine *args: _setup
    {{ venv_bin }}/python tests/perf/bench_status_state_machine.py {{ args }}

# Phase 6G dual-run parity gate. Runs every shipped Rust core operation
# under SASE_CORE_DUAL_RUN=1 and fails if any comparison record reports
# match=false (excluding the documented parse_project_bytes end_line gap).
parity-check *args: _setup
    {{ venv_bin }}/python tests/parity/dual_run_parity.py {{ args }}

# Run the Git query-op parsers benchmark. Times parse_git_name_status_z
# on synthetic NUL streams (small/medium/large), the smaller normalizers
# (branch name, workspace name, conflicted files, local changes), and
# real `git diff --name-status -z` invocations so Phase 5A can compare
# parse cost to subprocess fork+exec cost.
bench-git-query-ops *args: _setup
    {{ venv_bin }}/python tests/perf/bench_git_query_ops.py {{ args }}

# Phase 7 measurement smoke wrapper. Phase 7A only exercises the helper
# package (metadata envelope + ratio/speedup helpers) so later agents
# can produce comparable artifacts. Phase 7E will replace this with the
# real regression-floor invocation once the stable subset is chosen.
phase7-perf-check: _setup
    @printf "\n---------- Phase 7 helper smoke (sase-1e.1) ----------\n"
    {{ venv_bin }}/pytest -q tests/perf/phase7
