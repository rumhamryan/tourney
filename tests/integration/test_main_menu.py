from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QGraphicsTextItem,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
)

from bracket_preview import build_preview
from bracket_view import _ResultDialog
from chip_storage import save_tournament as save_chip_tournament
from chip_tournament import record_result as record_chip_result
from chip_view import _ResultDialog as _ChipResultDialog
from main_menu import MainMenu, main
from player_entry import PlayerEntry
from tournament_file import TournamentDocument, read_tournament_file
from tournament_state import MatchProgress, TableLabel, TournamentState
from tournament_storage import save_tournament
from ui_metrics import REFERENCE_WIDTH

_PLAYER_LIMIT = 32


@pytest.fixture(scope="session")
def application() -> Iterator[QApplication]:
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        assert isinstance(app, QApplication)
        app.setQuitOnLastWindowClosed(False)
        yield app


@pytest.fixture
def menu(application: QApplication, tmp_path: Path) -> Iterator[MainMenu]:
    window = MainMenu()
    window.show()
    window.activateWindow()
    application.processEvents()
    paths = (tmp_path / f"tournament-{index}.json" for index in range(100))
    with (
        patch(
            "main_menu.QFileDialog.getSaveFileName",
            side_effect=lambda *args, **kwargs: (str(next(paths)), ""),
        ),
        patch("main_menu.MainMenu._confirm_action", return_value=QMessageBox.StandardButton.Yes),
    ):
        yield window
    window.close()
    _wait_workers(window)
    window.deleteLater()
    application.processEvents()


def load_tournament(path: Path) -> TournamentState:
    loaded = read_tournament_file(path)
    state = loaded.state if isinstance(loaded, TournamentDocument) else loaded
    assert isinstance(state, TournamentState)
    return state


@pytest.fixture
def entry(menu: MainMenu) -> PlayerEntry:
    menu.single_button.click()
    return menu.player_entry


@pytest.fixture
def chip_entry(menu: MainMenu) -> PlayerEntry:
    menu.chip_button.click()
    return menu.player_entry


@pytest.fixture
def start_requests(entry: PlayerEntry) -> list[tuple[str, list[str], int]]:
    requests: list[tuple[str, list[str], int]] = []
    entry.start_requested.connect(
        lambda tournament_format, names, table_count: requests.append(
            (tournament_format, names, table_count)
        )
    )
    return requests


def _wait_scheduling(menu: MainMenu) -> None:
    for _ in range(300):
        QApplication.processEvents()
        if not menu.bracket_view.scheduling:
            return
        QTest.qWait(10)
    pytest.fail("Scheduling did not complete")


def _wait_workers(menu: MainMenu) -> None:
    for _ in range(300):
        QApplication.processEvents()
        if not menu._scheduling_threads:
            return
        QTest.qWait(10)
    pytest.fail("Scheduling workers did not finish")


def _start_players(entry: PlayerEntry, names: list[str]) -> None:
    for name in names:
        entry.name_input.setText(name)
        entry.add_button.click()
    with patch("main_menu.shuffle_names", side_effect=lambda players: players):
        entry.start_button.click()


def _click_match(menu: MainMenu, match_id: str = "W1") -> None:
    view = menu.bracket_view
    rectangle = view.match_rects[match_id]
    view.graphics.ensureVisible(rectangle)
    point = view.graphics.mapFromScene(rectangle.center())
    QTest.mouseClick(view.graphics.viewport(), Qt.MouseButton.LeftButton, pos=point)


def _start_chip_players(entry: PlayerEntry, chips: list[int], tables: int = 1) -> None:
    entry.table_count_input.setValue(tables)
    for index, count in enumerate(chips):
        entry.name_input.setText(f"Player {index + 1}")
        entry.chip_count_input.setText(str(count))
        entry.add_button.click()
    with patch("chip_tournament.shuffle"):
        entry.start_button.click()
    QApplication.processEvents()


def _choose_chip_winner(menu: MainMenu, identifier: str, position: int = 0) -> None:
    def choose() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, _ChipResultDialog)
        dialog.winner_buttons[position].click()

    QTimer.singleShot(0, choose)
    with patch("chip_tournament.shuffle"):
        menu.chip_view.match_cards[identifier].click()
    QApplication.processEvents()


def test_chip_round_barrier_removes_cards_and_refills_free_tables(
    menu: MainMenu, chip_entry: PlayerEntry
) -> None:
    _start_chip_players(chip_entry, [1] * 6, 2)
    view = menu.chip_view
    assert not view.match_cards["R1M3"].isEnabled()
    _choose_chip_winner(menu, "R1M1")
    assert set(view.match_cards) == {"R1M2", "R1M3"}
    state = menu.chip_tournament
    assert state is not None and len(state.rounds) == 1
    assert [match.table_number for match in state.rounds[-1].matches] == [None, 2, 1]
    assert state.players[0].chips == 1 and state.players[1].chips == 0
    eliminated = view.leaderboard.topLevelItem(5)
    assert eliminated is not None
    assert eliminated.data(0, Qt.ItemDataRole.UserRole) == 1
    assert "Eliminated" in eliminated.toolTip(0)
    assert eliminated.text(0) == "Player 2 · Eliminated"
    _choose_chip_winner(menu, "R1M2")
    assert set(view.match_cards) == {"R1M3"}
    _choose_chip_winner(menu, "R1M3")
    assert set(view.match_cards) == {"R2M1"}
    assert menu.chip_tournament is not None
    assert [round_.number for round_ in menu.chip_tournament.rounds] == [1, 2]
    assert view.bye_label.text().startswith("Bye this round:")


def test_chip_last_survivor_displays_champion_and_empty_grid(
    menu: MainMenu, chip_entry: PlayerEntry
) -> None:
    _start_chip_players(chip_entry, [2, 1], 6)
    _choose_chip_winner(menu, "R1M1")
    assert not menu.chip_view.match_cards
    assert menu.chip_view.status_label.text() == "Champion: Player 1"
    assert menu.chip_tournament is not None
    assert [player.chips for player in menu.chip_tournament.players] == [2, 0]


def test_chip_dialog_has_only_two_winner_buttons_and_cancel_preserves_state(
    menu: MainMenu, chip_entry: PlayerEntry
) -> None:
    _start_chip_players(chip_entry, [2, 2])
    original = menu.chip_tournament
    contents: list[tuple[list[str], list[str]]] = []

    def cancel() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, _ChipResultDialog)
        contents.append(
            (
                [label.text() for label in dialog.findChildren(QLabel)],
                [button.text() for button in dialog.findChildren(QPushButton)],
            )
        )
        QTest.keyClick(dialog, Qt.Key.Key_Escape)

    QTimer.singleShot(0, cancel)
    menu.chip_view.match_cards["R1M1"].click()
    assert contents == [(["Select the winner."], ["Player 1", "Player 2"])]
    assert menu.chip_tournament is original


def test_chip_match_and_winner_support_keyboard(menu: MainMenu, chip_entry: PlayerEntry) -> None:
    _start_chip_players(chip_entry, [1, 1])
    card = menu.chip_view.match_cards["R1M1"]
    card.setFocus()
    QApplication.processEvents()

    def choose() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, _ChipResultDialog)
        dialog.activateWindow()
        QApplication.processEvents()
        dialog.winner_buttons[1].setFocus()
        QTest.keyClick(dialog.winner_buttons[1], Qt.Key.Key_Return)

    QTimer.singleShot(0, choose)
    QTest.keyClick(card, Qt.Key.Key_Return)
    assert menu.chip_view.status_label.text() == "Champion: Player 2"


def test_chip_pending_matches_cannot_record_results(
    menu: MainMenu, chip_entry: PlayerEntry
) -> None:
    _start_chip_players(chip_entry, [2] * 4)
    original = menu.chip_tournament
    with patch("chip_view._ResultDialog") as dialog:
        menu.chip_view.match_cards["R1M2"].click()
        menu.chip_view._open_result("R1M2")
        menu.chip_view._open_result("unknown")
    dialog.assert_not_called()
    assert menu.chip_tournament is original
    with patch("main_menu.MainMenu._show_warning") as warning:
        menu._record_chip_result("R1M2", 2)
    warning.assert_called_once()
    assert menu.chip_tournament is original


def test_chip_missing_counts_can_be_updated_without_duplicating_players(
    menu: MainMenu, entry: PlayerEntry
) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.back_button.click()
    menu.chip_button.click()
    assert not entry.start_button.isEnabled()
    for row, count in enumerate([2, 3]):
        item = entry.player_list.item(row)
        assert item is not None
        entry.player_list.itemClicked.emit(item)
        assert entry.chip_count_input.text() == ""
        entry.chip_count_input.setText(str(count))
        entry.add_button.click()
    assert entry.player_names() == ["Alice", "Bob"]
    assert entry.player_chip_counts() == [2, 3]
    assert entry.start_button.isEnabled()
    entry.start_button.click()
    assert menu.chip_tournament is not None


