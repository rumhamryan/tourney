from pathlib import Path
from unittest.mock import patch

import pytest

from bracket_preview import build_preview
from tournament_state import MatchProgress, TournamentState
from tournament_storage import load_tournament, save_tournament


@pytest.fixture
def state() -> TournamentState:
    draw = build_preview(["Alice", "Alice", "李", "Dana"], "Single Elimination")
    return TournamentState(
        draw,
        tuple(reversed(draw.names)),
        2,
        progress=(
            MatchProgress("W1", "completed", winner_index=0),
            MatchProgress("W2", "in_progress", table_number=2),
        ),
        draw_locked=True,
    )


def test_save_and_load_file_round_trip(tmp_path: Path, state: TournamentState) -> None:
    path = tmp_path / "比赛.json"
    save_tournament(path, state)
    assert load_tournament(path) == state
    assert list(tmp_path.iterdir()) == [path]


def test_failed_replace_preserves_existing_file_and_cleans_temp(
    tmp_path: Path, state: TournamentState
) -> None:
    path = tmp_path / "tournament.json"
    path.write_text("previous save", encoding="utf-8")
    with (
        patch("tournament_storage.os.replace", side_effect=OSError("disk error")),
        pytest.raises(OSError, match="disk error"),
    ):
        save_tournament(path, state)
    assert path.read_text(encoding="utf-8") == "previous save"
    assert list(tmp_path.iterdir()) == [path]


def test_failed_flush_preserves_existing_file_and_cleans_temp(
    tmp_path: Path, state: TournamentState
) -> None:
    path = tmp_path / "tournament.json"
    path.write_text("previous save", encoding="utf-8")
    with (
        patch("tournament_storage.os.fsync", side_effect=OSError("disk full")),
        pytest.raises(OSError, match="disk full"),
    ):
        save_tournament(path, state)
    assert path.read_text(encoding="utf-8") == "previous save"
    assert list(tmp_path.iterdir()) == [path]


def test_loading_missing_file_reports_os_error(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        load_tournament(tmp_path / "missing.json")


def test_saving_to_missing_directory_reports_os_error(
    tmp_path: Path, state: TournamentState
) -> None:
    with pytest.raises(OSError):
        save_tournament(tmp_path / "missing" / "tournament.json", state)


def test_loading_bad_encoding_reports_value_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ValueError):
        load_tournament(path)
