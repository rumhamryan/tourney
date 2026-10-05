import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any

import pytest

from bracket_preview import Draw, Source, build_preview
from tournament_state import MatchProgress, TableLabel, TournamentState
from tournament_storage import dumps_tournament, loads_tournament


@pytest.fixture
def state() -> TournamentState:
    draw = build_preview(["Zoë", "李", "Zoë", "Dana"], "Double Elimination")
    return TournamentState(
        draw,
        tuple(reversed(draw.names)),
        3,
        progress=(
            MatchProgress("W1", "completed", winner_index=1),
            MatchProgress("W2", "in_progress", table_number=2),
        ),
        table_labels=(TableLabel(2, "TV · 台"),),
        draw_locked=True,
    )


def test_json_round_trip_preserves_every_parameter(state: TournamentState) -> None:
    contents = dumps_tournament(state)
    payload = json.loads(contents)
    assert payload["schema_version"] == 1
    assert "Zoë" in contents and "李" in contents
    assert loads_tournament(contents) == state
    assert loads_tournament(contents).draw.matches == state.draw.matches


@pytest.mark.parametrize("count", range(2, 33))
@pytest.mark.parametrize("tournament_format", ["Single Elimination", "Double Elimination"])
def test_round_trip_before_play_for_all_sizes(count: int, tournament_format: str) -> None:
    draw = build_preview([f"Player {i}" for i in range(count)], tournament_format)
    original = TournamentState(draw, draw.names, 1)
    assert loads_tournament(dumps_tournament(original)) == original


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "{",
        "[]",
        "null",
        '{"schema_version": 99}',
        '{"schema_version": 1, "schema_version": 1}',
        '{"table_count": NaN}',
    ],
)
def test_rejects_malformed_or_unsupported_files(contents: str) -> None:
    with pytest.raises(ValueError):
        loads_tournament(contents)


@pytest.mark.parametrize(
    "key, value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("table_count", "3"),
        ("table_count", 1.5),
        ("draw_locked", "true"),
        ("entry_names", ["different"]),
        ("progress", [{}]),
        ("progress", {}),
        ("table_labels", None),
        ("table_labels", [{"number": 1, "label": 123}]),
    ],
)
def test_rejects_bad_parameter_types(state: TournamentState, key: str, value: object) -> None:
    payload: dict[str, Any] = json.loads(dumps_tournament(state))
    payload[key] = value
    with pytest.raises(ValueError):
        loads_tournament(json.dumps(payload))


@pytest.mark.parametrize(
    "change",
    [
        "missing_field",
        "unknown_field",
        "blank_name",
        "non_string_name",
        "bad_format",
        "missing_match",
        "duplicate_match",
        "dangling_source",
        "wrong_player",
        "forward_source",
        "boolean_player",
        "bad_round",
        "bad_conditional",
        "bad_slots",
    ],
)
def test_rejects_invalid_bracket_structure(state: TournamentState, change: str) -> None:
    payload: dict[str, Any] = json.loads(dumps_tournament(state))
    draw = payload["draw"]
    actions: dict[str, Callable[[], object]] = {
        "missing_field": lambda: payload.pop("draw"),
        "unknown_field": lambda: payload.update(future_parameter=True),
        "blank_name": lambda: draw["names"].__setitem__(0, " "),
        "non_string_name": lambda: draw["names"].__setitem__(0, 123),
        "bad_format": lambda: draw.__setitem__("tournament_format", "Unknown"),
        "missing_match": lambda: draw["matches"].pop(),
        "duplicate_match": lambda: draw["matches"].append(draw["matches"][0]),
        "dangling_source": lambda: draw["matches"][2]["slots"][0].update(match_id="missing"),
        "wrong_player": lambda: draw["matches"][0]["slots"][0].update(player_index=9),
        "forward_source": lambda: draw["matches"][2]["slots"][0].update(match_id="GF"),
        "boolean_player": lambda: draw["matches"][0]["slots"][0].update(player_index=True),
        "bad_round": lambda: draw["matches"][0].update(round_number=True),
        "bad_conditional": lambda: draw["matches"][0].update(conditional="false"),
        "bad_slots": lambda: draw["matches"][0]["slots"].pop(),
    }
    actions[change]()
    with pytest.raises(ValueError):
        loads_tournament(json.dumps(payload))


def test_invalid_state_is_not_serialized(state: TournamentState) -> None:
    with pytest.raises(ValueError):
        dumps_tournament(replace(state, table_count=0))


def _player(source: Source, results: dict[str, tuple[int | None, int | None]]) -> int | None:
    return results[source.match_id][int(source.loser)] if source.match_id else source.player_index


def _snapshots(draw: Draw, lower_wins: bool) -> Iterator[TournamentState]:
    progress: list[MatchProgress] = []
    results: dict[str, tuple[int | None, int | None]] = {}
    yield TournamentState(draw, draw.names, 2)
    for match in draw.matches:
        if match.conditional and not lower_wins:
            continue
        players = [_player(source, results) for source in match.slots]
        present = [player for player in players if player is not None]
        if len(present) < len(match.slots):
            results[match.identifier] = (present[0] if present else None, None)
            continue
        winner_slot = int(match.identifier == "GF" and lower_wins)
        active = MatchProgress(match.identifier, "in_progress", table_number=2)
        yield TournamentState(draw, draw.names, 2, (*progress, active), draw_locked=True)
        winner, loser = present[winner_slot], present[1 - winner_slot]
        progress.append(MatchProgress(match.identifier, "completed", winner_index=winner))
        results[match.identifier] = (winner, loser)
        yield TournamentState(draw, draw.names, 2, tuple(progress), draw_locked=True)


@pytest.mark.parametrize("count", [2, 3, 5, 8, 32])
@pytest.mark.parametrize(
    "tournament_format, lower_wins",
    [("Single Elimination", False), ("Double Elimination", False), ("Double Elimination", True)],
)
def test_round_trip_at_every_point_in_tournament(
    count: int, tournament_format: str, lower_wins: bool
) -> None:
    draw = build_preview(["Repeated name"] * count, tournament_format)
    for snapshot in _snapshots(draw, lower_wins):
        assert loads_tournament(dumps_tournament(snapshot)) == snapshot