def test_chip_registered_counts_can_be_changed_in_place(
    menu: MainMenu, chip_entry: PlayerEntry
) -> None:
    _start_chip_players(chip_entry, [2, 3])
    menu.chip_view.back_button.click()
    menu.chip_button.click()
    item = chip_entry.player_list.item(0)
    assert item is not None
    chip_entry.player_list.itemActivated.emit(item)
    assert chip_entry.name_input.text() == "Player 1"
    assert chip_entry.chip_count_input.text() == "2"
    chip_entry.name_input.setText("Alice")
    chip_entry.chip_count_input.setText("5")
    chip_entry.add_button.click()
    assert chip_entry.player_names() == ["Alice", "Player 2"]
    assert chip_entry.player_chip_counts() == [5, 3]


@pytest.mark.parametrize("width, height", [(640, 600), (900, 700), (1920, 1080)])
def test_chip_leaderboard_and_match_grid_fit_resized_window(
    menu: MainMenu, chip_entry: PlayerEntry, width: int, height: int
) -> None:
    menu.resize(width, height)
    _start_chip_players(chip_entry, [3] * 32, 16)
    view = menu.chip_view
    assert menu.width() == width and menu.height() == height
    matchup_pane = view.splitter.widget(1)
    assert matchup_pane is not None
    assert view.leaderboard_pane.x() < matchup_pane.x()
    assert view.match_scroll.horizontalScrollBar().maximum() == 0
    cards = list(view.match_cards.values())
    assert cards[0].player_labels[0].font().pointSizeF() == view.font().pointSizeF()
    assert len({card.height() for card in cards}) == 1
    assert max(card.width() for card in cards) - min(card.width() for card in cards) <= 1
    first = view._grid.itemAtPosition(0, 0)
    row, column = (0, 1) if view._columns > 1 else (1, 0)
    second = view._grid.itemAtPosition(row, column)
    assert first is not None and first.widget() is cards[0]
    assert second is not None and second.widget() is cards[1]
    if width == REFERENCE_WIDTH:
        assert view._columns > 1


def test_chip_long_and_duplicate_names_keep_full_identity(
    menu: MainMenu, chip_entry: PlayerEntry
) -> None:
    name = "Zoë & 李 <player> " * 30
    for count in [2, 3]:
        chip_entry.name_input.setText(name)
        chip_entry.chip_count_input.setText(str(count))
        chip_entry.add_button.click()
    chip_entry.start_button.click()
    QApplication.processEvents()
    card = menu.chip_view.match_cards["R1M1"]
    assert all(label.toolTip() == name.strip() for label in card.player_labels)
    assert all(len(label.text()) < len(name) for label in card.player_labels)
    seen: list[str] = []

    def choose() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, _ChipResultDialog)
        seen.extend(button.accessibleName() for button in dialog.winner_buttons)
        dialog.winner_buttons[0].click()

    QTimer.singleShot(0, choose)
    card.click()
    assert seen == [f"Top player: {name.strip()}", f"Bottom player: {name.strip()}"]
    assert menu.chip_view.match_scroll.horizontalScrollBar().maximum() == 0


def test_chip_save_and_load_resume_partial_round_without_redrawing(
    menu: MainMenu, chip_entry: PlayerEntry, tmp_path: Path
) -> None:
    _start_chip_players(chip_entry, [3] * 5, 1)
    _choose_chip_winner(menu, "R1M1")
    original = menu.chip_tournament
    path = tmp_path / "chips.json"
    with patch("main_menu.QFileDialog.getSaveFileName", return_value=(str(path), "")):
        menu.chip_view.save_button.click()
    loaded = read_tournament_file(path)
    assert isinstance(loaded, TournamentDocument)
    assert loaded.state == original
    menu.chip_view.back_button.click()
    with (
        patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(path), "")),
        patch("chip_tournament.shuffle") as shuffle,
    ):
        menu.load_button.click()
    shuffle.assert_not_called()
    assert menu.chip_tournament == original
    assert menu.pages.currentWidget() is menu.chip_view
    assert set(menu.chip_view.match_cards) == {"R1M2"}
    assert menu.player_entry.player_chip_counts() == [3] * 5


def test_chip_champion_save_load_keeps_champion_visible(
    menu: MainMenu, chip_entry: PlayerEntry, tmp_path: Path
) -> None:
    _start_chip_players(chip_entry, [1, 1])
    state = menu.chip_tournament
    assert state is not None
    state = record_chip_result(state, "R1M1", 0)
    path = tmp_path / "champion.json"
    save_chip_tournament(path, state)
    with patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(path), "")):
        menu._load_tournament()
    assert menu.chip_view.status_label.text() == "Champion: Player 1"
    assert not menu.chip_view.match_cards


def test_chip_bad_load_and_failed_save_preserve_current_tournament(
    menu: MainMenu, chip_entry: PlayerEntry, tmp_path: Path
) -> None:
    _start_chip_players(chip_entry, [2, 2])
    original = menu.chip_tournament
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")
    with (
        patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(path), "")),
        patch("main_menu.MainMenu._show_warning") as warning,
    ):
        menu._load_tournament()
    warning.assert_called_once()
    assert menu.chip_tournament is original
    with (
        patch("main_menu.QFileDialog.getSaveFileName", return_value=(str(path), "")),
        patch("main_menu.save_document", side_effect=OSError("disk full")),
        patch("main_menu.MainMenu._confirm_action", return_value=QMessageBox.StandardButton.Yes),
        patch("main_menu.MainMenu._show_warning") as warning,
    ):
        menu._save_tournament()
    warning.assert_called_once()
    assert menu.chip_tournament is original
    assert path.read_text(encoding="utf-8") == "{}"


def test_start_assigns_tables_and_recording_winner_refills_them(
    menu: MainMenu, entry: PlayerEntry
) -> None:
    _start_players(entry, ["Alice", "Bob", "Carol", "Dana"])
    _wait_scheduling(menu)
    assert menu.tournament is not None and menu.tournament.draw_locked
    assert menu.tournament.progress == (MatchProgress("W1", "in_progress", table_number=1),)
    assert [button.text() for button in menu.bracket_view.findChildren(QPushButton)] == [
        "&Save As…",
        "&Undo Last Result",
        "&Back to Menu",
    ]

    def choose_winner() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, _ResultDialog)
        dialog.winner_buttons[1].click()

    QTimer.singleShot(0, choose_winner)
    _click_match(menu)
    _wait_scheduling(menu)
    assert menu.tournament.progress == (
        MatchProgress("W1", "completed", winner_index=1),
        MatchProgress("W2", "in_progress", table_number=1),
    )
    assert menu.bracket_view.back_button.text() == "&Back to Menu"


def test_result_dialog_cancel_preserves_snapshot(menu: MainMenu, entry: PlayerEntry) -> None:
    _start_players(entry, ["Alice", "Bob"])
    original = menu.tournament

    def cancel() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, _ResultDialog)
        dialog.reject()

    QTimer.singleShot(0, cancel)
    _click_match(menu)
    assert menu.tournament == original


