"""Shuffle player names and create single-elimination opening matchups."""

import random
from collections.abc import Sequence

_MIN_PLAYERS = 2
_MAX_PLAYERS = 32


def _validate_player_count(names: Sequence[str]) -> None:
    if not _MIN_PLAYERS <= len(names) <= _MAX_PLAYERS:
        raise ValueError("A bracket requires between 2 and 32 players.")


def shuffle_names(names: Sequence[str]) -> list[str]:
    """Return a shuffled copy of 2–32 names without changing the input."""
    _validate_player_count(names)
    shuffled = list(names)
    random.shuffle(shuffled)
    return shuffled


def create_bracket(names: Sequence[str]) -> list[tuple[str, str | None]]:
    """Return opening matchups in input order, with None representing a bye.

    Fill a bracket of the next power-of-two size. Pair the first names,
    then give each remaining name a bye, so no matchup has two empty slots.
    This function does not shuffle names or generate subsequent rounds.
    """
    _validate_player_count(names)
    bracket_size = 1 << (len(names) - 1).bit_length()
    bye_count = bracket_size - len(names)
    paired_count = len(names) - bye_count
    matches: list[tuple[str, str | None]] = [
        (names[index], names[index + 1]) for index in range(0, paired_count, 2)
    ]
    matches.extend((name, None) for name in names[paired_count:])
    return matches
