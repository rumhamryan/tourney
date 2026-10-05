# Tourney

## Run the main menu

From the repository directory, run:

```sh
uv run python src/main_menu.py
```

The menu offers Single Elimination, Double Elimination, Load Tournament, and Exit. Choosing
a format opens tournament setup. Set Number of tables using the arrows or
type a positive whole number; it defaults to one. Type a name and press Enter or click Add.
Select a player and click Remove Selected, or press Delete while the player
list has focus. Blank names are rejected, and the limit is 32 players.
Repeated names are allowed.

Start becomes available after adding at least two players and leaving no name
waiting to be added. Clicking it shuffles the players and opens a scrollable
bracket preview. Double elimination shows winners' and losers' sides, a grand
final, and a reset played only if the losers' finalist wins the first final.
Later match slots show their source match numbers. Byes advance automatically
in the preview. Long names can be read in full by hovering over them.

Back to Setup preserves the original player list and table count. Starting
again creates a new randomized preview. Result entry and table assignments
will be added separately.

Back to Menu preserves the table count, player list, and any unfinished name, including
when choosing a different format.
Use Tab or Shift+Tab to move between controls and Enter or Space to activate
the focused button. The window can be resized.

## Window sizing

The app opens maximized. Its typography, fields, buttons, player rows, and
bracket cards are sized for a 1920×1080 window. The menu and setup form stay
centered, with comfortable widths on a large screen. Smaller windows use a
compact scale; the minimum window is 640×600. Switching pages preserves the
chosen window size. Large brackets scroll while keeping match text readable.

## Save and load a tournament

Click **Save As…** on the bracket screen to write a readable UTF-8 `.json` file.
Use **Load Tournament** on the main menu to restore it. Loading preserves the
exact draw; it never reshuffles the players. Ctrl+Shift+S opens Save As on the
bracket screen, and Ctrl+O opens Load from the main menu. macOS uses the platform's
standard shortcuts.

The versioned snapshot includes the original setup order, randomized player
order, format, full winners'/losers' match graph, conditional reset, table count,
custom table labels, match statuses, winners, active table assignments, and the
draw-lock flag. Players are referenced by zero-based draw indices rather than
names, so repeated names remain distinct. Tables are numbered from one; omitted
label overrides default to `Table N`, and omitted match progress is pending.
Automatic byes, readiness, reset eligibility, and the champion are derived from
the saved graph and results.

Loaded progress appears in the bracket, including winners and occupied tables.
A started tournament returns to the main menu instead of editable setup to keep
its draw locked. Scoring and table-assignment controls will be added separately;
their state is already supported by this file format. This step provides manual
saves; automatic recovery saves are a later step.

Invalid or unsupported files are rejected before changing the current tournament.
Saving flushes a temporary file beside the destination and replaces the old file
atomically; a failed write leaves the previous save intact. The JSON schema is
currently version 1; future bracket-rule changes will require an explicit migration.

Run the UI checks without opening a desktop window:

```sh
uv run pytest tests/integration/test_main_menu.py
```

## Repository tooling

This is a template repository setup with modern Python tooling:

- **Package Manager**: [uv](https://github.com/astral-sh/uv)
- **Linting & Formatting**: [Ruff](https://github.com/astral-sh/ruff)
- **Type Checking**: [mypy](https://mypy-lang.org/)
- **Testing**: [pytest](https://docs.pytest.org/)
- **Quality Checks Local**: [pre-commit](https://pre-commit.com/)
- **Quality Checks Remote**: [Github Action](https://docs.github.com/en/actions)

## Getting Started

### 1. Prerequisite: Install uv
The project uses `uv` for fast dependency management. It is a required dependency.
```sh
# On macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# On Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Initialize Your Project
Run the automated setup script. This will:
- Rename the project in `pyproject.toml`.
- Create your package directory structure.
- Remove template placeholder files.
- **Automatically install pre-commit git hooks.**

```sh
# Clone the repo, then run:
uv run scripts/setup_project.py --name my_project_name --type cli

# Available types: library, cli, service
```

## Development Workflow

### Mandatory Quality Checks
This project enforces quality standards via `pre-commit`.
The hooks call the same `uv run ...` commands used in CI, so there is a
single version source for Ruff, mypy, and pytest.
CI runs the full quality suite on Linux and also runs pytest on Windows
and macOS for cross-platform coverage.
Pre-commit also validates TOML, merge conflict markers, private keys,
line endings, case-conflicting paths, and GitHub Actions workflows.
Commits also enforce a monotonic patch version bump in `pyproject.toml`;
if the version has not increased since `HEAD`, the hook updates it and
stops the commit so you can stage the file and retry.

To run all checks manually (recommended before pushing):
```sh
uv sync --all-extras --dev
uv run pre-commit run --all-files
```

Refresh `uv.lock` on a regular interval to keep the shared toolchain up to
date for local development, pre-commit, and CI:
```sh
uv lock --upgrade
uv sync --all-extras --dev
uv run pre-commit run --all-files
```

### Individual Tools
- **Test**: `uv run pytest`
- **Lint**: `uv run ruff check .`
- **Format**: `uv run ruff format .`
- **Type Check**: `uv run mypy .`
