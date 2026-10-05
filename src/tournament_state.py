"""Complete, immutable tournament snapshots independent of the desktop UI."""

from collections import Counter
from dataclasses import dataclass, replace

from bracket_preview import Draw, PreviewMatch, Source, build_preview

_MAX_TABLES = 2**31 - 1
_MIN_PLAYERS = 2
_MAX_PLAYERS = 32
Outcome = tuple[int | None, int | None]


@dataclass(frozen=True)
class MatchProgress:
    """Progress for a numbered match; omitted matches are pending.

    Player indices refer to draw order, keeping duplicate names distinct.
    Only in-progress matches occupy tables; completed matches retain a winner.
    """

    match_id: str
    status: str = "pending"
    winner_index: int | None = None
    table_number: int | None = None


@dataclass(frozen=True)
class TableLabel:
    """An optional label override for a one-based table number."""

    number: int
    label: str


@dataclass(frozen=True)
class TournamentState:
    """Everything needed to restore the same draw and its progress.

    Entry order is saved separately from randomized draw order. A locked
    draw stays locked even after all results have been undone. Table labels
    default to 'Table N', so large table counts need no list allocation.
    """

    draw: Draw
    entry_names: tuple[str, ...]
    table_count: int
    progress: tuple[MatchProgress, ...] = ()
    table_labels: tuple[TableLabel, ...] = ()
    draw_locked: bool = False


def _valid_number(value: int | None, maximum: int) -> bool:
    return type(value) is int and 1 <= value <= maximum


def _validate_names(names: tuple[str, ...]) -> None:
    if not _MIN_PLAYERS <= len(names) <= _MAX_PLAYERS or any(
        not isinstance(name, str) or not name.strip() or name != name.strip() for name in names
    ):
        raise ValueError("Players must contain 2–32 nonblank names.")


def _validate_draw(draw: Draw) -> None:
    _validate_names(draw.names)
    for match in draw.matches:
        if type(match.round_number) is not int or type(match.conditional) is not bool:
            raise ValueError("Invalid match round or conditional flag.")
        for source in match.slots:
            if type(source.loser) is not bool or (
                source.player_index is not None and type(source.player_index) is not int
            ):
                raise ValueError("Invalid match source.")
    if draw != build_preview(draw.names, draw.tournament_format):
        raise ValueError("The saved bracket structure is invalid for this format and player count.")


def _validate_tables(state: TournamentState) -> None:
    if not _valid_number(state.table_count, _MAX_TABLES):
        raise ValueError("The table count must be a positive whole number.")
    seen: set[int] = set()
    for table in state.table_labels:
        if not _valid_number(table.number, state.table_count) or table.number in seen:
            raise ValueError("Table labels must reference distinct, existing tables.")
        if not isinstance(table.label, str) or not table.label.strip():
            raise ValueError("Table labels cannot be blank.")
        seen.add(table.number)


def _progress_by_id(state: TournamentState) -> dict[str, MatchProgress]:
    identifiers = {match.identifier for match in state.draw.matches}
    progress: dict[str, MatchProgress] = {}
    for item in state.progress:
        if item.match_id not in identifiers or item.match_id in progress:
            raise ValueError("Match progress must reference distinct, existing matches.")
        if item.status not in {"pending", "in_progress", "completed"}:
            raise ValueError("Unknown match status.")
        if item.status != "pending" and not state.draw_locked:
            raise ValueError("The draw must be locked once a match starts.")
        if item.status == "pending" and (
            item.winner_index is not None or item.table_number is not None
        ):
            raise ValueError("Pending matches cannot have a result or occupy a table.")
        progress[item.match_id] = item
    return progress


def _resolve(source: Source, outcomes: dict[str, Outcome]) -> int | None:
    if source.match_id is None:
        return source.player_index
    outcome = outcomes.get(source.match_id)
    return outcome[int(source.loser)] if outcome is not None else None


def _ready(match: PreviewMatch, outcomes: dict[str, Outcome], draw: Draw) -> bool:
    if any(
        source.match_id is not None and source.match_id not in outcomes for source in match.slots
    ):
        return False
    if match.conditional:
        final = next(item for item in draw.matches if item.identifier == "GF")
        return outcomes.get("GF", (None, None))[0] == _resolve(final.slots[1], outcomes)
    return True