@pytest.mark.parametrize("key", [Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_result_can_be_recorded_using_keyboard(
    menu: MainMenu, entry: PlayerEntry, key: Qt.Key
) -> None:
    _start_players(entry, ["Alice", "Bob"])
    focus_checks: list[bool] = []

    def choose_winner() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, _ResultDialog)
        dialog.activateWindow()
        QApplication.processEvents()
        dialog.winner_buttons[0].setFocus()
        QTest.keyClick(dialog.winner_buttons[0], Qt.Key.Key_Tab)
        focus_checks.append(dialog.winner_buttons[1].hasFocus())
        QTest.keyClick(dialog.winner_buttons[1], key)

    QTimer.singleShot(0, choose_winner)
    _click_match(menu)
    assert focus_checks == [True]
    assert menu.tournament is not None
    assert menu.tournament.progress == (MatchProgress("W1", "completed", winner_index=1),)


@pytest.mark.parametrize(
    "match_id, names, winner", [("W1", ["Alice", "Bob"], 1), ("W2", ["Carol", "Dana"], 3)]
)
def test_winner_dialog_has_only_two_player_buttons(
    menu: MainMenu, entry: PlayerEntry, match_id: str, names: list[str], winner: int
) -> None:
    entry.table_count_input.setValue(2)
    _start_players(entry, ["Alice", "Bob", "Carol", "Dana"])
    assert menu.tournament is not None
    dialog = _ResultDialog(menu.tournament, menu, match_id)
    assert [label.text() for label in dialog.findChildren(QLabel)] == ["Select the winner."]
    assert not dialog.findChildren(QComboBox)
    assert not dialog.findChildren(QRadioButton)
    assert dialog.findChildren(QPushButton) == dialog.winner_buttons
    assert [button.text() for button in dialog.winner_buttons] == names
    with pytest.raises(ValueError, match="Choose a winner"):
        dialog.selection()
    dialog.winner_buttons[1].click()
    assert dialog.selection() == (match_id, winner)
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.deleteLater()


def _result_dialog(menu: MainMenu, tournament_format: str) -> _ResultDialog | _ChipResultDialog:
    menu._select_format(tournament_format)
    if tournament_format == "Chip Tournament":
        _start_chip_players(menu.player_entry, [2, 2])
        assert menu.chip_tournament is not None
        state = menu.chip_tournament
        return _ChipResultDialog(state, state.rounds[0].matches[0], menu)
    _start_players(menu.player_entry, ["Alice", "Bob"])
    _wait_scheduling(menu)
    assert menu.tournament is not None
    return _ResultDialog(menu.tournament, menu)


@pytest.mark.parametrize("width, height", [(900, 700), (1920, 1080)])
@pytest.mark.parametrize(
    "tournament_format", ["Single Elimination", "Double Elimination", "Chip Tournament"]
)
def test_result_dialog_is_larger_and_player_text_fits(
    menu: MainMenu,
    application: QApplication,
    *,
    tournament_format: str,
    width: int,
    height: int,
) -> None:
    minimum_dialog_size = (720, 200)
    minimum_button_height = 72
    menu.resize(width, height)
    application.processEvents()
    reference = QDialog(menu)
    expected_font_size = reference.font().pointSizeF() * 1.5
    reference.deleteLater()
    dialog = _result_dialog(menu, tournament_format)
    try:
        dialog.show()
        application.processEvents()
        assert dialog.width() >= minimum_dialog_size[0]
        assert dialog.height() >= minimum_dialog_size[1]
        for button in dialog.winner_buttons:
            assert button.height() >= minimum_button_height
            assert button.font().pointSizeF() == pytest.approx(expected_font_size)
            assert button.fontMetrics().horizontalAdvance(button.text()) < button.width()
            assert button.fontMetrics().height() < button.height()
        prompt = dialog.findChildren(QLabel)[0]
        assert prompt.font().pointSizeF() == pytest.approx(expected_font_size)
    finally:
        dialog.close()
        dialog.deleteLater()


def test_recording_result_preserves_bracket_scroll(menu: MainMenu, entry: PlayerEntry) -> None:
    _start_players(entry, [f"Player {index}" for index in range(_PLAYER_LIMIT)])
    graphics = menu.bracket_view.graphics
    QApplication.processEvents()
    graphics.horizontalScrollBar().setValue(graphics.horizontalScrollBar().maximum())
    graphics.verticalScrollBar().setValue(graphics.verticalScrollBar().maximum())
    position = (graphics.horizontalScrollBar().value(), graphics.verticalScrollBar().value())
    assert position[0] > 0 and position[1] > 0
    menu._record_result("W1", 0)
    assert (
        graphics.horizontalScrollBar().value(),
        graphics.verticalScrollBar().value(),
    ) == position


def test_invalid_result_keeps_tournament_and_warns(menu: MainMenu, entry: PlayerEntry) -> None:
    _start_players(entry, ["Alice", "Bob"])
    original = menu.tournament
    with patch("main_menu.MainMenu._show_warning") as warning:
        menu._record_result("W1", 10)
    warning.assert_called_once()
    assert menu.tournament is original


def test_stale_background_schedule_cannot_replace_new_tournament(
    menu: MainMenu, entry: PlayerEntry
) -> None:
    entry.set_format("Double Elimination")
    _start_players(entry, ["Alice", "Bob"])
    _wait_scheduling(menu)
    stale = menu.scheduling_result
    generation = menu._schedule_generation
    assert stale is not None
    menu.bracket_view.back_button.click()
    menu.single_button.click()
    entry.start_button.click()
    current = menu.tournament
    menu._apply_schedule(stale, generation)
    assert menu.tournament is current
    assert current is not None and current.draw.tournament_format == "Single Elimination"
    assert not menu.bracket_view.scheduling


def test_stale_bracket_schedule_cannot_replace_chip_tournament(
    menu: MainMenu, entry: PlayerEntry
) -> None:
    entry.set_format("Double Elimination")
    _start_players(entry, ["Alice", "Bob"])
    _wait_scheduling(menu)
    stale = menu.scheduling_result
    generation = menu._schedule_generation
    assert stale is not None
    menu.bracket_view.back_button.click()
    menu.chip_button.click()
    entry.restore_chip_setup(["Alice", "Bob"], [2, 3], 1)
    entry.start_button.click()
    current = menu.chip_tournament
    menu._apply_schedule(stale, generation)
    assert menu.chip_tournament is current and current is not None
    assert menu.tournament is None
    assert menu.pages.currentWidget() is menu.chip_view


def test_click_active_match_records_result_and_shows_champion(
    menu: MainMenu, entry: PlayerEntry
) -> None:
    _start_players(entry, ["Same", "Same"])

    def choose_winner() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, _ResultDialog)
        assert dialog.winner_buttons[0].text() != dialog.winner_buttons[1].text()
        dialog.winner_buttons[1].click()

    QTimer.singleShot(0, choose_winner)
    view = menu.bracket_view
    point = view.graphics.mapFromScene(view.match_rects["W1"].center())
    QTest.mouseClick(view.graphics.viewport(), Qt.MouseButton.LeftButton, pos=point)
    _wait_scheduling(menu)
    assert menu.tournament is not None
    assert menu.tournament.progress[0].winner_index == 1
    assert "Champion: Same" in view.status_label.text()
    with patch("bracket_view._ResultDialog") as dialog:
        _click_match(menu)
    dialog.assert_not_called()


def test_loading_legacy_preserves_free_tables_and_active_match(
    menu: MainMenu, tmp_path: Path
) -> None:
    draw = build_preview(["Alice", "Bob", "Carol", "Dana"], "Single Elimination")
    original = TournamentState(
        draw, draw.names, 2, (MatchProgress("W1", "in_progress", table_number=2),), draw_locked=True
    )
    path = tmp_path / "active.json"
    save_tournament(path, original)
    with patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(path), "")):
        menu.load_button.click()
    _wait_scheduling(menu)
    assert menu.tournament is not None
    assert menu.tournament.draw == original.draw
    assert menu.tournament.progress == original.progress
    assert menu.bracket_view.read_only


def test_double_scheduling_is_asynchronous_and_close_cleans_worker(
    menu: MainMenu, entry: PlayerEntry, application: QApplication
) -> None:
    entry.set_format("Double Elimination")
    _start_players(entry, ["Alice", "Bob", "Carol", "Dana"])
    assert menu.bracket_view.scheduling
    with patch("bracket_view._ResultDialog") as dialog:
        menu.bracket_view._open_results("W1")
    dialog.assert_not_called()
    closed: list[bool] = []

    def on_last_window_closed() -> None:
        closed.append(True)

    application.lastWindowClosed.connect(on_last_window_closed)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(application.quit)
    application.setQuitOnLastWindowClosed(True)
    try:
        timeout.start(3000)
        QTimer.singleShot(0, menu.close)
        application.exec()
    finally:
        timeout.stop()
        application.setQuitOnLastWindowClosed(False)
        application.lastWindowClosed.disconnect(on_last_window_closed)
    assert not menu._scheduling_threads
    assert not menu.isVisible()
    assert closed == [True]


def test_menu_opens_with_expected_controls(menu: MainMenu) -> None:
    assert menu.isVisible()
    assert menu.windowTitle() == "Tourney"
    assert menu.single_button.text() == "&Single Elimination"
    assert menu.double_button.text() == "&Double Elimination"
    assert menu.chip_button.text() == "&Chip Tournament"
    assert menu.load_button.text() == "&Load Tournament"
    assert menu.exit_button.text() == "E&xit"
    assert all(
        not label.text().startswith("Selected:") for label in menu.menu_page.findChildren(QLabel)
    )


@pytest.mark.parametrize(
    "button_name, expected",
    [
        ("single_button", "Single Elimination"),
        ("double_button", "Double Elimination"),
        ("chip_button", "Chip Tournament"),
    ],
)
def test_format_buttons_report_correct_selection(
    menu: MainMenu, button_name: str, expected: str
) -> None:
    selections: list[str] = []
    menu.format_selected.connect(selections.append)

    QTest.mouseClick(getattr(menu, button_name), Qt.MouseButton.LeftButton)

    assert selections == [expected]
    assert all(
        not label.text().startswith("Selected:") for label in menu.menu_page.findChildren(QLabel)
    )
    assert menu.isVisible()
    assert menu.player_entry.isVisible()
    assert menu.player_entry.format_label.text() == expected
    assert menu.player_entry.feedback_label.text() == ""


def test_switching_formats_updates_selection(menu: MainMenu) -> None:
    menu.single_button.click()
    menu.player_entry.back_button.click()
    menu.double_button.click()

    assert menu.player_entry.format_label.text() == "Double Elimination"
    menu.player_entry.back_button.click()
    assert all(
        not label.text().startswith("Selected:") for label in menu.menu_page.findChildren(QLabel)
    )


