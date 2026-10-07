"""Atomic tournament documents with validated, persistent result checkpoints."""

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import chip_storage
import tournament_storage
from chip_tournament import ChipTournament, _dispatch
from chip_tournament import champion_index as chip_champion
from chip_tournament import validate_tournament as validate_chip
from tournament_state import TournamentState, ready_matches, record_result, validate_tournament
from tournament_storage import (
    _integer,
    _invalid_constant,
    _list,
    _object,
    _save_contents,
    _string,
    _unique_object,
)

TournamentSnapshot = TournamentState | ChipTournament
_DOCUMENT_TYPE = "tourney-history"
_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ResultRecord:
    """One winner selection and the exact physical assignments before it."""

    match_id: str
    winner_index: int
    before: TournamentSnapshot


@dataclass(frozen=True)
class TournamentDocument:
    """Current play and its remaining undo stack, oldest checkpoint first."""

    state: TournamentSnapshot
    history: tuple[ResultRecord, ...] = ()


def _snapshot_payload(state: TournamentSnapshot) -> dict[str, Any]:
    contents = (
        tournament_storage.dumps_tournament(state)
        if isinstance(state, TournamentState)
        else chip_storage.dumps_tournament(state)
    )
    payload: dict[str, Any] = json.loads(contents)
    return payload


def _snapshot(value: object) -> TournamentSnapshot:
    if not isinstance(value, dict):
        raise ValueError("Expected a tournament snapshot.")
    contents = json.dumps(value, allow_nan=False)
    if value.get("format") == "Chip Tournament":
        return chip_storage.loads_tournament(contents)
    return tournament_storage.loads_tournament(contents)


def _validate_bracket_transition(
    record: ResultRecord, before: TournamentState, after: TournamentState
) -> None:
    expected = record_result(before, record.match_id, record.winner_index)
    if replace(after, progress=expected.progress) != expected:
        raise ValueError("History changes the tournament identity.")
    previous = {item.match_id: item for item in expected.progress}
    current = {item.match_id: item for item in after.progress}
    if any(current.get(identifier) != item for identifier, item in previous.items()):
        raise ValueError("History changes an unrelated result or table assignment.")
    assigned = [item for identifier, item in current.items() if identifier not in previous]
    eligible = {match.identifier for match in ready_matches(expected)}
    if any(item.status != "in_progress" or item.match_id not in eligible for item in assigned):
        raise ValueError("History contains an invalid automatic assignment.")
    free = expected.table_count - sum(item.status == "in_progress" for item in expected.progress)
    if len(assigned) != min(free, len(eligible)):
        raise ValueError("History does not include the automatic table assignments.")


def _chip_result(record: ResultRecord, before: ChipTournament) -> ChipTournament:
    round_ = before.rounds[-1]
    match = next((match for match in round_.matches if match.identifier == record.match_id), None)
    if match is None or match.table_number is None or match.winner_index is not None:
        raise ValueError("History must record an active match.")
    if type(record.winner_index) is not int or record.winner_index not in match.players:
        raise ValueError("History contains an invalid winner.")
    loser = next(player for player in match.players if player != record.winner_index)
    players = tuple(
        replace(player, chips=player.chips - 1) if index == loser else player
        for index, player in enumerate(before.players)
    )
    completed = replace(match, winner_index=record.winner_index, table_number=None)
    round_ = replace(
        round_, matches=tuple(completed if item == match else item for item in round_.matches)
    )
    return replace(before, players=players, rounds=(*before.rounds[:-1], round_))


def _validate_chip_transition(
    record: ResultRecord, before: ChipTournament, after: ChipTournament
) -> None:
    expected = _chip_result(record, before)
    new_round = chip_champion(expected) is None and all(
        match.winner_index is not None for match in expected.rounds[-1].matches
    )
    if not new_round:
        if after != _dispatch(expected):
            raise ValueError("History changes unrelated chip play.")
        return
    if len(after.rounds) != len(expected.rounds) + 1 or after.rounds[:-1] != expected.rounds:
        raise ValueError("History must retain completed rounds and add exactly one round.")
    bye = after.rounds[-1].bye_index
    players = tuple(
        replace(player, byes=player.byes + 1) if index == bye else player
        for index, player in enumerate(expected.players)
    )
    if after.players != players or after.table_count != before.table_count:
        raise ValueError("History changes chip counts or tournament identity.")
    if any(match.winner_index is not None for match in after.rounds[-1].matches):
        raise ValueError("A generated round cannot already contain results.")
    unassigned = replace(
        after,
        rounds=(
            *after.rounds[:-1],
            replace(
                after.rounds[-1],
                matches=tuple(
                    replace(match, table_number=None) for match in after.rounds[-1].matches
                ),
            ),
        ),
    )
    if after != _dispatch(unassigned):
        raise ValueError("History contains invalid chip table assignments.")


