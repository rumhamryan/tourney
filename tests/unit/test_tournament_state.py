from dataclasses import replace
from typing import Any

import pytest

from bracket_preview import build_preview
from tournament_state import (
    MatchProgress,
    TableLabel,
    TournamentState,
    resolved_outcomes,
    validate_tournament,
)


@pytest.fixture
def state() -> TournamentState:
    draw = build_preview(["Alice", "Bob", "Carol", "Dana"], "Single Elimination")
    return TournamentState(draw, tuple(reversed(draw.names)), 4)


@pytest.mark.parametrize("count", range(2, 33))
@pytest.mark.parametrize("tournament_format", ["Single Elimination", "Double Elimination"])
def test_valid_new_tournament(count: int, tournament_format: str) -> None:
    draw = build_preview([f"Player {i}" for i in range(count)], tournament_format)
    validate_tournament(TournamentState(draw, draw.names, 1))


def test_resolves_completed_matches_and_automatic_byes() -> None:
    draw = build_preview(["Alice", "Bob", "Carol"], "Single Elimination")
    state = TournamentState(
        draw,
        draw.names,
        1,
        progress=(MatchProgress("W1", "completed", winner_index=1),),
        draw_locked=True,
    )
    assert resolved_outcomes(state) == {"W1": (1, 0), "W2": (2, None)}


def test_in_progress_table_and_custom_label_are_valid(state: TournamentState) -> None:
    active = replace(
        state,
        progress=(MatchProgress("W1", "in_progress", table_number=3),),
        table_labels=(TableLabel(3, "Feature table"),),
        draw_locked=True,
    )
    validate_tournament(active)
    assert resolved_outcomes(active) == {}


@pytest.mark.parametrize("winner", [0, 1])
def test_double_final_allows_reset_only_after_losers_finalist_wins(winner: int) -> None:
    draw = build_preview(["Alice", "Bob"], "Double Elimination")
    state = TournamentState(
        draw,
        draw.names,
        1,
        progress=(
            MatchProgress("W1", "completed", winner_index=0),
            MatchProgress("GF", "completed", winner_index=winner),
            MatchProgress("RESET", "in_progress", table_number=1),
        ),
        draw_locked=True,
    )
    if winner == 1:
        validate_tournament(state)
    else:
        with pytest.raises(ValueError):
            validate_tournament(state)


@pytest.mark.parametrize(
    "changes",
    [
        {"table_count": 0},
        {"table_count": True},
        {"table_count": 2**31},
        {"entry_names": ("Alice", "Bob")},
        {"draw_locked": 1},
        {"table_labels": (TableLabel(0, "Bad"),)},
        {"table_labels": (TableLabel(5, "Bad"),)},
        {"table_labels": (TableLabel(1, " "),)},
        {"table_labels": (TableLabel(1, "A"), TableLabel(1, "B"))},
        {"progress": (MatchProgress("unknown", "completed", winner_index=0),)},
        {"progress": (MatchProgress("W1", "unknown"),)},
        {"progress": (MatchProgress("W1", "pending", winner_index=0),)},
        {"progress": (MatchProgress("W1", "pending", table_number=1),)},
        {"progress": (MatchProgress("W1", "in_progress", table_number=1),)},
    ],
)
def test_rejects_invalid_tournament_parameters(
    state: TournamentState, changes: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        validate_tournament(replace(state, **changes))


@pytest.mark.parametrize(
    "progress",
    [
        (MatchProgress("W1", "completed", winner_index=2),),
        (MatchProgress("W1", "completed", winner_index=True),),
        (MatchProgress("W1", "completed"),),
        (MatchProgress("W1", "completed", winner_index=0, table_number=1),),
        (MatchProgress("W1", "in_progress"),),
        (MatchProgress("W1", "in_progress", table_number=5),),
        (MatchProgress("W1", "in_progress", table_number=True),),
        (MatchProgress("W1", "in_progress", winner_index=0, table_number=1),),
        (MatchProgress("W3", "completed", winner_index=0),),
        (MatchProgress("W3", "in_progress", table_number=1),),
        (MatchProgress("W1", "pending"), MatchProgress("W1", "pending")),
        (
            MatchProgress("W1", "in_progress", table_number=1),
            MatchProgress("W2", "in_progress", table_number=1),
        ),
    ],
)
def test_rejects_inconsistent_progress(
    state: TournamentState, progress: tuple[MatchProgress, ...]
) -> None:
    with pytest.raises(ValueError):
        validate_tournament(replace(state, progress=progress, draw_locked=True))


def test_cannot_record_a_result_for_an_automatic_bye() -> None:
    draw = build_preview(["Alice", "Bob", "Carol"], "Single Elimination")
    state = TournamentState(
        draw,
        draw.names,
        1,
        progress=(MatchProgress("W2", "completed", winner_index=2),),
        draw_locked=True,
    )
    with pytest.raises(ValueError):
        resolved_outcomes(state)


def test_completed_final_and_locked_draw_without_results_are_valid(state: TournamentState) -> None:
    progress = (
        MatchProgress("W1", "completed", winner_index=0),
        MatchProgress("W2", "completed", winner_index=3),
        MatchProgress("W3", "completed", winner_index=3),
    )
    finished = replace(state, progress=progress, draw_locked=True)
    validate_tournament(finished)
    assert resolved_outcomes(finished)["W3"] == (3, 0)
    validate_tournament(replace(state, draw_locked=True))
