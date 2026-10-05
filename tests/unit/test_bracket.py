from collections import Counter
from collections.abc import Callable, Sequence
from unittest.mock import patch

import pytest

from bracket import create_bracket, shuffle_names


def test_shuffle_names_preserves_players_and_input() -> None:
    names = ["Alice", "Bob", "Carol", "Alice"]
    original = names.copy()

    shuffled = shuffle_names(names)

    assert Counter(shuffled) == Counter(original)
    assert names == original
    assert shuffled is not names


def test_shuffle_names_shuffles_the_copy() -> None:
    names = ["Alice", "Bob", "Carol"]
    with patch("bracket.random.shuffle", side_effect=lambda players: players.reverse()) as shuffle:
        shuffled = shuffle_names(names)

    shuffle.assert_called_once_with(shuffled)
    assert shuffled == ["Carol", "Bob", "Alice"]
    assert names == ["Alice", "Bob", "Carol"]


@pytest.mark.parametrize("player_count", [2, 4, 8, 16, 32])
def test_create_bracket_pairs_names_in_order(player_count: int) -> None:
    names = [f"Player {index}" for index in range(player_count)]

    assert create_bracket(names) == [
        (names[index], names[index + 1]) for index in range(0, player_count, 2)
    ]


def test_create_bracket_with_three_players() -> None:
    assert create_bracket(["Alice", "Bob", "Carol"]) == [
        ("Alice", "Bob"),
        ("Carol", None),
    ]


def test_create_bracket_with_five_players() -> None:
    assert create_bracket(["Alice", "Bob", "Carol", "Dan", "Eve"]) == [
        ("Alice", "Bob"),
        ("Carol", None),
        ("Dan", None),
        ("Eve", None),
    ]


@pytest.mark.parametrize("player_count", range(2, 33))
def test_create_bracket_preserves_players_and_fills_opening_round(player_count: int) -> None:
    names = [f"Player {index}" for index in range(player_count)]
    original = names.copy()
    bracket_size = 1 << (player_count - 1).bit_length()

    matches = create_bracket(names)
    players = [player for match in matches for player in match if player is not None]

    assert len(matches) == bracket_size // 2
    assert players == original
    assert sum(opponent is None for _, opponent in matches) == bracket_size - player_count
    assert names == original


@pytest.mark.parametrize("player_count", [0, 1, 33])
@pytest.mark.parametrize("function", [shuffle_names, create_bracket])
def test_functions_reject_invalid_player_counts(
    function: Callable[[Sequence[str]], object], player_count: int
) -> None:
    names = [f"Player {index}" for index in range(player_count)]

    with pytest.raises(ValueError, match="between 2 and 32 players"):
        function(names)
