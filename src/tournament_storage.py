"""Versioned UTF-8 JSON snapshots and atomic tournament-file writes."""

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from bracket_preview import Draw, PreviewMatch, Source
from tournament_state import MatchProgress, TableLabel, TournamentState, validate_tournament

_SCHEMA_VERSION = 1
_MATCH_SLOTS = 2


def _object(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("The tournament file contains missing or unsupported fields.")
    return value


def _list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("Expected a list in the tournament file.")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected text in the tournament file.")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("Expected a whole number in the tournament file.")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("Expected true or false in the tournament file.")
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _source(value: object) -> Source:
    item = _object(value, {"player_index", "match_id", "loser"})
    return Source(
        _optional_integer(item["player_index"]),
        None if item["match_id"] is None else _string(item["match_id"]),
        _boolean(item["loser"]),
    )


def _match(value: object) -> PreviewMatch:
    item = _object(value, {"identifier", "section", "round_number", "slots", "conditional"})
    slots = _list(item["slots"])
    if len(slots) != _MATCH_SLOTS:
        raise ValueError("Each match must have exactly two slots.")
    return PreviewMatch(
        _string(item["identifier"]),
        _string(item["section"]),
        _integer(item["round_number"]),
        (_source(slots[0]), _source(slots[1])),
        _boolean(item["conditional"]),
    )


def _draw(value: object) -> Draw:
    item = _object(value, {"names", "tournament_format", "matches"})
    return Draw(
        tuple(_string(name) for name in _list(item["names"])),
        _string(item["tournament_format"]),
        tuple(_match(match) for match in _list(item["matches"])),
    )


def _progress(value: object) -> MatchProgress:
    item = _object(value, {"match_id", "status", "winner_index", "table_number"})
    return MatchProgress(
        _string(item["match_id"]),
        _string(item["status"]),
        _optional_integer(item["winner_index"]),
        _optional_integer(item["table_number"]),
    )


def _table_label(value: object) -> TableLabel:
    item = _object(value, {"number", "label"})
    return TableLabel(_integer(item["number"]), _string(item["label"]))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate fields are not allowed in a tournament file.")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON number: {value}")


def dumps_tournament(state: TournamentState) -> str:
    """Serialize a validated, complete snapshot as readable Unicode JSON."""
    validate_tournament(state)
    payload = {"schema_version": _SCHEMA_VERSION, **asdict(state)}
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def loads_tournament(contents: str) -> TournamentState:
    """Restore an exact snapshot, rejecting malformed or unsupported files.

    Schema 1 stores the entire match graph. Its validation uses the current
    bracket rules; changing those rules requires a schema migration.
    """
    try:
        value = json.loads(
            contents, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("This is not a valid tournament JSON file.") from error
    if not isinstance(value, dict) or _integer(value.get("schema_version")) != _SCHEMA_VERSION:
        raise ValueError("Unsupported tournament file version.")
    item = _object(
        value,
        {
            "schema_version",
            "draw",
            "entry_names",
            "table_count",
            "progress",
            "table_labels",
            "draw_locked",
        },
    )
    state = TournamentState(
        _draw(item["draw"]),
        tuple(_string(name) for name in _list(item["entry_names"])),
        _integer(item["table_count"]),
        tuple(_progress(match) for match in _list(item["progress"])),
        tuple(_table_label(table) for table in _list(item["table_labels"])),
        _boolean(item["draw_locked"]),
    )
    validate_tournament(state)
    return state


def save_tournament(path: Path, state: TournamentState) -> None:
    """Atomically replace a JSON save; failed writes keep the previous file.

    The temporary file lives beside the destination so replacement stays
    on the same filesystem. The file is flushed to disk before replacement.
    I/O errors propagate to the caller, and temporary files are removed.
    """
    _save_contents(path, dumps_tournament(state))


def _save_contents(path: Path, contents: str) -> None:
    """Share the same atomic file replacement for bracket and chip snapshots."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=".tourney-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_tournament(path: Path) -> TournamentState:
    """Read and validate a UTF-8 JSON save without changing application state."""
    return loads_tournament(path.read_text(encoding="utf-8"))