def test_keyboard_focus_cycles_through_buttons(menu: MainMenu) -> None:
    menu.single_button.setFocus()
    for current, following in [
        (menu.single_button, menu.double_button),
        (menu.double_button, menu.chip_button),
        (menu.chip_button, menu.load_button),
        (menu.load_button, menu.exit_button),
        (menu.exit_button, menu.single_button),
    ]:
        assert current.hasFocus()
        QTest.keyClick(current, Qt.Key.Key_Tab)
        assert following.hasFocus()

    QTest.keyClick(menu.single_button, Qt.Key.Key_Backtab)
    assert menu.exit_button.hasFocus()


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space])
@pytest.mark.parametrize(
    "button_name, expected",
    [
        ("single_button", "Single Elimination"),
        ("double_button", "Double Elimination"),
        ("chip_button", "Chip Tournament"),
    ],
)
def test_keyboard_activates_focused_format(
    menu: MainMenu, button_name: str, expected: str, key: Qt.Key
) -> None:
    button = getattr(menu, button_name)
    button.setFocus()

    QTest.keyClick(button, key)

    assert menu.player_entry.format_label.text() == expected
    assert all(
        not label.text().startswith("Selected:") for label in menu.menu_page.findChildren(QLabel)
    )
    assert menu.player_entry.isVisible()
    assert menu.player_entry.feedback_label.text() == ""


@pytest.mark.parametrize("width, height", [(360, 320), (480, 400), (900, 700), (1920, 1080)])
def test_controls_fit_when_resized(
    menu: MainMenu, application: QApplication, width: int, height: int
) -> None:
    menu.resize(width, height)
    application.processEvents()

    for button in [
        menu.single_button,
        menu.double_button,
        menu.chip_button,
        menu.load_button,
        menu.exit_button,
    ]:
        assert button.isVisible()
        assert menu.rect().contains(button.geometry())
        assert button.width() >= button.sizeHint().width()
        assert button.height() >= button.sizeHint().height()


def test_exit_button_closes_menu(menu: MainMenu) -> None:
    QTest.mouseClick(menu.exit_button, Qt.MouseButton.LeftButton)

    assert not menu.isVisible()


def test_keyboard_activates_exit(menu: MainMenu) -> None:
    menu.exit_button.setFocus()
    QTest.keyClick(menu.exit_button, Qt.Key.Key_Return)

    assert not menu.isVisible()


def test_window_close_control_closes_menu(menu: MainMenu) -> None:
    assert menu.close()
    assert not menu.isVisible()


def test_main_shows_menu_and_returns_event_loop_exit_code() -> None:
    with patch("main_menu.QApplication") as application, patch("main_menu.MainMenu") as window:
        application.return_value.exec.return_value = 0

        assert main() == 0

    window.return_value.showMaximized.assert_called_once_with()
    application.return_value.exec.assert_called_once_with()


def test_player_entry_opens_empty_with_name_field_focused(entry: PlayerEntry) -> None:
    assert entry.name_input.hasFocus()
    assert entry.player_names() == []
    assert entry.count_label.text() == "Players: 0 / 32"
    assert entry.add_button.isEnabled()
    assert not entry.remove_button.isEnabled()


def test_chip_setup_requires_explicit_counts(chip_entry: PlayerEntry) -> None:
    assert chip_entry.chip_count_input.isVisible()
    assert chip_entry.chip_count_input.text() == ""
    assert chip_entry.chip_count_input.y() > chip_entry.name_input.y()
    assert chip_entry.name_input.hasFocus()
    assert chip_entry.add_button.text() == "&Add Player"
    assert not chip_entry.start_button.isEnabled()


@pytest.mark.parametrize("chips", ["", "0", "-1", "1.5", "abc", "2147483648"])
def test_chip_setup_rejects_missing_or_invalid_counts(chip_entry: PlayerEntry, chips: str) -> None:
    chip_entry.name_input.setText("Alice")
    chip_entry.chip_count_input.setText(chips)
    chip_entry.add_button.click()
    assert chip_entry.player_names() == []
    assert chip_entry.name_input.text() == "Alice"
    assert chip_entry.chip_count_input.hasFocus()
    assert "positive whole number" in chip_entry.feedback_label.text()


def test_chip_setup_adds_name_and_count_and_clears_both_fields(chip_entry: PlayerEntry) -> None:
    chip_entry.name_input.setText("  Alice  ")
    chip_entry.chip_count_input.setText("5")
    chip_entry.add_button.click()
    assert chip_entry.player_names() == ["Alice"]
    assert chip_entry.player_chip_counts() == [5]
    assert chip_entry.name_input.text() == ""
    assert chip_entry.chip_count_input.text() == ""
    assert chip_entry.name_input.hasFocus()
    assert chip_entry.feedback_label.text() == ""


def test_chip_setup_requires_a_name_and_accepts_the_largest_count(chip_entry: PlayerEntry) -> None:
    chips = 2**31 - 1
    chip_entry.chip_count_input.setText(str(chips))
    chip_entry.add_button.click()
    assert chip_entry.player_names() == []
    assert chip_entry.name_input.hasFocus()
    chip_entry.name_input.setText("Alice")
    chip_entry.add_button.click()
    assert chip_entry.player_chip_counts() == [chips]


def test_chip_player_limit_cannot_be_bypassed_with_enter(chip_entry: PlayerEntry) -> None:
    for index in range(_PLAYER_LIMIT):
        chip_entry.name_input.setText(f"Player {index}")
        chip_entry.chip_count_input.setText("3")
        chip_entry.add_button.click()
    chip_entry.name_input.setText("Extra")
    chip_entry.chip_count_input.setText("5")
    QTest.keyClick(chip_entry.chip_count_input, Qt.Key.Key_Return)
    assert len(chip_entry.player_names()) == _PLAYER_LIMIT
    assert chip_entry.name_input.text() == "Extra"
    assert chip_entry.chip_count_input.text() == "5"
    assert not chip_entry.add_button.isEnabled()


def test_chip_setup_preserves_duplicate_names_with_distinct_counts(chip_entry: PlayerEntry) -> None:
    for chips in ["2", "7", "4"]:
        chip_entry.name_input.setText("Same 李")
        chip_entry.chip_count_input.setText(chips)
        chip_entry.add_button.click()
    assert chip_entry.player_names() == ["Same 李"] * 3
    assert chip_entry.player_chip_counts() == [2, 7, 4]
    chip_entry.player_list.setCurrentRow(1)
    chip_entry.remove_button.click()
    assert chip_entry.player_chip_counts() == [2, 4]


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_chip_entry_keyboard_moves_from_name_to_chips_then_adds(
    chip_entry: PlayerEntry, key: Qt.Key
) -> None:
    QTest.keyClicks(chip_entry.name_input, "Alice")
    QTest.keyClick(chip_entry.name_input, key)
    assert chip_entry.chip_count_input.hasFocus()
    assert chip_entry.player_names() == []
    QTest.keyClicks(chip_entry.chip_count_input, "3")
    QTest.keyClick(chip_entry.chip_count_input, key)
    assert chip_entry.player_names() == ["Alice"]
    assert chip_entry.player_chip_counts() == [3]
    assert chip_entry.name_input.hasFocus()


def test_chip_setup_tab_order(chip_entry: PlayerEntry) -> None:
    QTest.keyClick(chip_entry.name_input, Qt.Key.Key_Tab)
    assert chip_entry.chip_count_input.hasFocus()
    QTest.keyClick(chip_entry.chip_count_input, Qt.Key.Key_Tab)
    assert chip_entry.add_button.hasFocus()


def test_chip_setup_keeps_counts_and_unfinished_input_when_switching_modes(
    menu: MainMenu, chip_entry: PlayerEntry
) -> None:
    chip_entry.name_input.setText("Alice")
    chip_entry.chip_count_input.setText("3")
    chip_entry.add_button.click()
    chip_entry.name_input.setText("Bob")
    chip_entry.chip_count_input.setText("6")
    tables = 4
    chip_entry.table_count_input.setValue(tables)
    chip_entry.back_button.click()
    menu.single_button.click()
    assert not chip_entry.chip_count_input.isVisible()
    assert chip_entry.add_button.text() == "&Add"
    assert chip_entry.player_names() == ["Alice"]
    chip_entry.back_button.click()
    menu.chip_button.click()
    assert chip_entry.player_chip_counts() == [3]
    assert chip_entry.name_input.text() == "Bob"
    assert chip_entry.chip_count_input.text() == "6"
    assert chip_entry.table_count() == tables


def test_chip_start_opens_leaderboard_and_matchups(menu: MainMenu, chip_entry: PlayerEntry) -> None:
    requests: list[tuple[str, list[str], int]] = []
    chip_entry.start_requested.connect(lambda *args: requests.append(args))
    for name in ["Alice", "Bob"]:
        chip_entry.name_input.setText(name)
        chip_entry.chip_count_input.setText("3")
        chip_entry.add_button.click()
    assert chip_entry.start_button.isEnabled()
    chip_entry.start_button.click()
    assert requests == [("Chip Tournament", ["Alice", "Bob"], 1)]
    assert menu.pages.currentWidget() is menu.chip_view
    assert menu.chip_tournament is not None
    assert menu.chip_view.leaderboard.topLevelItemCount() == len(menu.chip_tournament.players)
    assert len(menu.chip_view.match_cards) == 1
    assert menu.tournament is None


