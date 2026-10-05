from collections.abc import Iterator
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from main_menu import MainMenu, main


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


def test_switching_formats_updates_selection(menu: MainMenu) -> None:
    menu.single_button.click()
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