def _validate_active(item: MatchProgress, state: TournamentState, occupied: set[int]) -> None:
    if (
        not _valid_number(item.table_number, state.table_count)
        or item.table_number in occupied
        or item.winner_index is not None
    ):
        raise ValueError("An active match needs an available table and cannot have a winner.")
    assert item.table_number is not None
    occupied.add(item.table_number)


def resolved_outcomes(state: TournamentState) -> dict[str, Outcome]:
    """Resolve completed matches and byes, rejecting inconsistent progress."""
    progress = _progress_by_id(state)
    outcomes: dict[str, Outcome] = {}
    occupied: set[int] = set()
    for match in state.draw.matches:
        item = progress.get(match.identifier, MatchProgress(match.identifier))
        ready = _ready(match, outcomes, state.draw)
        players = tuple(_resolve(source, outcomes) for source in match.slots)
        present = [player for player in players if player is not None]
        if item.status != "pending" and (not ready or len(present) != len(match.slots)):
            raise ValueError(
                f"Match {match.identifier} cannot start before both players are ready."
            )
        if item.status == "completed":
            if (
                type(item.winner_index) is not int
                or item.winner_index not in present
                or item.table_number is not None
            ):
                raise ValueError(f"Match {match.identifier} has an invalid result.")
            outcomes[match.identifier] = (
                item.winner_index,
                next(player for player in present if player != item.winner_index),
            )
        elif item.status == "in_progress":
            _validate_active(item, state, occupied)
        elif ready and len(present) < len(match.slots):
            outcomes[match.identifier] = (present[0] if present else None, None)
    return outcomes


def validate_tournament(state: TournamentState) -> None:
    """Reject invalid parameters, broken brackets, and impossible progress."""
    _validate_draw(state.draw)
    _validate_names(state.entry_names)
    if Counter(state.entry_names) != Counter(state.draw.names):
        raise ValueError("Setup players must match the players in the bracket.")
    if type(state.draw_locked) is not bool:
        raise ValueError("The draw-lock flag must be true or false.")
    _validate_tables(state)
    resolved_outcomes(state)


def match_players(state: TournamentState, match_id: str) -> tuple[int | None, int | None]:
    """Resolve the two player indexes for an existing match, including byes."""
    match = next((match for match in state.draw.matches if match.identifier == match_id), None)
    if match is None:
        raise ValueError("Unknown match.")
    outcomes = resolved_outcomes(state)
    return _resolve(match.slots[0], outcomes), _resolve(match.slots[1], outcomes)


def ready_matches(state: TournamentState) -> tuple[PreviewMatch, ...]:
    """Return pending matches with two resolved players and eligible dependencies."""
    outcomes = resolved_outcomes(state)
    progress = _progress_by_id(state)
    return tuple(
        match
        for match in state.draw.matches
        if progress.get(match.identifier, MatchProgress(match.identifier)).status == "pending"
        and match.identifier not in outcomes
        and _ready(match, outcomes, state.draw)
        and all(_resolve(source, outcomes) is not None for source in match.slots)
    )


def record_result(state: TournamentState, match_id: str, winner_index: int) -> TournamentState:
    """Complete an active match without mutating its snapshot or earlier results."""
    validate_tournament(state)
    active = next((item for item in state.progress if item.match_id == match_id), None)
    if active is None or active.status != "in_progress":
        raise ValueError("Only a match in progress can have its result recorded.")
    if type(winner_index) is not int or winner_index not in match_players(state, match_id):
        raise ValueError("Choose one of this match's players as the winner.")
    completed = MatchProgress(match_id, "completed", winner_index=winner_index)
    result = replace(
        state, progress=tuple(completed if item == active else item for item in state.progress)
    )
    validate_tournament(result)
    return result


def champion_index(state: TournamentState) -> int | None:
    """Return the champion only once the applicable final has been completed."""
    outcomes = resolved_outcomes(state)
    if state.draw.tournament_format == "Single Elimination":
        return outcomes.get(state.draw.matches[-1].identifier, (None, None))[0]
    if "RESET" in outcomes:
        return outcomes["RESET"][0]
    if "GF" in outcomes:
        final = next(match for match in state.draw.matches if match.identifier == "GF")
        if outcomes["GF"][0] == _resolve(final.slots[0], outcomes):
            return outcomes["GF"][0]
    return None
