import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from bracket_preview import build_preview
from chip_tournament import start_tournament
from table_scheduler import schedule_tables
from tournament_file import (
    TournamentDocument,
    append_result,
    dumps_document,
    load_document,
    loads_document,
    save_document,
    undo_result,
)
from tournament_state import TournamentState, match_players, record_result


def bracket_document(format_: str = "Single Elimination") -> TournamentDocument:
    draw = build_preview(["Same", "Same", "李", "Dana"], format_)
    state = schedule_tables(TournamentState(draw, draw.names, 2)).state
    return TournamentDocument(state)


@pytest.mark.parametrize("format_", ["Single Elimination", "Double Elimination"])
def test_all_results_undo_exactly_after_reload(format_: str) -> None:
    document = bracket_document(format_)
    checkpoints = []
    while True:
        state = document.state
        assert isinstance(state, TournamentState)
        active = next((item for item in state.progress if item.status == "in_progress"), None)
        if active is None:
            break
        checkpoints.append(document)
        players = match_players(state, active.match_id)
        winner = players[1] if active.match_id == "GF" else players[0]
        assert winner is not None
        updated = schedule_tables(record_result(state, active.match_id, winner)).state
        document = append_result(document, active.match_id, winner, updated)
        document = loads_document(dumps_document(document))
    assert checkpoints
    if format_ == "Double Elimination":
        assert document.history[-1].match_id == "RESET"
    for checkpoint in reversed(checkpoints):
        document = undo_result(document)
        assert document == checkpoint
    with pytest.raises(ValueError, match="No result"):
        undo_result(document)


def test_chip_rounds_counts_byes_and_tables_restore_without_randomness() -> None:
    from chip_tournament import record_result as record_chip_result

    document = TournamentDocument(start_tournament(["Same"] * 5, [2] * 5, 1))
    checkpoints = []
    for _ in range(5):
        state = document.state
        assert not isinstance(state, TournamentState)
        match = next(match for match in state.rounds[-1].matches if match.table_number)
        checkpoints.append(document)
        updated = record_chip_result(state, match.identifier, match.players[0])
        document = append_result(document, match.identifier, match.players[0], updated)
    with patch("chip_tournament.shuffle", side_effect=AssertionError("redraw")):
        document = loads_document(dumps_document(document))
        for checkpoint in reversed(checkpoints):
            document = undo_result(document)
            assert document == checkpoint


def test_undo_then_correct_replaces_history_continuation() -> None:
    original = bracket_document()
    assert isinstance(original.state, TournamentState)
    first = schedule_tables(record_result(original.state, "W1", 0)).state
    document = append_result(original, "W1", 0, first)
    restored = undo_result(document)
    assert isinstance(restored.state, TournamentState)
    corrected = schedule_tables(record_result(restored.state, "W1", 1)).state
    document = append_result(restored, "W1", 1, corrected)
    assert len(document.history) == 1
    assert document.history[0].winner_index == 1
    assert undo_result(document) == original


def test_failed_atomic_save_keeps_previous_document(tmp_path: Path) -> None:
    path = tmp_path / "比赛.json"
    original = bracket_document()
    save_document(path, original)
    with (
        patch("tournament_storage.os.replace", side_effect=OSError("disk full")),
        pytest.raises(OSError),
    ):
        save_document(path, original)
    assert load_document(path) == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("corruption", ["winner", "identity", "transition", "version"])
def test_corrupt_history_is_rejected(corruption: str) -> None:
    document = bracket_document()
    assert isinstance(document.state, TournamentState)
    updated = schedule_tables(record_result(document.state, "W1", 0)).state
    payload = json.loads(dumps_document(append_result(document, "W1", 0, updated)))
    if corruption == "winner":
        payload["history"][0]["winner_index"] = True
    elif corruption == "identity":
        payload["history"][0]["before"]["table_count"] = 3
    elif corruption == "transition":
        payload["current"] = payload["history"][0]["before"]
    else:
        payload["schema_version"] = 99
    with pytest.raises(ValueError):
        loads_document(json.dumps(payload))


def test_completed_snapshot_cannot_claim_empty_history() -> None:
    original = bracket_document()
    assert isinstance(original.state, TournamentState)
    completed = record_result(original.state, "W1", 0)
    with pytest.raises(ValueError):
        dumps_document(replace(original, state=completed))
