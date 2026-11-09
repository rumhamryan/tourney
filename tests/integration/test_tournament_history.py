from collections.abc import Iterator
from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QTextEdit

from main_menu import MainMenu
from tournament_file import load_document
from tournament_state import TournamentState
from tournament_storage import save_tournament


@pytest.fixture
def window(monkeypatch: pytest.MonkeyPatch) -> Iterator[MainMenu]:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    menu = MainMenu()
    menu.show()
    yield menu
    menu.close()
    for _ in range(500):
        application.processEvents()
        if not menu._scheduling_threads:
            break
        QTest.qWait(10)
    menu.deleteLater()
    application.processEvents()


def wait(menu: MainMenu) -> None:
    for _ in range(500):
        QApplication.processEvents()
        if not menu.bracket_view.scheduling:
            return
        QTest.qWait(10)
    pytest.fail("Scheduling did not finish")


def start(menu: MainMenu, path: Path, format_: str = "Single Elimination") -> None:
    with (
        patch("main_menu.QFileDialog.getSaveFileName", return_value=(str(path), "")),
        patch("main_menu.shuffle_names", side_effect=lambda names: names),
    ):
        menu._show_preview(format_, ["A", "B", "C", "D"], 2)
    wait(menu)


@pytest.mark.parametrize("format_", ["Single Elimination", "Double Elimination"])
def test_reopen_and_undo_restore_tables(window: MainMenu, tmp_path: Path, format_: str) -> None:
    path = tmp_path / "tournament.json"
    start(window, path, format_)
    original = window.tournament
    window._record_result("W1", 0)
    wait(window)
    assert window._undo_description() == (
        "Do you want to return table 1 assignment from unassigned back to W1?"
    )
    window._record_result("W2", 2)
    wait(window)
    with patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(path), "")):
        window._load_tournament()
    current_box = "L1" if format_ == "Double Elimination" else "unassigned"
    assert window._undo_description() == (
        f"Do you want to return table 2 assignment from {current_box} back to W2?"
    )
    with patch("main_menu.MainMenu._confirm_action", return_value=QMessageBox.StandardButton.Yes):
        window.bracket_view.undo_button.click()
        window.bracket_view.undo_button.click()
    assert window.tournament == original
    assert load_document(path).state == original
    assert not window.bracket_view.undo_button.isEnabled()


@pytest.mark.parametrize("format_", ["Single Elimination", "Double Elimination", "Chip Tournament"])
def test_undo_prompt_identifies_reassigned_table(
    window: MainMenu, tmp_path: Path, format_: str
) -> None:
    path = tmp_path / "tournament.json"
    names = ["A", "B", "C", "D"]
    if format_ == "Chip Tournament":
        window.player_entry.restore_chip_setup(names, [1] * 4, 1)
    with (
        patch("main_menu.QFileDialog.getSaveFileName", return_value=(str(path), "")),
        patch("main_menu.shuffle_names", side_effect=lambda players: players),
        patch("chip_tournament.shuffle"),
    ):
        window._show_preview(format_, names, 1)
    wait(window)
    assert window.document is not None
    original = window.document.state
    if format_ == "Chip Tournament":
        window._record_chip_result("R1M1", 0)
        current_box, last_box = "R1M2", "R1M1"
    else:
        window._record_result("W1", 0)
        wait(window)
        current_box, last_box = "W2", "W1"
    with patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(path), "")):
        window._load_tournament()
    assert window._active_assignments(window.document.state) == {current_box: 1}
    expected = f"Do you want to return table 1 assignment from {current_box} back to {last_box}?"
    with patch(
        "main_menu.MainMenu._confirm_action", return_value=QMessageBox.StandardButton.Yes
    ) as confirm:
        window._undo_result()
    confirm.assert_called_once_with("Undo Last Result?", expected)
    assert window.document.state == original
    assert load_document(path).state == original


def test_start_cancel_and_initial_save_failure_keep_setup(window: MainMenu, tmp_path: Path) -> None:
    window.single_button.click()
    with patch("main_menu.QFileDialog.getSaveFileName", return_value=("", "")):
        window._show_preview("Single Elimination", ["A", "B"], 1)
    assert window.pages.currentWidget() is window.player_entry
    with (
        patch("main_menu.save_document", side_effect=OSError("disk full")),
        patch("main_menu.MainMenu._show_warning") as warning,
    ):
        start(window, tmp_path / "failed.json")
    warning.assert_called_once()
    assert window.pages.currentWidget() is window.player_entry
    assert window.tournament is None


