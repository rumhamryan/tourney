from dataclasses import replace
from functools import cache
from itertools import combinations
from unittest.mock import patch

import pytest

from bracket_preview import build_preview
from table_scheduler import schedule_tables
from tournament_state import (
    MatchProgress,
    TournamentState,
    match_players,
    record_result,
    validate_tournament,
)

_LARGE_PLAYER_COUNT = 32
_CONFLICT_CHECK_SOLVER_LIMIT = 0.01


def _state(
    count: int, tables: int, tournament_format: str = "Single Elimination"
) -> TournamentState:
    draw = build_preview([f"Player {index}" for index in range(count)], tournament_format)
    return TournamentState(draw, draw.names, tables)


def _minimum_waves(state: TournamentState) -> int:
    """Exhaustively enumerate simultaneous batches, independently of either scheduler."""
    matches = state.draw.matches
    indexes = {match.identifier: index for index, match in enumerate(matches)}
    prerequisites = [
        sum(
            1 << index
            for index in {
                indexes[source.match_id] for source in match.slots if source.match_id is not None
            }
        )
        for match in matches
    ]
    byes = {index for index, match in enumerate(matches) if any(s.empty for s in match.slots)}
    finished = (1 << len(matches)) - 1

    @cache
    def visit(done: int) -> int:
        while True:
            expanded = done
            for index in byes:
                if prerequisites[index] & done == prerequisites[index]:
                    expanded |= 1 << index
            if expanded == done:
                break
            done = expanded
        if done == finished:
            return 0
        ready = [
            index
            for index in range(len(matches))
            if not done & (1 << index) and prerequisites[index] & done == prerequisites[index]
        ]
        return 1 + min(
            visit(done | sum(1 << index for index in batch))
            for batch in combinations(ready, min(state.table_count, len(ready)))
        )

    return visit(0)


@pytest.mark.parametrize("count", [2, 3, 5, 8])
@pytest.mark.parametrize("tables", [1, 2, 3])
def test_hu_schedule_matches_exhaustive_optimum(count: int, tables: int) -> None:
    state = _state(count, tables)
    expected = _minimum_waves(state)
    waves = 0
    while True:
        result = schedule_tables(state)
        assert result.algorithm == "hu"
        active = [item for item in result.state.progress if item.status == "in_progress"]
        if not active:
            break
        state = result.state
        for item in active:
            winner = match_players(state, item.match_id)[0]
            assert winner is not None
            state = record_result(state, item.match_id, winner)
        waves += 1
    assert waves == expected


@pytest.mark.parametrize("count", [2, 3, 5, 8])
@pytest.mark.parametrize("tables", [1, 2, 3])
def test_cp_sat_proves_initial_schedule_optimal(count: int, tables: int) -> None:
    state = _state(count, tables, "Double Elimination")
    result = schedule_tables(state)
    assert result.algorithm == "cp_sat"
    assert result.solver_status == "OPTIMAL"
    assert result.makespan_units == _minimum_waves(state)
    assert len(result.state.progress) == min(tables, count // 2)
    validate_tournament(result.state)


def test_hu_prioritizes_longer_chain_over_ready_later_round() -> None:
    state = _state(8, 1)
    state = replace(
        state,
        draw_locked=True,
        progress=(
            MatchProgress("W1", "completed", winner_index=0),
            MatchProgress("W2", "completed", winner_index=2),
        ),
    )
    result = schedule_tables(state)
    assert result.state.progress[-1] == MatchProgress("W3", "in_progress", table_number=1)


@pytest.mark.parametrize("tournament_format", ["Single Elimination", "Double Elimination"])
def test_existing_assignments_preserved_and_lowest_free_tables_used(tournament_format: str) -> None:
    state = _state(8, 3, tournament_format)
    active = MatchProgress("W1", "in_progress", table_number=2)
    state = replace(state, progress=(active,), draw_locked=True)
    result = schedule_tables(state)
    assert active in result.state.progress
    assert {item.table_number for item in result.state.progress} == {1, 2, 3}
    assert state.progress == (active,)
    assert schedule_tables(result.state).state == result.state


@pytest.mark.parametrize("status", ["FEASIBLE", "UNKNOWN", "INFEASIBLE", "MODEL_INVALID"])
def test_nonoptimal_solver_status_uses_critical_path_fallback(status: str) -> None:
    state = _state(8, 2, "Double Elimination")
    with patch("table_scheduler._solve_cp", return_value=(status, (), None)):
        result = schedule_tables(state)
    assert result.algorithm == "critical_path"
    assert result.solver_status == status
    assert result.makespan_units is None
    assert [item.match_id for item in result.state.progress] == ["W1", "W2"]


@pytest.mark.parametrize("tournament_format", ["Single Elimination", "Double Elimination"])
@pytest.mark.parametrize("tables", [1, 6, 2147483647])
@pytest.mark.parametrize("count", [8, _LARGE_PLAYER_COUNT])
def test_bracket_finishes_without_conflicts(
    tournament_format: str, tables: int, count: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    if count == _LARGE_PLAYER_COUNT:
        # These runs check safety and completion, including the real solver's fallback.
        # Small exhaustive optimality checks and full 8-player runs keep the normal limit.
        monkeypatch.setattr("table_scheduler._SOLVER_TIME_LIMIT", _CONFLICT_CHECK_SOLVER_LIMIT)
    state = _state(count, tables, tournament_format)
    for _ in range(len(state.draw.matches) + 1):
        state = schedule_tables(state).state
        active = [item for item in state.progress if item.status == "in_progress"]
        if not active:
            break
        assert len({item.table_number for item in active}) == len(active)
        players = [player for item in active for player in match_players(state, item.match_id)]
        assert len(set(players)) == len(players)
        for item in active:
            winner = match_players(state, item.match_id)[0]
            assert winner is not None
            state = record_result(state, item.match_id, winner)
        validate_tournament(state)
    else:
        pytest.fail("Tournament did not finish")
    expected = (count - 1) * (1 if tournament_format == "Single Elimination" else 2)
    assert sum(item.status == "completed" for item in state.progress) == expected
    assert schedule_tables(state).state == state


@pytest.mark.parametrize("lower_wins", [False, True])
def test_final_reset_only_scheduled_when_required(lower_wins: bool) -> None:
    state = _state(2, 1, "Double Elimination")
    state = schedule_tables(state).state
    state = record_result(state, "W1", 0)
    state = schedule_tables(state).state
    state = record_result(state, "GF", int(lower_wins))
    result = schedule_tables(state)
    assert any(item.match_id == "RESET" for item in result.state.progress) == lower_wins


def test_invalid_snapshot_is_rejected_without_mutation() -> None:
    state = _state(4, 0)
    with pytest.raises(ValueError):
        schedule_tables(state)
    assert state.progress == ()
