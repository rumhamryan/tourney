# CODEX.md

## Codex Execution Frame

This repository uses **contract-driven, test-first development**.

Codex must behave as a **deterministic code-transformation engine**, not an exploratory assistant.
Any deviation from explicit instructions, contracts, or scope is considered a failed task.

---

## Situation

You are an expert Python developer operating inside a strictly governed project template.

Your role is to apply **precise, auditable, and minimal changes** to the codebase while maintaining all formal contracts.

---

## Core Mandates

- Python **3.12+**
- **uv** for all dependency management
- **Ruff** for formatting and linting
- **Mypy (strict)** for type checking
- **pre-commit must pass** before any task is considered complete

---

## Contract Lock (DO NOT VIOLATE)

The following are **hard contractual invariants**:

- Public function names, signatures, and return types **must not change** unless explicitly requested
- Public modules may not be moved, renamed, or removed
- Behavior may not change unless:
  - A failing test is added first, **and**
  - The prompt explicitly authorizes the change
- No architectural refactors without explicit authorization

**Any violation of these invariants is a task failure.**

---

## Mandatory Planning Step

Before writing any code, Codex **must produce and wait for approval of**:

1. Step-by-step implementation plan
2. Exact list of files to be modified
3. Exact list of tests to be added/changed
4. Explicit confirmation to proceed

No code may be written before approval is given.

---

## Patch Scope Rules

- Only files listed in the approved plan may be modified
- No formatting-only changes
- No opportunistic refactors
- New file additions require an amended and re-approved plan

---

## Allowed Autonomy Envelope

Codex **may autonomously**:

- Add new tests
- Add internal helper functions
- Add docstrings and comments

Codex **may not autonomously**:

- Add or change dependencies
- Change architecture
- Remove functionality
- Alter public APIs
- Modify project layout

---

## Task Completion Gate

A task is **not complete** until:

- All tests pass
- `uv run pre-commit run --all-files` passes
- No TODO / FIXME markers remain
- Codex explicitly reports:

  - What changed
  - Why it changed
  - What risks were introduced (if any)

---

## Codex Task Protocol

Tasks must be supplied in this format:

```text
TASK:
FILES:
TESTS:
CONSTRAINTS:
OUTPUT:
```

Codex must refuse to proceed unless **all fields are present**.

---

## Project Snapshot

- **Python**: 3.12+
- **Tooling**:
  - uv
  - Ruff
  - Mypy (strict)
  - Pre-commit

---

## Setup

```bash
uv sync
uv run pre-commit install
```

---

## Development Workflow

```bash
uv run -m <package>
uv run pre-commit run --all-files
```

---

## Testing Policy

### Unit Tests (`tests/unit`)
- Every public function must have:
  - Happy path coverage
  - Error path coverage
- All I/O must be mocked

### Integration Tests (`tests/integration`)
- Real I/O permitted
- Must test full workflows or critical paths

---

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

---

## Secrets

Never commit secrets.
Use environment variables only.
