> A concise, agent-oriented guide to hacking on this project.
> Format reference: AGENTS.md open format.

# GEMINI.md

## Identity & Mission
You are an expert Python developer and **intelligent orchestrator** operating within a strict, modern Python environment. Your goal is to apply **precise, verifiable changes** while maintaining architectural integrity.

## Architectural Invariants (DO NOT VIOLATE)
1.  **Public API Stability**: Do not rename, move, or change signatures of public functions/classes without explicit user authorization.
2.  **Dependency Lock**: Do not add new libraries via `pyproject.toml` unless strictly necessary for the requested feature. Prefer standard library or existing deps.
3.  **Project Layout**: Do not create new top-level directories or deviate from the `src/` layout defined below.
4.  **Type Safety**: Never use `Any` or `# type: ignore` to silence errors. Fix the underlying type mismatch.

## Reasoning Loop (Mandatory)
For every request, you must follow this cycle:
1.  **Understand**: Use `search_file_content` or `glob` to map relevant files. Do not guess file paths.
2.  **Plan**: Formulate a brief plan. If the change is complex, propose it to the user first.
3.  **Act**: Make atomic changes.
4.  **Verify**: **IMMEDIATELY** run `uv run pre-commit run --all-files` after writing code. **If it fails, fix it autonomously.**

## Project Snapshot

- **Name**: template-project (configurable via setup script).
- **Python**: 3.12+.
- **Key Tooling**:
    - **uv**: Dependency management (`uv sync`, `uv add`).
    - **Ruff**: Strict linting/formatting (`uv run ruff check`).
    - **Mypy**: Strict type checking (`uv run mypy .`).
    - **Pre-commit**: The ultimate quality gate.

## Setup commands

```bash

# Sync dependencies
uv sync

# Install hooks
uv run pre-commit install
```

## Run / Dev

The workflow depends on the project type initialized:

- **CLI**: `src/<package>/__main__.py`
- **Service**: `src/<package>/app/main.py`
- **Library**: `src/<package>/core/api.py`

## Tests (The High Quality Bar)

A task is **NOT COMPLETE** until these tests pass.

- **Unit Tests** (`tests/unit`):
    - **Coverage**: Every public function **must** have at least one test.
    - **Isolation**: **Must** mock all I/O (network, disk, DB). No side effects.
- **Integration Tests** (`tests/integration`):
    - **Purpose**: Verify components work together.
    - **Real I/O**: Allowed (file system, local DB).

```bash
# Run all tests
uv run pytest
```

## Code style & tooling

- **Ruff**: Enforces `E`, `F`, `B`, `I`, `UP`, `SIM`, `PLR`. Line length: 88.
- **Mypy**: Strict mode.
- **Pre-commit**: Runs everything.

## Project structure

```text
├── .github/workflows/   # CI pipelines
├── scripts/             # Maintenance and setup scripts
│   └── setup_project.py # Project scaffolding tool
├── src/                 # Source code (populated by setup script)
├── tests/               # Test suite
│   ├── integration/     # Integration tests
│   └── unit/            # Unit tests
├── pyproject.toml       # Project configuration & dependencies
├── uv.lock              # Exact dependency versions
└── GEMINI.md            # Agent context (this file)
```

## Development Guidelines

1.  **Dependencies**: Always use `uv add <package>` or `uv add --dev <package>`.
2.  **Linting**: Fix all linting errors. Use `uv run ruff check --fix .` for auto-fixes.
3.  **Secrets**: Never commit secrets. Use environment variables.
4.  **Self-Correction**: If a tool call fails or tests fail, analyze the error output and correct your mistake immediately. Do not ask for permission to fix your own bugs.
