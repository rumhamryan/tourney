# Tourney

## Portable Windows application

On Windows 11 x64, download `Tourney.exe` and double-click it to open the app.
No installation, Python, uv, or internet connection is needed to run it. Move
the executable wherever convenient; tournament saves remain separate `.json`
files in the location you choose when saving.

This build is unsigned, so Windows may show a download or launch warning.
It does not create shortcuts or install anything. On each launch, the executable
extracts its bundled libraries into a temporary directory, which can add startup
time. Normal exit removes those temporary files.

### Build or rebuild the executable

Use a Windows x64 build machine with [uv](https://docs.astral.sh/uv/getting-started/installation/)
available in PowerShell. From the repository directory, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

The script installs Python 3.12 if needed and synchronizes the application and
PyInstaller build dependencies into `.venv` using the committed `uv.lock`.
Network access is required to download dependencies that are not already cached.
Dependencies and build outputs are excluded from Git; do not commit `.venv`.
The build script also works from another directory when given its full path.

The result is `dist/Tourney.exe`, containing Python, the required Qt plugins,
and the OR-Tools solver libraries. Share that file alone. Intermediate files
are written under `build/`. Run the same command again after changing the app;
it replaces the previous executable. Testers replace their old executable with
the new one and keep their tournament saves.

Before distributing a build, check it on a Windows 11 x64 machine without Python
or developer tools: open it from a folder outside the repo (including a path
with spaces), start each tournament format, record results, and save and reload
a tournament. Double elimination should successfully run its background solver.

### Tagged builds in GitHub Actions

Pushing any Git tag triggers CI for the tagged commit. After the quality checks
and Windows/macOS tests pass, CI runs the same build script on a Windows runner
and uploads `dist/Tourney.exe` as the `Tourney-windows-x64` artifact. Open the
tag's run in the repository's **Actions** tab and download that artifact; extract
the ZIP to get `Tourney.exe`. Ordinary branch pushes and pull requests run checks
without producing an executable.

For example, after committing the desired version:

```sh
git tag v0.1.11
git push origin v0.1.11
```

The tagged commit must contain the packaging files and updated workflow.
Artifacts are retained according to the repository's Actions retention settings.
CI produces the unsigned portable application and does not create a GitHub Release.

## Run the main menu

From the repository directory, run:

```sh
uv run python src/main_menu.py
```

The menu offers Single Elimination, Double Elimination, Chip Tournament, Load Tournament,
and Exit. Choosing
a format opens tournament setup. Set Number of tables using the arrows or
type a positive whole number; it defaults to one. Type a name and press Enter or click Add.
Select a player and click Remove Selected, or press Delete while the player
list has focus. Blank names are rejected, and the limit is 32 players.
Repeated names are allowed.

Chip Tournament adds a **Chip count** field directly below the player-name field.
Enter a name and a positive whole-number count, then click **Add Player**.
Both fields clear after adding; no chip count is supplied automatically.
Enter in the name field moves to the chip field; Enter there adds the player.
The roster displays names and chip counts in aligned columns, and returning
through the menu preserves them. Players entered in bracket modes have no chip
count and are marked **Chips not set** when viewed in chip mode.
Select a registered player to edit their name or chip count, then click
**Update Player**. Start requires at least two players, a chip count for every
player, and no unfinished entry.

For elimination formats, Start becomes available after adding at least two players and leaving no name
waiting to be added. Clicking it shuffles the players, locks the draw, assigns
ready matches to tables, and opens a scrollable bracket. Double elimination
shows winners' and losers' sides, a grand
final, and a reset played only if the losers' finalist wins the first final.
Later match slots show their source match numbers. Byes advance automatically
in the bracket. Long names can be read in full by hovering over them.

Click an active match to open its winner dialog.
The dialog says **Select the winner.** and contains two
player buttons. Clicking a player records the winner immediately. The window
title identifies the match and table; repeated names are distinguished as top
and bottom players. Escape or the window's close button dismisses the dialog
without recording a result. Recording a result advances players and immediately
assigns ready matches to free tables. The champion appears when the final is
complete. Results cannot currently be undone or corrected.

Back to Menu preserves the table count, player list, and any unfinished name, including
when choosing a different format.
Save the current tournament before starting another one; Start creates a new draw.
Use Tab or Shift+Tab to move between controls and Enter or Space to activate
the focused button. The window can be resized.

## Chip tournament rounds

Starting a chip tournament opens the current chip leaderboard on the left and
an evenly spaced matchup grid on the right. Players are paired randomly each
round. Active matchups show their table number in green; waiting matchups fill
tables as they become free.

Click an active matchup and select the winner. The loser loses one chip, the
winner keeps their chips, and the completed matchup disappears. The leaderboard
updates immediately, with eliminated players shown at the bottom. Once every
matchup in the round finishes, players with chips are randomly paired again.
An odd roster gives one player a bye without losing a chip; byes favor players
who have received the fewest. Rounds continue until only one player has chips.

## Automatic table scheduling

Single elimination uses Hu's highest-level-first algorithm. Double elimination
uses OR-Tools CP-SAT to minimize the modeled remaining duration, with a one-second
solve limit in a background thread. If the solver does not prove optimality, the
app fills tables using critical-path priority. Both formats preserve matches
already running and use the lowest available table numbers.

Scheduling assumes identical tables and equal match durations, with no rest
periods or match clocks. Running matches are modeled with one unit remaining.
The double-elimination model includes a possible final reset until results rule
it out; that match is assigned only when required. Any optimality guarantee
applies to these assumptions, rather than actual elapsed tournament time.

## Window sizing

The app opens maximized. Its typography, fields, buttons, player rows, and
bracket cards are sized for a 1920×1080 window. The menu and setup form stay
centered, with comfortable widths on a large screen. Smaller windows use a
compact scale; the minimum window is 640×600. Switching pages preserves the
chosen window size. Large brackets scroll while keeping match text readable.

## Save and load a tournament

Click **Save As…** on the tournament screen to write a readable UTF-8 `.json` file.
Use **Load Tournament** on the main menu to restore it. Loading preserves the
exact draw; it never reshuffles the players. Ctrl+Shift+S opens Save As on the
tournament screen, and Ctrl+O opens Load from the main menu. macOS uses the platform's
standard shortcuts.
Loading also locks the draw, preserves existing assignments and results, and
assigns ready matches to any free tables.

Chip saves preserve starting and current chip counts, every round and result,
byes, and active table assignments. Loading resumes the current round without
changing its pairings.

The elimination snapshot includes the original setup order, randomized player
order, format, full winners'/losers' match graph, conditional reset, table count,
custom table labels, match statuses, winners, active table assignments, and the
draw-lock flag. Players are referenced by zero-based draw indices rather than
names, so repeated names remain distinct. Tables are numbered from one; omitted
label overrides default to `Table N`, and omitted match progress is pending.
Automatic byes, readiness, reset eligibility, and the champion are derived from
the saved graph and results.

Loaded progress appears in the bracket, including winners and occupied tables.
Matches in progress show their table number in bold green beside the match number.
Hover over the table number to read its custom name, if configured. Match notes
wrap onto two lines; longer notes keep their full text in a tooltip.
A started tournament returns to the main menu instead of editable setup to keep
its draw locked. Saves are manual; automatic recovery saves are a later step.

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