def test_failed_result_and_undo_preserve_memory_and_file(window: MainMenu, tmp_path: Path) -> None:
    path = tmp_path / "tournament.json"
    start(window, path)
    original = window.tournament
    contents = path.read_bytes()
    with (
        patch("main_menu.save_document", side_effect=OSError("disk full")),
        patch("main_menu.MainMenu._show_warning"),
    ):
        window._record_result("W1", 0)
    assert window.tournament is original
    assert path.read_bytes() == contents
    window._record_result("W1", 0)
    completed = window.tournament
    contents = path.read_bytes()
    with (
        patch("main_menu.save_document", side_effect=OSError("disk full")),
        patch("main_menu.MainMenu._show_warning"),
        patch("main_menu.MainMenu._confirm_action", return_value=QMessageBox.StandardButton.Yes),
    ):
        window.bracket_view.undo_button.click()
    assert window.tournament is completed
    assert path.read_bytes() == contents
    assert window.bracket_view.undo_button.isEnabled()


def test_undo_cancel_and_shortcut(window: MainMenu, tmp_path: Path) -> None:
    path = tmp_path / "tournament.json"
    start(window, path)
    original = window.tournament
    window._record_result("W1", 0)
    completed = window.tournament
    with patch("main_menu.MainMenu._confirm_action", return_value=QMessageBox.StandardButton.No):
        window.bracket_view.undo_button.click()
    assert window.tournament is completed
    window.bracket_view.undo_button.setFocus()
    QApplication.processEvents()
    with patch("main_menu.MainMenu._confirm_action", return_value=QMessageBox.StandardButton.Yes):
        QTest.keyClick(
            window.bracket_view.undo_button, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier
        )
    assert window.tournament == original


def test_legacy_file_is_exact_and_viewing_only(window: MainMenu, tmp_path: Path) -> None:
    start(window, tmp_path / "new.json")
    state = window.tournament
    assert isinstance(state, TournamentState)
    path = tmp_path / "legacy.json"
    save_tournament(path, state)
    with patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(path), "")):
        window._load_tournament()
    window._record_result("W1", 0)
    assert window.tournament == state
    assert not window.bracket_view.save_action.isEnabled()
    assert not window.bracket_view.undo_button.isEnabled()
    assert "Viewing only" in window.bracket_view.file_label.text()


def test_chip_round_and_champion_undo_survive_reload(window: MainMenu, tmp_path: Path) -> None:
    path = tmp_path / "chips.json"
    window.player_entry.restore_chip_setup(["Same"] * 4, [1] * 4, 2)
    with (
        patch("main_menu.QFileDialog.getSaveFileName", return_value=(str(path), "")),
        patch("chip_tournament.shuffle"),
    ):
        window._show_preview("Chip Tournament", ["Same"] * 4, 2)
    original = window.chip_tournament
    window._record_chip_result("R1M1", 0)
    with patch("chip_tournament.shuffle"):
        window._record_chip_result("R1M2", 2)
    second_round = window.chip_tournament
    window._record_chip_result("R2M1", 0)
    assert window.chip_view.status_label.text() == "Champion: Same"
    with (
        patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(path), "")),
        patch("chip_tournament.shuffle", side_effect=AssertionError("redraw")),
    ):
        window._load_tournament()
    assert window._undo_description() == (
        "Do you want to return table 1 assignment from unassigned back to R2M1?"
    )
    with patch("main_menu.MainMenu._confirm_action", return_value=QMessageBox.StandardButton.Yes):
        window.chip_view.undo_button.click()
        assert window.chip_tournament == second_round
        description = window._undo_description()
        assert description == (
            "Do you want to return table 2 assignment from unassigned back to R1M2?"
        )
        window.chip_view.undo_button.click()
        window.chip_view.undo_button.click()
    assert window.chip_tournament == original
    assert load_document(path).state == original


def test_save_as_switches_path_only_on_success(window: MainMenu, tmp_path: Path) -> None:
    original = tmp_path / "original.json"
    copy = tmp_path / "copy.json"
    start(window, original)
    window._record_result("W1", 0)
    with (
        patch("main_menu.QFileDialog.getSaveFileName", return_value=(str(copy), "")),
        patch("main_menu.save_document", side_effect=OSError("disk full")),
        patch("main_menu.MainMenu._show_warning"),
    ):
        window._save_tournament()
    assert window.tournament_path == original
    with patch("main_menu.QFileDialog.getSaveFileName", return_value=(str(copy), "")):
        window._save_tournament()
    assert window.tournament_path == copy
    assert load_document(copy) == load_document(original)
    old_contents = original.read_bytes()
    window._record_result("W2", 2)
    assert original.read_bytes() == old_contents
    assert [record.match_id for record in load_document(copy).history] == ["W1", "W2"]