@pytest.mark.parametrize("width, height", [(640, 600), (900, 700), (1920, 1080)])
def test_chip_setup_controls_fit_and_fields_are_stacked(
    menu: MainMenu, chip_entry: PlayerEntry, application: QApplication, width: int, height: int
) -> None:
    menu.resize(width, height)
    application.processEvents()
    assert menu.width() == width and menu.height() == height
    for widget in [
        chip_entry.name_input,
        chip_entry.chip_count_input,
        chip_entry.add_button,
        chip_entry.player_list,
        chip_entry.remove_button,
        chip_entry.back_button,
        chip_entry.start_button,
    ]:
        assert widget.isVisible()
        assert chip_entry.rect().contains(widget.geometry())
    assert chip_entry.name_input.geometry().bottom() < chip_entry.chip_count_input.geometry().top()
    assert chip_entry.chip_count_input.geometry().bottom() < chip_entry.player_list.geometry().top()


def test_add_button_adds_trimmed_name(entry: PlayerEntry) -> None:
    entry.name_input.setText("  Alice Smith  ")
    QTest.mouseClick(entry.add_button, Qt.MouseButton.LeftButton)

    assert entry.player_names() == ["Alice Smith"]
    assert entry.count_label.text() == "Players: 1 / 32"
    assert entry.name_input.text() == ""
    assert entry.name_input.hasFocus()
    assert entry.feedback_label.text() == ""


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_enter_in_name_field_adds_exactly_one_player(entry: PlayerEntry, key: Qt.Key) -> None:
    QTest.keyClicks(entry.name_input, "Alice")
    QTest.keyClick(entry.name_input, key)

    assert entry.player_names() == ["Alice"]
    assert entry.feedback_label.text() == ""


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space])
def test_keyboard_activates_add_button(entry: PlayerEntry, key: Qt.Key) -> None:
    entry.name_input.setText("Alice")
    entry.add_button.setFocus()
    QTest.keyClick(entry.add_button, key)

    assert entry.player_names() == ["Alice"]
    assert entry.feedback_label.text() == ""


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_blank_names_are_rejected(entry: PlayerEntry, name: str) -> None:
    entry.name_input.setText(name)
    entry.add_button.click()

    assert entry.player_names() == []
    assert entry.count_label.text() == "Players: 0 / 32"
    assert entry.feedback_label.text() == "Enter a player name."
    assert entry.name_input.hasFocus()


def test_repeated_and_unicode_names_are_preserved(entry: PlayerEntry) -> None:
    names = ["Alice", "Alice", "José 李"]
    for name in names:
        entry.name_input.setText(name)
        entry.add_button.click()

    assert entry.player_names() == names


def test_player_names_returns_an_independent_copy(entry: PlayerEntry) -> None:
    entry.name_input.setText("Alice")
    entry.add_button.click()
    names = entry.player_names()
    names.clear()

    assert entry.player_names() == ["Alice"]


def test_player_limit_cannot_be_bypassed_with_enter(entry: PlayerEntry) -> None:
    names = [f"Player {index}" for index in range(_PLAYER_LIMIT)]
    for name in names:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.name_input.setText("Extra player")
    QTest.keyClick(entry.name_input, Qt.Key.Key_Return)

    assert entry.player_names() == names
    assert entry.count_label.text() == "Players: 32 / 32"
    assert not entry.add_button.isEnabled()
    assert "32-player limit" in entry.feedback_label.text()
    assert entry.name_input.text() == "Extra player"


def test_remove_selected_preserves_other_players(entry: PlayerEntry) -> None:
    for name in ["Alice", "Bob", "Carol"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.player_list.setCurrentRow(1)
    QTest.mouseClick(entry.remove_button, Qt.MouseButton.LeftButton)

    assert entry.player_names() == ["Alice", "Carol"]
    assert entry.count_label.text() == "Players: 2 / 32"


def test_delete_key_removes_only_selected_player(entry: PlayerEntry) -> None:
    for name in ["Alice", "Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.player_list.setCurrentRow(1)
    entry.player_list.setFocus()
    QTest.keyClick(entry.player_list, Qt.Key.Key_Delete)

    assert entry.player_names() == ["Alice", "Bob"]


def test_remove_button_requires_a_selection(entry: PlayerEntry) -> None:
    entry.name_input.setText("Alice")
    entry.add_button.click()
    entry.player_list.clearSelection()

    assert not entry.remove_button.isEnabled()
    entry.remove_button.click()
    assert entry.player_names() == ["Alice"]


def test_removing_last_player_restores_empty_controls(entry: PlayerEntry) -> None:
    entry.name_input.setText("Alice")
    entry.add_button.click()
    entry.remove_button.click()

    assert entry.player_names() == []
    assert entry.count_label.text() == "Players: 0 / 32"
    assert not entry.remove_button.isEnabled()


def test_removing_a_player_at_limit_allows_another(entry: PlayerEntry) -> None:
    for index in range(_PLAYER_LIMIT):
        entry.name_input.setText(f"Player {index}")
        entry.add_button.click()
    entry.remove_button.click()

    assert entry.add_button.isEnabled()
    assert entry.feedback_label.text() == ""
    entry.name_input.setText("Replacement")
    entry.add_button.click()
    assert len(entry.player_names()) == _PLAYER_LIMIT
    assert entry.player_names()[-1] == "Replacement"


def test_delete_in_name_field_does_not_remove_players(entry: PlayerEntry) -> None:
    entry.name_input.setText("Alice")
    entry.add_button.click()
    entry.name_input.setText("Bob")
    entry.name_input.setCursorPosition(0)
    QTest.keyClick(entry.name_input, Qt.Key.Key_Delete)

    assert entry.player_names() == ["Alice"]
    assert entry.name_input.text() == "ob"


def test_back_preserves_names_and_unfinished_input(menu: MainMenu, entry: PlayerEntry) -> None:
    entry.name_input.setText("Alice")
    entry.add_button.click()
    entry.name_input.setText("Bob")
    entry.back_button.click()

    assert menu.single_button.isVisible()
    assert not entry.isVisible()
    assert menu.single_button.hasFocus()
    menu.double_button.click()
    assert entry.format_label.text() == "Double Elimination"
    assert entry.player_names() == ["Alice"]
    assert entry.name_input.text() == "Bob"
    assert entry.name_input.hasFocus()


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space])
def test_keyboard_activates_back(menu: MainMenu, entry: PlayerEntry, key: Qt.Key) -> None:
    entry.back_button.setFocus()
    QTest.keyClick(entry.back_button, key)

    assert menu.single_button.isVisible()
    assert not entry.isVisible()


def test_player_entry_tab_order(entry: PlayerEntry) -> None:
    entry.name_input.setText("Alice")
    entry.add_button.click()
    for current, following in [
        (entry.name_input, entry.add_button),
        (entry.add_button, entry.player_list),
        (entry.player_list, entry.remove_button),
        (entry.remove_button, entry.back_button),
        (entry.back_button, entry.table_count_input),
        (entry.table_count_input, entry.name_input),
    ]:
        assert current.hasFocus()
        QTest.keyClick(current, Qt.Key.Key_Tab)
        assert following.hasFocus()


@pytest.mark.parametrize("width, height", [(360, 440), (480, 500), (900, 700), (1920, 1080)])
def test_player_entry_controls_fit_when_resized(
    menu: MainMenu, entry: PlayerEntry, application: QApplication, width: int, height: int
) -> None:
    for index in range(_PLAYER_LIMIT):
        entry.name_input.setText(f"Player {index}")
        entry.add_button.click()
    entry.start_button.click()
    menu.bracket_view.back_button.click()
    menu.single_button.click()
    menu.resize(width, height)
    application.processEvents()

    for widget in [
        entry.name_input,
        entry.table_count_input,
        entry.player_list,
        entry.add_button,
        entry.remove_button,
        entry.back_button,
        entry.start_button,
        entry.feedback_label,
    ]:
        assert widget.isVisible()
        assert entry.rect().contains(widget.geometry())
    assert entry.add_button.width() >= entry.add_button.sizeHint().width()
    assert entry.remove_button.width() >= entry.remove_button.sizeHint().width()
    assert entry.back_button.width() >= entry.back_button.sizeHint().width()
    assert entry.start_button.width() >= entry.start_button.sizeHint().width()
    assert entry.player_list.geometry().bottom() < entry.feedback_label.geometry().top()
    assert entry.feedback_label.geometry().bottom() < entry.back_button.geometry().top()
    assert entry.back_button.geometry().bottom() < entry.start_button.geometry().top()


def test_window_closes_from_player_entry(menu: MainMenu, entry: PlayerEntry) -> None:
    assert menu.close()
    assert not menu.isVisible()
    assert not entry.isVisible()


def test_table_count_defaults_to_one(entry: PlayerEntry) -> None:
    assert entry.table_count_input.isVisible()
    assert entry.table_count() == 1


def test_table_count_can_be_entered_with_keyboard(entry: PlayerEntry) -> None:
    entry.table_count_input.setFocus()
    entry.table_count_input.selectAll()
    QTest.keyClicks(entry.table_count_input, "12")
    QTest.keyClick(entry.table_count_input, Qt.Key.Key_Return)

    expected_count = 12
    assert entry.table_count() == expected_count
    assert entry.player_names() == []
    assert entry.feedback_label.text() == ""