def _validate_transition(record: ResultRecord, after: TournamentSnapshot) -> None:
    if isinstance(record.before, TournamentState) and isinstance(after, TournamentState):
        _validate_bracket_transition(record, record.before, after)
    elif isinstance(record.before, ChipTournament) and isinstance(after, ChipTournament):
        _validate_chip_transition(record, record.before, after)
    else:
        raise ValueError("History cannot change tournament formats.")


def validate_document(document: TournamentDocument) -> None:
    """Check every snapshot and result transition without scheduling or random draws."""
    snapshots = (*[record.before for record in document.history], document.state)
    for state in snapshots:
        if isinstance(state, TournamentState):
            validate_tournament(state)
        else:
            validate_chip(state)
    initial = snapshots[0]
    if isinstance(initial, TournamentState):
        completed = any(item.status == "completed" for item in initial.progress)
    else:
        completed = len(initial.rounds) != 1 or any(
            match.winner_index is not None for match in initial.rounds[0].matches
        )
    if completed:
        raise ValueError("A tournament document must retain history for every result.")
    for record, after in zip(document.history, snapshots[1:], strict=True):
        _validate_transition(record, after)


def append_result(
    document: TournamentDocument, match_id: str, winner_index: int, updated: TournamentSnapshot
) -> TournamentDocument:
    """Append a checkpoint after result recording and automatic dispatch have succeeded."""
    candidate = TournamentDocument(
        updated, (*document.history, ResultRecord(match_id, winner_index, document.state))
    )
    validate_document(candidate)
    return candidate


def undo_result(document: TournamentDocument) -> TournamentDocument:
    """Restore the latest checkpoint, including its original table assignments."""
    validate_document(document)
    if not document.history:
        raise ValueError("No result is available to undo.")
    return TournamentDocument(document.history[-1].before, document.history[:-1])


def dumps_document(document: TournamentDocument) -> str:
    """Encode the complete current tournament and persistent undo stack."""
    validate_document(document)
    payload = {
        "document_type": _DOCUMENT_TYPE,
        "schema_version": _SCHEMA_VERSION,
        "current": _snapshot_payload(document.state),
        "history": [
            {
                "match_id": record.match_id,
                "winner_index": record.winner_index,
                "before": _snapshot_payload(record.before),
            }
            for record in document.history
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _record(value: object) -> ResultRecord:
    item = _object(value, {"match_id", "winner_index", "before"})
    return ResultRecord(
        _string(item["match_id"]), _integer(item["winner_index"]), _snapshot(item["before"])
    )


def _decode(contents: str) -> Any:
    try:
        return json.loads(
            contents, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("This is not a valid tournament JSON file.") from error


def loads_document(contents: str) -> TournamentDocument:
    """Load a history document, rejecting unsupported versions and corrupt checkpoints."""
    item = _object(_decode(contents), {"document_type", "schema_version", "current", "history"})
    if (
        item["document_type"] != _DOCUMENT_TYPE
        or _integer(item["schema_version"]) != _SCHEMA_VERSION
    ):
        raise ValueError("Unsupported tournament document version or type.")
    document = TournamentDocument(
        _snapshot(item["current"]), tuple(_record(value) for value in _list(item["history"]))
    )
    validate_document(document)
    return document


def load_document(path: Path) -> TournamentDocument:
    """Read a tournament file with its full undo history."""
    return loads_document(path.read_text(encoding="utf-8"))


def read_tournament_file(path: Path) -> TournamentDocument | TournamentSnapshot:
    """Read new documents or legacy snapshots; legacy snapshots are for viewing only."""
    contents = path.read_text(encoding="utf-8")
    value = _decode(contents)
    if isinstance(value, dict) and "document_type" in value:
        return loads_document(contents)
    return _snapshot(value)


def save_document(path: Path, document: TournamentDocument) -> None:
    """Atomically save; a failed write preserves the previous tournament file."""
    _save_contents(path, dumps_document(document))
