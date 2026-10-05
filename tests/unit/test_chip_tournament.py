from collections.abc import Iterator
from dataclasses import replace
from unittest.mock import patch

import pytest

from chip_tournament import (
    champion_index,
    record_result,
    resume_tournament,
    start_tournament,
    validate_tournament,
)


@pytest.fixture(autouse=True)
def deterministic_pairing() -> Iterator[None]:
    with (
        patch("chip_tournament.shuffle", side_effect=lambda players: None),
        patch("chip_tournament.choice", side_effect=lambda players: players[0]),
    ):
        yield


def test_start_pairs_once_per_round_and_respects_table_capacity() -> None:
    state = start_tournament(["A", "B", "C", "D", "E"], [3] * 5, 1)
    round_ = state.rounds[-1]
    assert round_.number == 1
    assert round_.bye_index == 0
    assert [match.players for match in round_.matches] == [(1, 2), (3, 4)]
    assert [match.table_number for match in round_.matches] == [1, None]
    assert [player.chips for player in state.players] == [3] * 5
    validate_tournament(state)


def test_result_removes_one_chip_and_dispatches_waiting_match_without_new_round() -> None:
    original = start_tournament(["Same"] * 6, [2] * 6, 2)
    state = record_result(original, "R1M1", 1)
    assert state.players[0].chips == 1
    assert state.players[1].chips == original.players[1].chips
    assert original.players[0].chips == state.players[0].chips + 1
    assert len(state.rounds) == 1
    assert state.rounds[-1].matches[0].winner_index == 1
    assert state.rounds[-1].matches[0].table_number is None
    assert state.rounds[-1].matches[1] == original.rounds[-1].matches[1]
    assert state.rounds[-1].matches[2].table_number == 1


def test_round_waits_for_all_matches_then_reshuffles_survivors() -> None:
    state = start_tournament(["A", "B", "C", "D"], [1] * 4, 2)
    state = record_result(state, "R1M1", 0)
    assert state.players[1].chips == 0
    assert len(state.rounds) == 1
    with patch("chip_tournament.shuffle") as shuffled:
        state = record_result(state, "R1M2", 2)
    shuffled.assert_called_once()
    expected_rounds = 2
    assert len(state.rounds) == expected_rounds
    assert state.rounds[-1].matches[0].players == (0, 2)
    assert all(
        player not in {1, 3} for match in state.rounds[-1].matches for player in match.players
    )


def test_odd_rounds_distribute_byes_fairly_without_chip_loss() -> None:
    state = start_tournament(["A", "B", "C"], [20] * 3, 1)
    completed = 8
    for _ in range(completed):
        match = state.rounds[-1].matches[0]
        state = record_result(state, match.identifier, match.players[0])
    assert [player.byes for player in state.players] == [3] * 3
    assert sum(player.chips for player in state.players) == 3 * 20 - completed


@pytest.mark.parametrize("count", [2, 3, 5, 8, 32])
@pytest.mark.parametrize("tables", [1, 6, 2147483647])
def test_tournament_finishes_without_player_or_table_conflicts(count: int, tables: int) -> None:
    state = start_tournament(["Same"] * count, [2] * count, tables)
    results = 0
    while champion_index(state) is None:
        active = [match for match in state.rounds[-1].matches if match.table_number is not None]
        assert active
        assert len({match.table_number for match in active}) == len(active)
        assert len({player for match in active for player in match.players}) == 2 * len(active)
        match = active[-1]
        state = record_result(state, match.identifier, match.players[0])
        results += 1
        assert results < 2 * count
        validate_tournament(state)
    assert sum(player.chips > 0 for player in state.players) == 1
    assert all(match.table_number is None for match in state.rounds[-1].matches)
    assert results == 2 * count - sum(player.chips for player in state.players)
    assert resume_tournament(state) == state


@pytest.mark.parametrize(
    "identifier, winner", [("missing", 0), ("R1M2", 2), ("R1M1", 9), ("R1M1", True)]
)
def test_invalid_results_are_rejected(identifier: str, winner: int) -> None:
    state = start_tournament(["A", "B", "C", "D"], [2] * 4, 1)
    with pytest.raises(ValueError):
        record_result(state, identifier, winner)


def test_completed_result_cannot_be_changed() -> None:
    state = start_tournament(["A", "B"], [1, 1], 1)
    state = record_result(state, "R1M1", 0)
    assert champion_index(state) == 0
    with pytest.raises(ValueError):
        record_result(state, "R1M1", 1)


@pytest.mark.parametrize("counts, tables", [([0, 1], 1), ([True, 1], 1), ([1], 1), ([1, 1], 0)])
def test_invalid_setup_is_rejected(counts: list[int], tables: int) -> None:
    with pytest.raises(ValueError):
        start_tournament(["A", "B"], counts, tables)


def test_validation_rejects_chip_counts_that_disagree_with_results() -> None:
    state = start_tournament(["A", "B"], [2, 2], 1)
    state = replace(state, players=(replace(state.players[0], chips=1), state.players[1]))
    with pytest.raises(ValueError):
        validate_tournament(state)


def test_resume_preserves_draw_and_running_tables() -> None:
    state = start_tournament(["A", "B", "C", "D"], [2] * 4, 2)
    with patch("chip_tournament.shuffle") as shuffled:
        resumed = resume_tournament(state)
    shuffled.assert_not_called()
    assert resumed == state
