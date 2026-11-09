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
and publishes a GitHub Release for the pushed tag with `Tourney.exe` attached.
Download the executable directly from that release. CI also uploads
`dist/Tourney.exe` as the `Tourney-windows-x64` artifact in the tag's **Actions**
run; extract that artifact's ZIP to get the same executable. Ordinary branch
pushes and pull requests run checks without producing an executable or release.

For example, after committing the desired version:

```sh
git tag -a v0.1.24 -m "Tourney v0.1.24"
git push origin v0.1.24
```

The tagged commit must contain the packaging files and updated workflow.
Artifacts are retained according to the repository's Actions retention settings.
The tag must be pushed to GitHub; creating it locally does not trigger CI.
The Windows build job uses `GITHUB_TOKEN` with `contents: write` to publish the
release and generated notes; no additional secret is required. Rerunning a tag
build replaces `Tourney.exe` on an existing release for that tag. The executable
is unsigned.

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
New names and renames must be unique within the roster. Surrounding whitespace
is trimmed before comparing names; comparison is case-sensitive. Duplicate
entries show an error and keep the entered values for correction.

Click **Import Players…** on any tournament setup page to replace the roster
from a UTF-8 `.txt` or `.csv` file. Both extensions use comma-separated values,
with one player per row: `name` or `name,chips`. An optional first row of `name`
or `name,chips` is treated as a header (case-insensitive). For example:

```csv
name,chips
Alice,6
Bob,
Charlie
"Doe, Jane",3
```

Missing or blank chip values default to **4** for each imported player. Chip
values must be whole numbers from 1 to **10**; no player may have more than 10 chips.
Imported chip values are
retained when switching tournament formats; elimination brackets use only names.
Names are trimmed, blank lines are skipped, and names containing commas must be
quoted. Files may include a UTF-8 byte-order mark. Import keeps the first 32 valid,
unique players in file order; at least two are needed to start.

Lines with blank names, invalid chip counts, or extra columns are skipped. Duplicate
names are skipped after trimming whitespace, using case-sensitive comparison; the
first valid occurrence keeps its chip count. A rejected row does not prevent a
later valid occurrence of that name from being imported. Players beyond the
32-player limit are also skipped. Missing chips default to 4, but invalid chip
values cause that row to be skipped rather than changing its chip count.

A successful import replaces all existing players and clears unfinished player
input while preserving the format and table count. The imported/skipped counts
appear below the player list. When rows are skipped, an **Import Results** dialog
offers **Show Details** with each row number and rejection reason.

Cancellation, unreadable files, invalid encoding, malformed CSV, and files with no
usable players leave the entire roster and unfinished input unchanged. File errors
appear below the player list. Files with no usable players also report all rejected
rows, if any. Broken quoting rejects the file even if valid rows appear before it.

Chip Tournament adds a **Chip count** field directly below the player-name field.
Enter a name and a whole-number count from **1 to 10**, then click **Add Player**.
Both fields clear after adding; no chip count is supplied automatically.
Enter in the name field moves to the chip field; Enter there adds the player.
The roster displays names and chip counts in aligned columns, and returning
through the menu preserves them. Players entered in bracket modes have no chip
count and are marked **Chips not set** when viewed in chip mode.
Select a registered player to edit their name or chip count, then click
**Update Player**. Start requires at least two players, a chip count for every
player, and no unfinished entry.

For elimination formats, Start becomes available after adding at least two players and leaving no name
waiting to be added. Clicking it first asks where to create the tournament's
`.json` file; canceling leaves setup unchanged. After choosing the file, the app
shuffles the players, locks the draw, assigns
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
complete. Each result is saved automatically before the display advances.

Returning to the main menu asks for confirmation, with **No** selected by default.
Winner selection, confirmation, replacement, and error dialogs use their natural
proportions with dialog dimensions and text enlarged by 1.5×. File browsers keep
their own sizing.
Choosing No, pressing Escape, or closing the dialog keeps the current screen open.
Back to Menu preserves the table count, player list, and any unfinished name, including
when choosing a different format.
Start creates a new draw and requires a tournament file, with confirmation before
replacing an existing file.
Use Tab or Shift+Tab to move between controls and Enter or Space to activate
the focused button. The window can be resized.

## Manual player-import checks

The following sample files are in the repository root. Open any tournament setup
page and choose **Import Players…**. For preservation checks, first add two players
and leave an unfinished name in the input field. The roster and unfinished input
should remain unchanged after the failed import. The samples work in all three
formats; Chip Tournament displays the imported chip values directly.

