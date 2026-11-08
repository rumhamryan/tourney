"""Immutable, round-based chip tournaments with random pairings and fair byes."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from random import choice, shuffle

MAX_CHIPS = 10

_MIN_PLAYERS = 2
_MAX_PLAYERS = 32
_MAX_NUMBER = 2**31 - 1
_MATCH_PLAYERS = 2


@dataclass(frozen=True)
class ChipPlayer:
    name: str
    starting_chips: int
    chips: int
    byes: int = 0


@dataclass(frozen=True)
class ChipMatch:
    identifier: str
    players: tuple[int, int]
    table_number: int | None = None
    winner_index: int | None = None


@dataclass(frozen=True)
class ChipRound:
    number: int
    matches: tuple[ChipMatch, ...]
    bye_index: int | None = None


@dataclass(frozen=True)
class ChipTournament:
    players: tuple[ChipPlayer, ...]
    table_count: int
    rounds: tuple[ChipRound, ...]


def _number(value: object, maximum: int, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _validate_players(state: ChipTournament) -> None:
    if (
        not isinstance(state.players, tuple)
        or not _MIN_PLAYERS <= len(state.players) <= _MAX_PLAYERS
    ):
        raise ValueError("A chip tournament needs 2–32 players.")
    if not _number(state.table_count, _MAX_NUMBER, 1):
        raise ValueError("The table count must be a positive whole number.")
    for player in state.players:
        if not isinstance(player, ChipPlayer) or (
            not isinstance(player.name, str)
            or not player.name.strip()
            or player.name != player.name.strip()
        ):
            raise ValueError("Players must have nonblank names.")
        if not _number(player.starting_chips, MAX_CHIPS, 1) or not _number(
            player.chips, player.starting_chips
        ):
            raise ValueError(
                f"Players need 1–{MAX_CHIPS} starting chips and valid remaining chip counts."
            )
        if not _number(player.byes, len(state.rounds)):
            raise ValueError("Invalid bye count.")


def _validate_participants(round_: ChipRound, chips: list[int], byes: list[int]) -> None:
    alive = {index for index, count in enumerate(chips) if count > 0}
    participants = [player for match in round_.matches for player in match.players]
    if any(not _number(player, len(chips) - 1) for player in participants):
        raise ValueError("Unknown player in a matchup.")
    if len(alive) % _MATCH_PLAYERS:
        bye = round_.bye_index
        if not _number(bye, len(chips) - 1) or bye not in alive:
            raise ValueError("An odd roster needs one eligible bye.")
        assert bye is not None
        if byes[bye] != min(byes[index] for index in alive):
            raise ValueError("Byes must go to players with the fewest previous byes.")
        byes[bye] += 1
        participants.append(bye)
    elif round_.bye_index is not None:
        raise ValueError("An even roster cannot have a bye.")
    if len(participants) != len(set(participants)) or set(participants) != alive:
        raise ValueError("Every surviving player must appear exactly once per round.")


def _validate_match(match: ChipMatch, chips: list[int], tables: set[int], table_count: int) -> None:
    if match.winner_index is not None:
        if type(match.winner_index) is not int or match.winner_index not in match.players:
            raise ValueError("A match winner must be one of its players.")
        if match.table_number is not None:
            raise ValueError("Completed matches cannot occupy tables.")
        loser = next(player for player in match.players if player != match.winner_index)
        chips[loser] -= 1
    elif match.table_number is not None:
        if not _number(match.table_number, table_count, 1) or match.table_number in tables:
            raise ValueError("Active matches must occupy distinct, existing tables.")
        tables.add(match.table_number)


def _validate_round_shape(round_: ChipRound, number: int) -> None:
    if (
        not isinstance(round_, ChipRound)
        or type(round_.number) is not int
        or round_.number != number
    ):
        raise ValueError("Rounds must be consecutive.")
    if not isinstance(round_.matches, tuple) or not round_.matches:
        raise ValueError("A round must contain matchups.")
    for index, match in enumerate(round_.matches, start=1):
        if (
            not isinstance(match, ChipMatch)
            or match.identifier != f"R{number}M{index}"
            or not isinstance(match.players, tuple)
            or len(match.players) != _MATCH_PLAYERS
        ):
            raise ValueError("Invalid numbered matchup.")


def validate_tournament(state: ChipTournament) -> None:
    """Replay the saved rounds and reject inconsistent counts, players, or tables."""
    if not isinstance(state.rounds, tuple) or not state.rounds:
        raise ValueError("A started chip tournament must contain a round.")
    _validate_players(state)
    chips = [player.starting_chips for player in state.players]
    byes = [0] * len(state.players)
    for number, round_ in enumerate(state.rounds, start=1):
        _validate_round_shape(round_, number)
        _validate_participants(round_, chips, byes)
        tables: set[int] = set()
        for match in round_.matches:
            _validate_match(match, chips, tables, state.table_count)
        if number < len(state.rounds) and any(
            match.winner_index is None for match in round_.matches
        ):
            raise ValueError("A new round cannot begin before all previous matches finish.")
    if chips != [player.chips for player in state.players] or byes != [
        p.byes for p in state.players
    ]:
        raise ValueError("Chip or bye counts disagree with the recorded rounds.")


def champion_index(state: ChipTournament) -> int | None:
    """Identify the champion when only one player still has chips."""
    alive = [index for index, player in enumerate(state.players) if player.chips > 0]
    return alive[0] if len(alive) == 1 else None


def _dispatch(state: ChipTournament) -> ChipTournament:
    round_ = state.rounds[-1]
    occupied = {match.table_number for match in round_.matches if match.table_number is not None}
    matches = list(round_.matches)
    table = 1
    for index, match in enumerate(matches):
        if match.winner_index is not None or match.table_number is not None:
            continue
        if len(occupied) == state.table_count:
            break
        while table in occupied:
            table += 1
        matches[index] = replace(match, table_number=table)
        occupied.add(table)
    return replace(state, rounds=(*state.rounds[:-1], replace(round_, matches=tuple(matches))))


def _next_round(state: ChipTournament) -> ChipTournament:
    alive = [index for index, player in enumerate(state.players) if player.chips > 0]
    players = list(state.players)
    bye = None
    if len(alive) % _MATCH_PLAYERS:
        least = min(players[index].byes for index in alive)
        bye = choice([index for index in alive if players[index].byes == least])
        alive.remove(bye)
        players[bye] = replace(players[bye], byes=players[bye].byes + 1)
    shuffle(alive)
    number = len(state.rounds) + 1
    matches = tuple(
        ChipMatch(f"R{number}M{index // 2 + 1}", (alive[index], alive[index + 1]))
        for index in range(0, len(alive), 2)
    )
    return _dispatch(
        replace(
            state, players=tuple(players), rounds=(*state.rounds, ChipRound(number, matches, bye))
        )
    )


def start_tournament(
    names: Sequence[str], chip_counts: Sequence[int], table_count: int
) -> ChipTournament:
    """Create the first random round, with stable player indices for repeated names."""
    if len(names) != len(chip_counts):
        raise ValueError("Every player needs an explicit chip count.")
    players = tuple(
        ChipPlayer(name, count, count) for name, count in zip(names, chip_counts, strict=True)
    )
    state = ChipTournament(players, table_count, ())
    _validate_players(state)
    state = _next_round(state)
    validate_tournament(state)
    return state


def resume_tournament(state: ChipTournament) -> ChipTournament:
    """Fill free tables without changing any unfinished round's pairings."""
    validate_tournament(state)
    if champion_index(state) is not None:
        return state
    if all(match.winner_index is not None for match in state.rounds[-1].matches):
        return _next_round(state)
    return _dispatch(state)


def record_result(state: ChipTournament, match_id: str, winner_index: int) -> ChipTournament:
    """Remove one chip from the loser and advance the round only after its last match."""
    validate_tournament(state)
    round_ = state.rounds[-1]
    match = next((match for match in round_.matches if match.identifier == match_id), None)
    if match is None or match.table_number is None:
        raise ValueError("Only a match in progress can have its result recorded.")
    if type(winner_index) is not int or winner_index not in match.players:
        raise ValueError("Choose one of this match's players as the winner.")
    loser = next(player for player in match.players if player != winner_index)
    players = list(state.players)
    players[loser] = replace(players[loser], chips=players[loser].chips - 1)
    completed = replace(match, winner_index=winner_index, table_number=None)
    matches = tuple(completed if item == match else item for item in round_.matches)
    result = replace(
        state, players=tuple(players), rounds=(*state.rounds[:-1], replace(round_, matches=matches))
    )
    result = resume_tournament(result)
    validate_tournament(result)
    return result