def test_start_button_requires_at_least_two_players(entry: PlayerEntry) -> None:
    assert entry.start_button.isVisible()
    assert entry.start_button.text() == "&Start"
    assert not entry.start_button.isEnabled()
    for name in ["Alice", "Bob"]:
        assert not entry.start_button.isEnabled()
        entry.name_input.setText(name)
        entry.add_button.click()

    assert entry.start_button.isEnabled()
    entry.remove_button.click()
    assert not entry.start_button.isEnabled()


@pytest.mark.parametrize(
    "button_name, expected_format",
    [("single_button", "Single Elimination"), ("double_button", "Double Elimination")],
)
def test_start_hands_off_selected_setup(
    menu: MainMenu,
    entry: PlayerEntry,
    start_requests: list[tuple[str, list[str], int]],
    button_name: str,
    expected_format: str,
) -> None:
    entry.back_button.click()
    getattr(menu, button_name).click()
    names = ["Alice", "Bob"]
    for name in names:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.table_count_input.setValue(3)

    QTest.mouseClick(entry.start_button, Qt.MouseButton.LeftButton)

    assert start_requests == [(expected_format, names, 3)]
    assert entry.feedback_label.text() == (
        f"Setup confirmed: {expected_format}, 2 players, 3 tables."
    )


def test_start_is_disabled_until_unfinished_name_is_added(entry: PlayerEntry) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.name_input.setText("Carol")

    assert not entry.start_button.isEnabled()
    assert "Add the entered name" in entry.start_button.toolTip()
    entry.add_button.click()
    assert entry.start_button.isEnabled()


def test_clearing_unfinished_name_enables_start(entry: PlayerEntry) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.name_input.setText("Carol")
    entry.name_input.clear()

    assert entry.start_button.isEnabled()


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space])
def test_keyboard_activates_start(
    entry: PlayerEntry, start_requests: list[tuple[str, list[str], int]], key: Qt.Key
) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.setFocus()
    QTest.keyClick(entry.start_button, key)

    assert start_requests == [("Single Elimination", ["Alice", "Bob"], 1)]


def test_enter_to_add_second_player_does_not_start(
    entry: PlayerEntry, start_requests: list[tuple[str, list[str], int]]
) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        QTest.keyClick(entry.name_input, Qt.Key.Key_Return)

    assert entry.start_button.isEnabled()
    assert start_requests == []
    assert entry.feedback_label.text() == ""


def test_start_snapshot_does_not_change_when_players_are_edited(
    menu: MainMenu, entry: PlayerEntry, start_requests: list[tuple[str, list[str], int]]
) -> None:
    for name in ["Alice", "Alice"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.click()
    menu.bracket_view.back_button.click()
    entry.remove_button.click()

    assert start_requests == [("Single Elimination", ["Alice", "Alice"], 1)]
    assert entry.player_names() == ["Alice"]


def test_start_button_is_in_keyboard_tab_order(entry: PlayerEntry) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.back_button.setFocus()
    QTest.keyClick(entry.back_button, Qt.Key.Key_Tab)
    assert entry.start_button.hasFocus()
    QTest.keyClick(entry.start_button, Qt.Key.Key_Tab)
    assert entry.table_count_input.hasFocus()


def test_table_count_can_be_changed_with_arrow_keys(entry: PlayerEntry) -> None:
    initial_count = entry.table_count()
    entry.table_count_input.setFocus()
    QTest.keyClick(entry.table_count_input, Qt.Key.Key_Up)
    assert entry.table_count() == initial_count + 1
    QTest.keyClick(entry.table_count_input, Qt.Key.Key_Down)
    assert entry.table_count() == initial_count


@pytest.mark.parametrize("value", [0, -1])
def test_table_count_cannot_be_zero_or_negative(entry: PlayerEntry, value: int) -> None:
    entry.table_count_input.setValue(value)
    QTest.keyClick(entry.table_count_input, Qt.Key.Key_Down)

    assert entry.table_count() == 1


@pytest.mark.parametrize("text", ["0", "-2", "abc", "1.5", ""])
def test_invalid_table_input_keeps_a_positive_whole_number(entry: PlayerEntry, text: str) -> None:
    entry.table_count_input.setFocus()
    entry.table_count_input.selectAll()
    QTest.keyClick(entry.table_count_input, Qt.Key.Key_Backspace)
    QTest.keyClicks(entry.table_count_input, text)
    QTest.keyClick(entry.table_count_input, Qt.Key.Key_Return)

    assert isinstance(entry.table_count(), int)
    assert entry.table_count() >= 1
    assert entry.table_count_input.text() == str(entry.table_count())


def test_back_preserves_table_count_when_changing_format(
    menu: MainMenu, entry: PlayerEntry
) -> None:
    expected_count = 8
    entry.table_count_input.setValue(expected_count)
    entry.back_button.click()
    menu.double_button.click()

    assert entry.format_label.text() == "Double Elimination"
    assert entry.table_count() == expected_count


def test_start_opens_preview_with_shuffled_players_and_table_count(
    menu: MainMenu, entry: PlayerEntry
) -> None:
    names = ["Alice", "Bob", "Carol"]
    for name in names:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.table_count_input.setValue(4)
    with patch("main_menu.shuffle_names", side_effect=lambda players: list(reversed(players))):
        entry.start_button.click()

    view = menu.bracket_view
    assert view.isVisible()
    assert not entry.isVisible()
    assert view.draw is not None
    assert view.draw.names == tuple(reversed(names))
    assert view.draw.tournament_format == "Single Elimination"
    expected_tables = 4
    assert view.table_count == expected_tables
    assert "4 tables" in view.summary_label.text()
    assert entry.player_names() == names


@pytest.mark.parametrize("format_", ["Single Elimination", "Double Elimination"])
def test_bracket_byes_omit_automatic_advance_note(menu: MainMenu, format_: str) -> None:
    draw = build_preview(["Alice", "Bob", "Carol"], format_)
    menu.bracket_view.show_draw(draw, 2)
    assert any(any(source.empty for source in match.slots) for match in draw.matches)
    texts = [
        item for item in menu.bracket_view.scene.items() if isinstance(item, QGraphicsTextItem)
    ]
    assert all("Bye: automatic advance" not in item.toPlainText() for item in texts)
    assert all("Bye: automatic advance" not in item.toolTip() for item in texts)


def test_double_preview_shows_both_sides_and_conditional_reset(
    menu: MainMenu, entry: PlayerEntry
) -> None:
    entry.back_button.click()
    menu.double_button.click()
    for index in range(8):
        entry.name_input.setText(f"Player {index}")
        entry.add_button.click()
    entry.start_button.click()
    _wait_scheduling(menu)
    texts = [
        item.toPlainText()
        for item in menu.bracket_view.scene.items()
        if isinstance(item, QGraphicsTextItem)
    ]

    assert "Winners' bracket" in texts
    assert "Losers' bracket" in texts
    assert "GF" in texts
    assert "RESET" in texts
    assert "If losers' finalist wins GF" in texts


@pytest.mark.parametrize("player_count", [2, 3, 5, 8, 32])
def test_started_bracket_returns_to_menu_without_losing_setup_inputs(
    menu: MainMenu, entry: PlayerEntry, player_count: int
) -> None:
    names = [f"Player {index}" for index in range(player_count)]
    for name in names:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.table_count_input.setValue(8)
    entry.start_button.click()
    QTest.mouseClick(menu.bracket_view.back_button, Qt.MouseButton.LeftButton)

    expected_tables = 8
    assert menu.menu_page.isVisible()
    assert entry.player_names() == names
    assert entry.table_count() == expected_tables
    assert menu.single_button.hasFocus()


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space])
def test_preview_back_button_works_with_keyboard(
    menu: MainMenu, entry: PlayerEntry, key: Qt.Key
) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.click()
    back = menu.bracket_view.back_button
    back.setFocus()
    QTest.keyClick(back, key)

    assert menu.menu_page.isVisible()


def test_large_double_preview_scrolls_and_match_boxes_do_not_overlap(
    menu: MainMenu, entry: PlayerEntry, application: QApplication
) -> None:
    entry.back_button.click()
    menu.double_button.click()
    for index in range(_PLAYER_LIMIT):
        entry.name_input.setText(f"Player {index}")
        entry.add_button.click()
    entry.start_button.click()
    _wait_scheduling(menu)
    menu.resize(360, 440)
    application.processEvents()
    view = menu.bracket_view
    rectangles = list(view.match_rects.values())

    assert view.graphics.horizontalScrollBar().maximum() > 0
    assert view.graphics.verticalScrollBar().maximum() > 0
    assert view.rect().contains(view.back_button.geometry())
    assert not view.graphics.geometry().intersects(view.back_button.geometry())
    for index, rectangle in enumerate(rectangles):
        assert all(not rectangle.intersects(other) for other in rectangles[index + 1 :])


