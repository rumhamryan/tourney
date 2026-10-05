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
        (entry.back_button, entry.name_input),
    ]:
        assert current.hasFocus()
        QTest.keyClick(current, Qt.Key.Key_Tab)
        assert following.hasFocus()


@pytest.mark.parametrize("width, height", [(360, 440), (480, 500), (900, 700)])
def test_player_entry_controls_fit_when_resized(
    menu: MainMenu, entry: PlayerEntry, application: QApplication, width: int, height: int
) -> None:
    menu.resize(width, height)
    application.processEvents()

    for widget in [
        entry.name_input,
        entry.player_list,
        entry.add_button,
        entry.remove_button,
        entry.back_button,
        entry.feedback_label,
    ]:
        assert widget.isVisible()
        assert entry.rect().contains(widget.geometry())
    assert entry.add_button.width() >= entry.add_button.sizeHint().width()
    assert entry.remove_button.width() >= entry.remove_button.sizeHint().width()
    assert entry.back_button.width() >= entry.back_button.sizeHint().width()


def test_window_closes_from_player_entry(menu: MainMenu, entry: PlayerEntry) -> None:
    assert menu.close()
    assert not menu.isVisible()
    assert not entry.isVisible()
