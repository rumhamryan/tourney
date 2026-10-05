from collections.abc import Iterator
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from main_menu import MainMenu, main
from player_entry import PlayerEntry

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
def menu(application: QApplication) -> Iterator[MainMenu]:
    window = MainMenu()
    window.show()
    window.activateWindow()
    application.processEvents()
    yield window
    window.close()
    window.deleteLater()
    application.processEvents()


@pytest.fixture
def entry(menu: MainMenu) -> PlayerEntry:
    menu.single_button.click()
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


def test_menu_opens_with_expected_controls(menu: MainMenu) -> None:
    assert menu.isVisible()
    assert menu.windowTitle() == "Tourney"
    assert menu.single_button.text() == "&Single Elimination"
    assert menu.double_button.text() == "&Double Elimination"
    assert menu.exit_button.text() == "E&xit"
    assert menu.selection_label.text() == ""


@pytest.mark.parametrize(
    "button_name, expected",
    [
        ("single_button", "Single Elimination"),
        ("double_button", "Double Elimination"),
    ],
)
def test_format_buttons_report_correct_selection(
    menu: MainMenu, button_name: str, expected: str
) -> None:
    selections: list[str] = []
    menu.format_selected.connect(selections.append)

    QTest.mouseClick(getattr(menu, button_name), Qt.MouseButton.LeftButton)

    assert selections == [expected]
    assert menu.selection_label.text() == f"Selected: {expected}"
    assert menu.isVisible()
    assert menu.player_entry.isVisible()
    assert menu.player_entry.format_label.text() == expected
    assert menu.player_entry.feedback_label.text() == ""


def test_switching_formats_updates_selection(menu: MainMenu) -> None:
    menu.single_button.click()
    menu.player_entry.back_button.click()
    menu.double_button.click()

    assert menu.selection_label.text() == "Selected: Double Elimination"


def test_keyboard_focus_cycles_through_buttons(menu: MainMenu) -> None:
    menu.single_button.setFocus()
    for current, following in [
        (menu.single_button, menu.double_button),
        (menu.double_button, menu.exit_button),
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
    ],
)
def test_keyboard_activates_focused_format(
    menu: MainMenu, button_name: str, expected: str, key: Qt.Key
) -> None:
    button = getattr(menu, button_name)
    button.setFocus()

    QTest.keyClick(button, key)

    assert menu.selection_label.text() == f"Selected: {expected}"
    assert menu.player_entry.isVisible()
    assert menu.player_entry.feedback_label.text() == ""


@pytest.mark.parametrize("width, height", [(360, 320), (480, 400), (900, 700)])
def test_controls_fit_when_resized(
    menu: MainMenu, application: QApplication, width: int, height: int
) -> None:
    menu.resize(width, height)
    application.processEvents()

    for button in [menu.single_button, menu.double_button, menu.exit_button]:
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

    window.return_value.show.assert_called_once_with()
    application.return_value.exec.assert_called_once_with()


def test_player_entry_opens_empty_with_name_field_focused(entry: PlayerEntry) -> None:
    assert entry.name_input.hasFocus()
    assert entry.player_names() == []
    assert entry.count_label.text() == "Players: 0 / 32"
    assert entry.add_button.isEnabled()
    assert not entry.remove_button.isEnabled()


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


@pytest.mark.parametrize("width, height", [(360, 440), (480, 500), (900, 700)])
def test_player_entry_controls_fit_when_resized(
    menu: MainMenu, entry: PlayerEntry, application: QApplication, width: int, height: int
) -> None:
    for index in range(_PLAYER_LIMIT):
        entry.name_input.setText(f"Player {index}")
        entry.add_button.click()
    entry.start_button.click()
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
    entry: PlayerEntry, start_requests: list[tuple[str, list[str], int]]
) -> None:
    for name in ["Alice", "Alice"]:
        entry.name_input.setText(name)
        entry.add_button.click()
    entry.start_button.click()
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