def test_preview_can_be_rebuilt_with_a_different_player_count(
    menu: MainMenu, entry: PlayerEntry
) -> None:
    for name in ["Alice", "Bob", "Carol", "Dan"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.click()
    menu.bracket_view.back_button.click()
    menu.single_button.click()
    entry.remove_button.click()
    entry.remove_button.click()
    entry.start_button.click()

    assert set(menu.bracket_view.match_rects) == {"W1"}


def test_long_names_are_readable_through_tooltips(menu: MainMenu, entry: PlayerEntry) -> None:
    long_name = "A very long player name " * 20
    for name in [long_name, "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.click()
    labels = [
        item
        for item in menu.bracket_view.scene.items()
        if isinstance(item, QGraphicsTextItem) and item.toolTip() == long_name.strip()
    ]

    assert len(labels) == 1
    assert labels[0].toPlainText() != long_name.strip()


def test_window_closes_from_preview(menu: MainMenu, entry: PlayerEntry) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.click()

    assert menu.close()
    assert not menu.bracket_view.isVisible()


def test_preview_rejects_invalid_table_count_without_replacing_draw(menu: MainMenu) -> None:
    with pytest.raises(ValueError, match="At least one table"):
        menu.bracket_view.show_draw(build_preview(["Alice", "Bob"], "Single Elimination"), 0)

    assert menu.bracket_view.draw is None


@pytest.fixture
def saved_state() -> TournamentState:
    draw = build_preview(["Zoë", "李", "Zoë", "Dana"], "Double Elimination")
    return TournamentState(
        draw,
        tuple(reversed(draw.names)),
        3,
        progress=(
            MatchProgress("W1", "completed", winner_index=1),
            MatchProgress("W2", "in_progress", table_number=2),
        ),
        table_labels=(TableLabel(2, "Feature table"),),
        draw_locked=True,
    )


@pytest.mark.parametrize("table_number", [2, 2147483647])
@pytest.mark.parametrize("background", ["#ffffff", "#202020"])
def test_active_match_shows_green_table_number_inside_header(
    menu: MainMenu, table_number: int, background: str
) -> None:
    view = menu.bracket_view
    palette = view.palette()
    palette.setColor(QPalette.ColorRole.Base, QColor(background))
    view.setPalette(palette)
    draw = build_preview(["Alice", "Bob"], "Single Elimination")
    view.show_tournament(
        TournamentState(
            draw,
            draw.names,
            table_number,
            progress=(MatchProgress("W1", "in_progress", table_number=table_number),),
            draw_locked=True,
        )
    )
    texts = [item for item in view.scene.items() if isinstance(item, QGraphicsTextItem)]
    badge = next(item for item in texts if item.toPlainText() == f"Table {table_number}")
    identifier = next(item for item in texts if item.toPlainText() == "W1")

    color = badge.defaultTextColor()
    assert color.green() > color.red()
    assert color.green() > color.blue()
    assert badge.font().bold()
    assert badge.pos().y() == identifier.pos().y()
    assert view.match_rects["W1"].contains(badge.sceneBoundingRect())
    assert not badge.sceneBoundingRect().intersects(identifier.sceneBoundingRect())


def test_table_badge_preserves_custom_name_and_clears_when_draw_changes(
    menu: MainMenu, saved_state: TournamentState
) -> None:
    view = menu.bracket_view
    view.show_tournament(saved_state)
    texts = [item for item in view.scene.items() if isinstance(item, QGraphicsTextItem)]
    badge = next(item for item in texts if item.toPlainText() == "Table 2")

    assert badge.toolTip() == "Feature table"
    assert sum(item.toPlainText().startswith("Table ") for item in texts) == 1
    assert any(item.toPlainText() == "In progress · Feature table" for item in texts)
    assert view.match_rects["W2"].contains(badge.sceneBoundingRect())
    assert all(
        not rectangle.contains(badge.sceneBoundingRect())
        for match_id, rectangle in view.match_rects.items()
        if match_id != "W2"
    )
    view.show_draw(saved_state.draw, saved_state.table_count)
    assert not any(
        isinstance(item, QGraphicsTextItem) and item.toPlainText().startswith("Table ")
        for item in view.scene.items()
    )


@pytest.mark.parametrize(
    "label",
    ["Feature table", "Feature table " * 100, "X" * 200],
    ids=["custom", "long", "unbroken"],
)
def test_wrapped_match_notes_fit_inside_cards_with_full_tooltips(
    menu: MainMenu, label: str
) -> None:
    view = menu.bracket_view
    draw = build_preview(["Alice", "Bob", "Carol", "Dana"], "Double Elimination")
    view.show_tournament(
        TournamentState(
            draw,
            draw.names,
            1,
            progress=(MatchProgress("W1", "in_progress", table_number=1),),
            table_labels=(TableLabel(1, label),),
            draw_locked=True,
        )
    )
    for match_id, note in [
        ("W1", f"In progress · {label}"),
        ("RESET", "If losers' finalist wins GF"),
    ]:
        item = next(
            item
            for item in view.scene.items()
            if isinstance(item, QGraphicsTextItem) and item.toolTip() == note
        )
        assert view.match_rects[match_id].contains(item.sceneBoundingRect())
        if label == "Feature table" or match_id == "RESET":
            assert item.toPlainText() == note
        else:
            assert item.toPlainText().endswith("…")


def test_save_as_writes_exact_draw_and_setup_order(
    menu: MainMenu, entry: PlayerEntry, tmp_path: Path
) -> None:
    names = ["Alice", "Bob", "Carol"]
    for name in names:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.table_count_input.setValue(4)
    with patch("main_menu.shuffle_names", side_effect=lambda players: list(reversed(players))):
        entry.start_button.click()
    path = tmp_path / "my bracket.json"
    with patch("main_menu.QFileDialog.getSaveFileName", return_value=(str(path), "")):
        menu.bracket_view.save_button.click()
    loaded = load_tournament(path)
    assert loaded.draw == menu.bracket_view.draw
    assert loaded.entry_names == tuple(names)
    expected_tables = 4
    assert loaded.table_count == expected_tables
    assert str(path) in menu.bracket_view.file_label.text()


def test_load_restores_saved_progress_without_shuffling(
    menu: MainMenu, tmp_path: Path, saved_state: TournamentState
) -> None:
    path = tmp_path / "saved.json"
    save_tournament(path, saved_state)
    with (
        patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(path), "")),
        patch("main_menu.shuffle_names", side_effect=AssertionError("must not reshuffle")),
    ):
        menu.load_button.click()
    assert menu.bracket_view.isVisible()
    assert menu.tournament == saved_state
    assert menu.bracket_view.draw == saved_state.draw
    assert menu.player_entry.player_names() == list(saved_state.entry_names)
    assert menu.player_entry.table_count() == saved_state.table_count
    texts = {
        item.toPlainText()
        for item in menu.bracket_view.scene.items()
        if isinstance(item, QGraphicsTextItem)
    }
    assert "Winner: 李" in texts
    assert "In progress · Feature table" in texts
    assert menu.bracket_view.back_button.text() == "&Back to Menu"
    menu.bracket_view.back_button.click()
    assert menu.menu_page.isVisible()


def test_legacy_progress_cannot_be_saved_as_new_document(
    menu: MainMenu, tmp_path: Path, saved_state: TournamentState
) -> None:
    original = tmp_path / "original.json"
    copy = tmp_path / "copy.json"
    save_tournament(original, saved_state)
    with patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(original), "")):
        menu.load_button.click()
    with patch("main_menu.QFileDialog.getSaveFileName", return_value=(str(copy), "")):
        menu.bracket_view.save_button.click()
    assert not copy.exists()
    assert not menu.bracket_view.save_button.isEnabled()
    assert menu.tournament == saved_state


def test_unstarted_legacy_draw_remains_viewing_only(menu: MainMenu, tmp_path: Path) -> None:
    draw = build_preview(["Alice", "Bob", "Carol"], "Single Elimination")
    state = TournamentState(draw, tuple(reversed(draw.names)), 5)
    path = tmp_path / "before play.json"
    save_tournament(path, state)
    with patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(path), "")):
        menu.load_button.click()
    menu.bracket_view.back_button.click()
    assert menu.menu_page.isVisible()
    assert menu.tournament is not None
    assert menu.tournament.draw == draw
    assert not menu.tournament.draw_locked
    assert not menu.tournament.progress
    assert menu.bracket_view.read_only
    assert menu.player_entry.player_names() == list(state.entry_names)
    assert menu.player_entry.format_label.text() == state.draw.tournament_format
    assert menu.single_button.hasFocus()
    assert menu.player_entry.count_label.text() == "Players: 3 / 32"
    assert menu.player_entry.start_button.isEnabled()


def test_cancel_load_keeps_current_page_and_setup(menu: MainMenu) -> None:
    with patch("main_menu.QFileDialog.getOpenFileName", return_value=("", "")):
        menu.load_button.click()
    assert menu.menu_page.isVisible()
    assert menu.tournament is None
    assert menu.player_entry.player_names() == []


