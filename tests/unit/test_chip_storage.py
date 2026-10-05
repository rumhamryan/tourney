import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from chip_storage import dumps_tournament, load_tournament, loads_tournament, save_tournament
from chip_tournament import champion_index, record_result, start_tournament


@pytest.mark.parametrize("players", [2, 3, 5, 32])
def test_round_trip_preserves_every_round_result_and_assignment(players: int) -> None:
    state = start_tournament(["Zoë 李"] * players, [2] * players, 3)
    while True:
        contents = dumps_tournament(state)
        assert loads_tournament(contents) == state
        assert "Zoë 李" in contents
        if champion_index(state) is not None:
            break
        match = next(match for match in state.rounds[-1].matches if match.table_number is not None)
        state = record_result(state, match.identifier, match.players[0])


@pytest.mark.parametrize(
    "contents",
    ["", "{", "[]", "null", '{"schema_version":1,"schema_version":1}', '{"schema_version":NaN}'],
)
def test_malformed_files_are_rejected(contents: str) -> None:
    with pytest.raises(ValueError):
        loads_tournament(contents)


@pytest.mark.parametrize(
    "field, value",
    [
        ("schema_version", 99),
        ("schema_version", True),
        ("format", "Single Elimination"),
        ("players", "AB"),
        ("rounds", []),
        ("table_count", 0),
        ("table_count", True),
    ],
)
def test_invalid_snapshot_fields_are_rejected(field: str, value: object) -> None:
    state = start_tournament(["A", "B"], [2, 2], 1)
    payload = json.loads(dumps_tournament(state))
    payload[field] = value
    with pytest.raises(ValueError):
        loads_tournament(json.dumps(payload))


def test_inconsistent_result_and_unknown_fields_are_rejected() -> None:
    state = start_tournament(["A", "B"], [2, 2], 1)
    payload = json.loads(dumps_tournament(state))
    payload["players"][0]["chips"] = 1
    with pytest.raises(ValueError):
        loads_tournament(json.dumps(payload))
    payload["players"][0]["chips"] = 2
    payload["rounds"][0]["matches"][0]["extra"] = "unsupported"
    with pytest.raises(ValueError):
        loads_tournament(json.dumps(payload))


def test_file_io_uses_validated_json_and_atomic_writer() -> None:
    state = start_tournament(["A", "B"], [2, 2], 1)
    path = Path("chip.json")
    with patch("chip_storage._save_contents") as writer:
        save_tournament(path, state)
    writer.assert_called_once_with(path, dumps_tournament(state))
    with patch.object(Path, "read_text", return_value=dumps_tournament(state)):
        assert load_tournament(path) == state


@pytest.mark.parametrize(
    "field, value",
    [
        ("players", [0]),
        ("players", [0, 0]),
        ("players", [0, True]),
        ("players", [0, 32]),
        ("table_number", True),
        ("table_number", 0),
        ("table_number", 2),
        ("winner_index", True),
        ("winner_index", 2),
        ("winner_index", 0),
    ],
)
def test_invalid_match_participants_results_and_tables_are_rejected(
    field: str, value: object
) -> None:
    payload = json.loads(dumps_tournament(start_tournament(["A", "B"], [2, 2], 1)))
    payload["rounds"][0]["matches"][0][field] = value
    with pytest.raises(ValueError):
        loads_tournament(json.dumps(payload))


def test_two_active_matches_cannot_share_a_table() -> None:
    payload = json.loads(dumps_tournament(start_tournament(["Same"] * 4, [2] * 4, 2)))
    payload["rounds"][0]["matches"][1]["table_number"] = 1
    with pytest.raises(ValueError, match="distinct"):
        loads_tournament(json.dumps(payload))


def test_incomplete_round_cannot_be_followed_by_another_round() -> None:
    payload = json.loads(dumps_tournament(start_tournament(["A", "B"], [2, 2], 1)))
    next_round = {
        "number": 2,
        "bye_index": None,
        "matches": [
            {"identifier": "R2M1", "players": [0, 1], "table_number": 1, "winner_index": None}
        ],
    }
    payload["rounds"].append(next_round)
    with pytest.raises(ValueError, match="previous matches finish"):
        loads_tournament(json.dumps(payload))


def test_invalid_state_cannot_be_saved_or_serialized() -> None:
    payload = start_tournament(["A", "B"], [2, 2], 1)
    state = replace(payload, players=(replace(payload.players[0], chips=1), payload.players[1]))
    with pytest.raises(ValueError):
        dumps_tournament(state)
    with patch("chip_storage._save_contents") as writer, pytest.raises(ValueError):
        save_tournament(Path("chip.json"), state)
    writer.assert_not_called()


def test_file_read_errors_propagate_without_a_snapshot() -> None:
    with (
        patch.object(Path, "read_text", side_effect=OSError("read failed")),
        pytest.raises(OSError),
    ):
        load_tournament(Path("chip.json"))