def test_initial_overwrite_cancel_keeps_existing_file(window: MainMenu, tmp_path: Path) -> None:
    path = tmp_path / "existing.json"
    path.write_text("existing", encoding="utf-8")
    with (
        patch("main_menu.QFileDialog.getSaveFileName", return_value=(str(path), "")),
        patch("main_menu.MainMenu._confirm_action", return_value=QMessageBox.StandardButton.No),
        patch("main_menu.shuffle_names") as shuffle,
    ):
        window._show_preview("Single Elimination", ["A", "B"], 1)
    shuffle.assert_not_called()
    assert path.read_text(encoding="utf-8") == "existing"
    assert window.tournament is None


def test_pending_schedule_blocks_actions_and_failure_retains_state(
    window: MainMenu, tmp_path: Path
) -> None:
    path = tmp_path / "tournament.json"
    start(window, path, "Double Elimination")
    original = window.tournament
    contents = path.read_bytes()
    release = Event()

    def fail(state: TournamentState) -> None:
        assert release.wait(timeout=3)
        raise ValueError("scheduler failed")

    with (
        patch("main_menu.schedule_tables", side_effect=fail),
        patch("main_menu.MainMenu._show_warning") as warning,
    ):
        window._record_result("W1", 0)
        try:
            assert window.bracket_view.scheduling
            assert not window.bracket_view.save_action.isEnabled()
            assert not window.bracket_view.undo_button.isEnabled()
            assert not window.bracket_view.back_button.isEnabled()
            window._record_result("W2", 2)
            window._save_tournament()
            window._undo_result()
            assert window.tournament is original
            assert path.read_bytes() == contents
        finally:
            release.set()
            wait(window)
    warning.assert_called_once()
    assert window.tournament is original
    assert path.read_bytes() == contents
    assert window.bracket_view.save_action.isEnabled()


def test_stale_failure_does_not_cancel_current_transaction(
    window: MainMenu, tmp_path: Path
) -> None:
    start(window, tmp_path / "tournament.json")
    document = window.document
    with patch("main_menu.MainMenu._show_warning") as warning:
        window._schedule_failed("old failure", window._schedule_generation - 1)
    warning.assert_not_called()
    assert window.document is document


@pytest.mark.parametrize("page", ["setup", "single", "double", "chip", "legacy"])
@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
def test_return_to_menu_requires_confirmation(
    window: MainMenu, tmp_path: Path, page: str, answer: QMessageBox.StandardButton
) -> None:
    view = (
        window.player_entry
        if page == "setup"
        else window.chip_view
        if page == "chip"
        else window.bracket_view
    )
    if page == "setup":
        window.single_button.click()
    elif page == "chip":
        window.player_entry.restore_chip_setup(["A", "B"], [1, 1], 1)
        with patch(
            "main_menu.QFileDialog.getSaveFileName", return_value=(str(tmp_path / "chip.json"), "")
        ):
            window._show_preview("Chip Tournament", ["A", "B"], 1)
    else:
        format_ = "Double Elimination" if page == "double" else "Single Elimination"
        start(window, tmp_path / "tournament.json", format_)
        if page == "legacy":
            assert isinstance(window.tournament, TournamentState)
            legacy = tmp_path / "legacy.json"
            save_tournament(legacy, window.tournament)
            with patch("main_menu.QFileDialog.getOpenFileName", return_value=(str(legacy), "")):
                window._load_tournament()
    state = (window.tournament, window.chip_tournament, window.document, window.tournament_path)
    contents = window.tournament_path.read_bytes() if window.tournament_path else None
    with patch("main_menu.MainMenu._confirm_action", return_value=answer) as question:
        view.back_button.click()
    question.assert_called_once()
    assert question.call_args.args[0] == "Return to Main Menu?"
    expected = window.menu_page if answer == QMessageBox.StandardButton.Yes else view
    assert window.pages.currentWidget() is expected
    assert state == (
        window.tournament,
        window.chip_tournament,
        window.document,
        window.tournament_path,
    )
    if window.tournament_path:
        assert window.tournament_path.read_bytes() == contents