@pytest.mark.parametrize("contents", ["not json", "{}", "[]"])
def test_invalid_load_does_not_change_current_tournament(
    menu: MainMenu, entry: PlayerEntry, tmp_path: Path, contents: str
) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.click()
    original = menu.tournament
    menu.bracket_view.back_button.click()
    entry.back_button.click()
    path = tmp_path / "bad.json"
    path.write_text(contents, encoding="utf-8")
    with (
        patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(path), "")),
        patch("main_menu.MainMenu._show_warning") as warning,
    ):
        menu.load_button.click()
    warning.assert_called_once()
    assert menu.menu_page.isVisible()
    assert menu.tournament is original
    assert entry.player_names() == ["Alice", "Bob"]


def test_load_io_error_is_reported_without_leaving_menu(menu: MainMenu) -> None:
    with (
        patch("main_menu.QFileDialog.getOpenFileName", return_value=("missing.json", "")),
        patch("main_menu.read_tournament_file", side_effect=OSError("permission denied")),
        patch("main_menu.MainMenu._show_warning") as warning,
    ):
        menu.load_button.click()
    warning.assert_called_once()
    assert menu.menu_page.isVisible()
    assert menu.tournament is None


def test_save_cancel_and_write_failure_keep_draw(
    menu: MainMenu, entry: PlayerEntry, tmp_path: Path
) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.click()
    original = menu.tournament
    with (
        patch("main_menu.QFileDialog.getSaveFileName", return_value=("", "")),
        patch("main_menu.save_document") as save,
    ):
        menu.bracket_view.save_button.click()
    save.assert_not_called()
    with (
        patch("main_menu.QFileDialog.getSaveFileName", return_value=(str(tmp_path / "a"), "")),
        patch("main_menu.save_document", side_effect=OSError("disk full")),
        patch("main_menu.MainMenu._show_warning") as warning,
    ):
        menu.bracket_view.save_button.click()
    warning.assert_called_once()
    assert menu.tournament is original
    assert menu.bracket_view.isVisible()


@pytest.mark.parametrize("filename", ["bracket", "bracket.txt", "bracket.JSON"])
def test_save_as_ensures_json_extension(
    menu: MainMenu, entry: PlayerEntry, tmp_path: Path, filename: str
) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.click()
    with patch(
        "main_menu.QFileDialog.getSaveFileName", return_value=(str(tmp_path / filename), "")
    ):
        menu.bracket_view.save_button.click()
    expected = filename if filename.lower().endswith(".json") else filename + ".json"
    assert load_tournament(tmp_path / expected) == menu.tournament


def test_load_shortcut_is_only_available_on_main_menu(
    menu: MainMenu, application: QApplication
) -> None:
    with patch("main_menu.QFileDialog.getOpenFileName", return_value=("", "")) as dialog:
        QTest.keySequence(menu, QKeySequence(QKeySequence.StandardKey.Open))
        assert dialog.call_count == 1
        menu.single_button.click()
        application.processEvents()
        QTest.keySequence(menu.player_entry.name_input, QKeySequence(QKeySequence.StandardKey.Open))
        assert dialog.call_count == 1
        for name in ["Alice", "Bob"]:
            menu.player_entry.name_input.setText(name)
            menu.player_entry.add_button.click()
        menu.player_entry.start_button.click()
        application.processEvents()
        QTest.keySequence(
            menu.bracket_view.back_button, QKeySequence(QKeySequence.StandardKey.Open)
        )
        assert dialog.call_count == 1
        assert not menu.load_button.isVisible()


def test_save_shortcut_works_on_bracket(menu: MainMenu, entry: PlayerEntry, tmp_path: Path) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.click()
    QApplication.processEvents()
    path = tmp_path / "shortcut.json"
    with patch("main_menu.QFileDialog.getSaveFileName", return_value=(str(path), "")):
        QTest.keySequence(
            menu.bracket_view.back_button, QKeySequence(QKeySequence.StandardKey.SaveAs)
        )
    assert load_tournament(path) == menu.tournament


@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
def test_adding_json_extension_confirms_overwrite(
    menu: MainMenu, entry: PlayerEntry, tmp_path: Path, answer: QMessageBox.StandardButton
) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.click()
    path = tmp_path / "existing.json"
    path.write_text("previous save", encoding="utf-8")
    with (
        patch(
            "main_menu.QFileDialog.getSaveFileName", return_value=(str(tmp_path / "existing"), "")
        ),
        patch("main_menu.MainMenu._confirm_action", return_value=answer) as question,
    ):
        menu.bracket_view.save_button.click()
    question.assert_called_once()
    if answer == QMessageBox.StandardButton.Yes:
        assert load_tournament(path) == menu.tournament
    else:
        assert path.read_text(encoding="utf-8") == "previous save"


@pytest.mark.parametrize("gf_winner", [0, 1])
def test_loaded_double_final_uses_player_ids_for_reset_note(
    menu: MainMenu, tmp_path: Path, gf_winner: int
) -> None:
    draw = build_preview(["Same name", "Same name"], "Double Elimination")
    state = TournamentState(
        draw,
        draw.names,
        1,
        progress=(
            MatchProgress("W1", "completed", winner_index=0),
            MatchProgress("GF", "completed", winner_index=gf_winner),
        ),
        draw_locked=True,
    )
    path = tmp_path / "final.json"
    save_tournament(path, state)
    with patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(path), "")):
        menu.load_button.click()
    texts = {
        item.toPlainText()
        for item in menu.bracket_view.scene.items()
        if isinstance(item, QGraphicsTextItem)
    }
    assert ("Not needed" if gf_winner == 0 else "If losers' finalist wins GF") in texts


@pytest.mark.parametrize(
    "tournament_format, names, table_count",
    [
        ("Unknown", ["Alice", "Bob"], 1),
        ("Single Elimination", ["Alice"], 1),
        ("Single Elimination", ["Alice", " "], 1),
        ("Single Elimination", ["Alice", "Bob"], 0),
    ],
)
def test_restore_setup_validates_before_changing_inputs(
    entry: PlayerEntry, tournament_format: str, names: list[str], table_count: int
) -> None:
    entry.name_input.setText("Unfinished name")
    with pytest.raises(ValueError):
        entry.restore_setup(tournament_format, names, table_count)
    assert entry.name_input.text() == "Unfinished name"
    assert entry.player_names() == []
    assert entry.format_label.text() == "Single Elimination"


def test_existing_json_file_uses_explicit_overwrite_confirmation(
    menu: MainMenu, entry: PlayerEntry, tmp_path: Path
) -> None:
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.click()
    path = tmp_path / "existing.json"
    path.write_text("previous save", encoding="utf-8")
    with (
        patch("main_menu.QFileDialog.getSaveFileName", return_value=(str(path), "")),
        patch(
            "main_menu.MainMenu._confirm_action", return_value=QMessageBox.StandardButton.Yes
        ) as question,
    ):
        menu.bracket_view.save_button.click()
    question.assert_called_once()
    assert load_tournament(path) == menu.tournament


def test_full_hd_controls_are_readable_and_menu_is_centered(
    menu: MainMenu, application: QApplication
) -> None:
    menu.resize(1920, 1080)
    application.processEvents()
    minimum_font_points = 14
    minimum_button_height = 56
    maximum_menu_width = 900
    for button in [
        menu.single_button,
        menu.double_button,
        menu.chip_button,
        menu.load_button,
        menu.exit_button,
    ]:
        assert button.font().pointSizeF() >= minimum_font_points
        assert button.height() >= minimum_button_height
        assert button.width() <= maximum_menu_width
        center = button.mapTo(menu, button.rect().center())
        assert abs(center.x() - menu.rect().center().x()) <= 1
    menu.single_button.click()
    for widget in [menu.player_entry.name_input, menu.player_entry.table_count_input]:
        assert widget.font().pointSizeF() >= minimum_font_points
        assert widget.height() >= minimum_button_height


@pytest.mark.parametrize("player_count", [2, 8, 32])
@pytest.mark.parametrize("tournament_format", ["Single Elimination", "Double Elimination"])
def test_full_hd_bracket_text_fits_inside_larger_match_boxes(
    menu: MainMenu,
    entry: PlayerEntry,
    application: QApplication,
    player_count: int,
    tournament_format: str,
) -> None:
    menu.resize(1920, 1080)
    entry.set_format(tournament_format)
    for index in range(player_count):
        entry.name_input.setText(f"Player {index}")
        entry.add_button.click()
    entry.start_button.click()
    application.processEvents()
    view = menu.bracket_view
    minimum_card_width = 300
    minimum_font_points = 14
    for rectangle in view.match_rects.values():
        visible_width = view.graphics.mapFromScene(rectangle).boundingRect().width()
        assert visible_width >= minimum_card_width
        for item in view.scene.items(rectangle):
            if isinstance(item, QGraphicsTextItem):
                assert item.font().pointSizeF() >= minimum_font_points
                assert rectangle.contains(item.sceneBoundingRect())


@pytest.mark.parametrize("width, height", [(900, 700), (1920, 1080)])
def test_switching_pages_keeps_the_user_selected_window_size(
    menu: MainMenu, entry: PlayerEntry, width: int, height: int
) -> None:
    menu.resize(width, height)
    expected_size = menu.size()
    for name in ["Alice", "Bob"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.click()
    assert menu.size() == expected_size
    menu.bracket_view.back_button.click()
    assert menu.size() == expected_size