| Sample file | Expected result |
|---|---|
| `import_case_duplicate_names.txt` | Import 14 players: `player_1`–`player_10` and `player_12`–`player_15`, each with 4 chips. Skip row 15, the second `player_1`. This mirrors `player_list.txt`. |
| `import_case_blank_names.csv` | Import Alice (6) and Bob (4). Skip rows 3 and 4 for blank names. |
| `import_case_invalid_chips.csv` | Import Alice (6), Bob (4), and Charlie (1). Skip rows 3–8: zero, negative, decimal, text, over-limit (11), and non-ASCII chip counts. |
| `import_case_extra_columns.csv` | Import Alice (6) and Bob (4). Skip row 3 for extra columns. |
| `import_case_over_32_players.csv` | Import Player01–Player32 with 4 chips each. Skip rows 34 and 35, Player33 and Player34. |
| `import_case_malformed_csv.csv` | Preserve setup and report malformed CSV ending at row 5. Even Alice and Bob before the broken quote must not be imported. |
| `import_case_invalid_encoding.txt` | Preserve setup and request UTF-8. This sample is deliberately saved in unsupported UTF-16. |
| `import_case_unreadable_file.txt` | While locked as described below, preserve setup and show the file-access error. After unlocking, import Alice (6) and Bob (4). |
| `import_case_empty_file.txt` | Preserve setup and report that at least one usable player is required. |
| `import_case_header_only.csv` | Preserve setup and report that at least one usable player is required. |
| `import_case_all_invalid_rows.csv` | Preserve setup. Report no usable players and three skipped rows: row 2 has no name, row 3 has invalid chips, and row 4 has extra columns. |

To check the unreadable-file case on Windows, leave the app open and run this in
a PowerShell terminal at the repository root. While the terminal waits for Enter,
try importing `import_case_unreadable_file.txt` in the app. Return to the terminal
and press Enter to release the lock, then retry the import; it should succeed.
The lock does not change the file's contents or permissions.

```powershell
$importSamplePath = Join-Path (Get-Location) 'import_case_unreadable_file.txt'
$importSampleLock = [System.IO.File]::Open(
    $importSamplePath,
    [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::Read,
    [System.IO.FileShare]::None
)
try {
    Read-Host 'Test the import in Tourney, then press Enter here to unlock the file'
} finally {
    $importSampleLock.Dispose()
}
```

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

Single- and double-elimination bracket pages also have a **Zoom** slider beside
the title. Choose **25%–200%** in 5% steps; **100%** matches the normal bracket size
for the current window. Zoom scales the bracket's cards, text, and connectors
while page controls and winner dialogs keep their normal size. Scrolling and
clicking active matches work at every zoom level. Zooming keeps the current view
center where the scroll boundaries allow it.

Focus Zoom with Tab or Alt+Z. Arrow keys adjust it by 5%, Page Up/Down by 25%,
and Home/End select 25%/200%. Zoom is retained through results, undo, Save As, and
window resizing. Successfully starting or loading a tournament resets it to 100%;
canceled or failed operations leave it unchanged. New bracket previews start at
100%. Zoom is a display preference and is not saved in tournament files.

## Save and load a tournament

Every new tournament requires a readable UTF-8 `.json` file. Results and undo
operations automatically update it. The file path appears on the tournament screen.
If saving or scheduling fails, the previous result, history, and file remain unchanged;
resolve the error and try again.

Press **Ctrl+Shift+S** on a tournament page to use Save As and copy the complete
tournament and undo history to another file.
After a successful save, that file becomes the active location for automatic saves.
Use **Load Tournament** on the main menu to restore a tournament. Loading preserves the
exact draw, table assignments, and undo history; it never reshuffles players or
redraws chip rounds. Ctrl+O opens Load from the main menu. macOS uses the platform's
standard shortcuts.

Use **Undo Last Result** or Ctrl+Z to restore the state before the most recent
winner selection. The confirmation shows the table's current bracket box and the
previous box to restore (for example, from W2 back to W1). A free table is shown as
"unassigned".
Stop affected physical play before confirming; the app cannot detect whether play
has begun. Undo restores table assignments, chip counts, byes, pairings, and champion
status exactly. Select the correct winner once the match returns to active play.
Repeat undo to reach an older mistake; intervening results must then be recorded again.
Undo history persists when reopening the file. There is no redo or fixed history limit.

Chip saves preserve starting and current chip counts, every round and result,
byes, and active table assignments. Loading restores the current round without
changing its pairings.
Saved chip tournaments with starting or remaining chip counts above 10 are rejected.

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
its draw locked. Result entry, undo, Save As, and navigation are disabled while
a scheduling transaction is pending.

Older JSON snapshots without undo history open for viewing only. Their draw,
results, and tables are preserved, but result entry, undo, and Save As are disabled.
Start a new tournament to use automatic saving and undo.

Invalid or unsupported files are rejected before changing the current tournament.
Saving flushes a temporary file beside the destination and replaces the old file
atomically; a failed write leaves the previous save intact. New files use a version-1
`tourney-history` document envelope with the current version-1 tournament snapshot
and an ordered stack of result records containing the match identifier, winner index,
and full snapshot before the result. Undo removes the latest record; a replacement
result starts a new continuation. All snapshots and result transitions are validated
on loading. Future bracket-rule changes will require an explicit migration.

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