def test_dismissing_menu_confirmation_keeps_tournament_open(
    window: MainMenu, tmp_path: Path
) -> None:
    start(window, tmp_path / "tournament.json")
    defaults = []

    def dismiss() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        defaults.append(dialog.defaultButton() == dialog.button(QMessageBox.StandardButton.No))
        QTest.keyClick(dialog, Qt.Key.Key_Escape)

    QTimer.singleShot(0, dismiss)
    window.bracket_view.back_button.click()
    assert defaults == [True]
    assert window.pages.currentWidget() is window.bracket_view


def _message_metrics(window: MainMenu, path: Path, action: str) -> tuple[QSize, float]:
    messages = {
        "undo": ("Undo Last Result?", window._undo_description()),
        "menu": ("Return to Main Menu?", "Return to the main menu?"),
        "replace": ("Replace Saved Tournament?", f"Replace {path.name}?"),
        "warning": ("Warning", "Example warning."),
    }
    title, text = messages[action]
    reference = QMessageBox(
        QMessageBox.Icon.Warning if action == "warning" else QMessageBox.Icon.Question,
        title,
        text,
        QMessageBox.StandardButton.Ok
        if action == "warning"
        else QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        window,
    )
    reference.show()
    QApplication.processEvents()
    size = reference.size()
    font_size = reference.font().pointSizeF()
    reference.hide()
    reference.deleteLater()
    return size, font_size


def _request_dialog(window: MainMenu, path: Path, action: str) -> None:
    if action == "undo":
        window.bracket_view.undo_button.click()
    elif action == "replace":
        window._confirm_overwrite(path)
    elif action == "warning":
        window._show_warning("Warning", "Example warning.")
    else:
        window.bracket_view.back_button.click()


@pytest.mark.parametrize("action", ["undo", "menu", "replace", "warning"])
def test_operator_dialogs_scale_their_natural_size_without_large_empty_boxes(
    window: MainMenu, tmp_path: Path, action: str
) -> None:
    start(window, tmp_path / "tournament.json")
    window._record_result("W1", 0)
    original_size, original_font = _message_metrics(window, tmp_path / "tournament.json", action)
    sizes = []
    fonts: list[float] = []
    buttons_fit: list[bool] = []
    defaults = []

    def inspect_and_cancel() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        sizes.append(dialog.size())
        fonts.extend(
            label.font().pointSizeF() for label in dialog.findChildren(QLabel) if label.text()
        )
        fonts.extend(button.font().pointSizeF() for button in dialog.buttons())
        fonts.extend(editor.font().pointSizeF() for editor in dialog.findChildren(QTextEdit))
        buttons_fit.extend(
            button.width() >= button.sizeHint().width() for button in dialog.buttons()
        )
        default = (
            QMessageBox.StandardButton.Ok if action == "warning" else QMessageBox.StandardButton.No
        )
        defaults.append(dialog.defaultButton() == dialog.button(default))
        dialog.button(default).click()

    QTimer.singleShot(0, inspect_and_cancel)
    _request_dialog(window, tmp_path / "tournament.json", action)
    assert (
        round(original_size.width() * 1.5)
        <= sizes[0].width()
        <= round(original_size.width() * 1.5) + 32
    )
    assert (
        round(original_size.height() * 1.5)
        <= sizes[0].height()
        <= round(original_size.height() * 1.5) + 100
    )
    assert fonts and all(font == pytest.approx(original_font * 1.5) for font in fonts)
    assert all(buttons_fit)
    assert defaults == [True]
    assert window.pages.currentWidget() is window.bracket_view


@pytest.mark.parametrize(
    "text",
    [
        "Disk full.",
        "A file error with <literal text> and & symbols.\n" * 3,
        "A longer file error with <literal text> and & symbols. " * 12,
    ],
)
def test_error_messages_keep_native_labels_and_readable_text(
    window: MainMenu, tmp_path: Path, text: str
) -> None:
    start(window, tmp_path / "tournament.json")
    messages = []
    readable = []
    text_editors = []

    def inspect_and_close() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        label = dialog.findChild(QLabel, "qt_msgbox_label")
        assert label is not None
        assert dialog.textFormat() == Qt.TextFormat.PlainText
        messages.append(label.text())
        # Qt chooses wrapping based on the platform's fonts, style, and available width.
        readable.append(
            label.wordWrap()
            or all(
                label.fontMetrics().horizontalAdvance(line) <= label.contentsRect().width()
                for line in text.splitlines()
            )
        )
        text_editors.append(bool(dialog.findChildren(QTextEdit)))
        dialog.button(QMessageBox.StandardButton.Ok).click()

    QTimer.singleShot(0, inspect_and_close)
    window._show_warning("Could Not Save Tournament", text)
    assert messages == [text]
    assert readable == [True]
    assert text_editors == [False]
