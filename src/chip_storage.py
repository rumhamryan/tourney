"""Versioned chip snapshots, retaining random draws and their full result history."""

import json
from dataclasses import asdict
from pathlib import Path

from chip_tournament import ChipMatch, ChipPlayer, ChipRound, ChipTournament, validate_tournament
from tournament_storage import (
    _integer,
    _invalid_constant,
    _list,
    _object,
    _optional_integer,
    _save_contents,
    _string,
    _unique_object,
)

_SCHEMA_VERSION = 1
_MATCH_PLAYERS = 2


def _player(value: object) -> ChipPlayer:
    item = _object(value, {"name", "starting_chips", "chips", "byes"})
    return ChipPlayer(
        _string(item["name"]),
        _integer(item["starting_chips"]),
        _integer(item["chips"]),
        _integer(item["byes"]),
    )


def _match(value: object) -> ChipMatch:
    item = _object(value, {"identifier", "players", "table_number", "winner_index"})
    players = _list(item["players"])
    if len(players) != _MATCH_PLAYERS:
        raise ValueError("Each matchup must contain two players.")
    return ChipMatch(
        _string(item["identifier"]),
        (_integer(players[0]), _integer(players[1])),
        _optional_integer(item["table_number"]),
        _optional_integer(item["winner_index"]),
    )


def _round(value: object) -> ChipRound:
    item = _object(value, {"number", "matches", "bye_index"})
    return ChipRound(
        _integer(item["number"]),
        tuple(_match(match) for match in _list(item["matches"])),
        _optional_integer(item["bye_index"]),
    )


def dumps_tournament(state: ChipTournament) -> str:
    """Serialize a complete validated chip tournament in readable Unicode JSON."""
    validate_tournament(state)
    payload = {"schema_version": _SCHEMA_VERSION, "format": "Chip Tournament", **asdict(state)}
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def loads_tournament(contents: str) -> ChipTournament:
    """Restore chip counts, rounds, byes, and tables without redrawing the round."""
    try:
        value = json.loads(
            contents, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("This is not a valid tournament JSON file.") from error
    item = _object(value, {"schema_version", "format", "players", "table_count", "rounds"})
    if _integer(item["schema_version"]) != _SCHEMA_VERSION or item["format"] != "Chip Tournament":
        raise ValueError("Unsupported chip tournament file version or format.")
    state = ChipTournament(
        tuple(_player(player) for player in _list(item["players"])),
        _integer(item["table_count"]),
        tuple(_round(round_) for round_ in _list(item["rounds"])),
    )
    validate_tournament(state)
    return state


def save_tournament(path: Path, state: ChipTournament) -> None:
    """Atomically save a chip snapshot; a failed write leaves the old file intact."""
    _save_contents(path, dumps_tournament(state))


def load_tournament(path: Path) -> ChipTournament:
    """Read and validate a chip snapshot without changing application state."""
    return loads_tournament(path.read_text(encoding="utf-8"))
