# Contributing to sase

## Setup

```bash
uv venv .venv
source .venv/bin/activate
just install
```

## Development Workflow

```bash
just fmt           # Auto-format code
just lint          # Run ruff + mypy
just test          # Run tests with coverage
just check         # All checks (fmt-check + lint + test)
```

## Adding Dependencies

Add runtime dependencies to `[project.dependencies]` in `pyproject.toml`. Add dev-only dependencies to
`[project.optional-dependencies.dev]`. Then re-run `just install`.

## Running Specific Tests

```bash
pytest tests/path/to/test_file.py             # Single file
pytest tests/path/to/test_file.py::test_name  # Single test
pytest -k "pattern"                            # By name pattern
```

## Multi-Version Testing

```bash
just test-tox       # All versions (3.12, 3.13, 3.14)
just test-py 312    # Specific version
```

## Ignoring Lint Violations

- **Ruff**: Add `# noqa: RULE` to the line (e.g., `# noqa: E501`)
- **Mypy**: Add `# type: ignore[code]` to the line
- **Coverage**: Add `# pragma: no cover` to exclude from coverage

## Submitting Issues

This project uses `bd` (beads) for issue tracking:

```bash
bd create --title="Description" --type=bug --priority=2
bd ready    # See available work
```
