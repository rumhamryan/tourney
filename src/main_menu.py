"""Launch the Tourney desktop main menu."""

import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import (
    QCloseEvent,
    QFont,
    QKeySequence,
    QResizeEvent,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from bracket import shuffle_names
from bracket_preview import build_preview
from bracket_view import BracketView, _display_match_id
from chip_tournament import ChipTournament
from chip_tournament import record_result as record_chip_result
from chip_tournament import start_tournament as start_chip_tournament
from chip_view import ChipView
from player_entry import PlayerEntry
from table_scheduler import SchedulingResult, schedule_tables
from tournament_file import (
    ResultRecord,
    TournamentDocument,
    TournamentSnapshot,
    read_tournament_file,
    save_document,
    undo_result,
)
from tournament_state import TournamentState, record_result
from ui_metrics import (
    BODY_POINT_SIZE,
    BUTTON_HEIGHT,
    LAYOUT_SPACING,
    MINIMUM_SCALE,
    OPERATOR_DIALOG_SCALE,
    PAGE_MARGIN,
    REFERENCE_HEIGHT,
    REFERENCE_WIDTH,
)

_SCALE_CHANGE_THRESHOLD = 0.01


class _MessageDialog(QMessageBox):
    """Enlarge standard message boxes while preserving their natural proportions."""

    def __init__(self, title: str, text: str, parent: QWidget, *, warning: bool = False) -> None:
        super().__init__(
            QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Question,
            title,
            text,
            QMessageBox.StandardButton.Ok
            if warning
            else QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            parent,
        )
        self.setDefaultButton(
            QMessageBox.StandardButton.Ok if warning else QMessageBox.StandardButton.No
        )
        self.setTextFormat(Qt.TextFormat.PlainText)
        self._enlarged = False

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._enlarged:
            return
        self._enlarged = True
        original = self.size()
        button_sizes = [button.sizeHint() for button in self.buttons()]
        font = QFont(self.font())
        font.setPointSizeF(font.pointSizeF() * OPERATOR_DIALOG_SCALE)
        self.setFont(font)
        for button, size in zip(self.buttons(), button_sizes, strict=True):
            button.setMinimumSize(
                round(size.width() * OPERATOR_DIALOG_SCALE),
                round(size.height() * OPERATOR_DIALOG_SCALE),
            )
        self._enlarge_layout(
            round(original.width() * OPERATOR_DIALOG_SCALE),
            round(original.height() * OPERATOR_DIALOG_SCALE),
        )

    def _enlarge_layout(self, width: int, height: int) -> None:
        layout = self.layout()
        assert isinstance(layout, QGridLayout)
        margins = layout.contentsMargins()
        layout.setContentsMargins(
            round(margins.left() * OPERATOR_DIALOG_SCALE),
            round(margins.top() * OPERATOR_DIALOG_SCALE),
            round(margins.right() * OPERATOR_DIALOG_SCALE),
            round(margins.bottom() * OPERATOR_DIALOG_SCALE),
        )
        layout.setSpacing(round(layout.spacing() * OPERATOR_DIALOG_SCALE))
        margins = layout.contentsMargins()
        spacer = QSpacerItem(
            max(0, width - margins.left() - margins.right()),
            max(0, height - layout.minimumSize().height() - layout.verticalSpacing()),
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Minimum,
        )
        # Keep Qt's message-box sizing while reserving the requested enlargement.
        layout.addItem(spacer, layout.rowCount(), 0, 1, layout.columnCount())
        layout.activate()
        self.setMinimumSize(width, height)


class _SchedulingThread(QThread):
    scheduled = Signal(object, int)
    failed = Signal(str, int)

    def __init__(self, state: TournamentState, generation: int, parent: QWidget) -> None:
        super().__init__(parent)
        self._state = state
        self._generation = generation

    def run(self) -> None:
        try:
            result = schedule_tables(self._state)
        except Exception as error:
            self.failed.emit(str(error), self._generation)
        else:
            self.scheduled.emit(result, self._generation)


class MainMenu(QDialog):
    """Choose a tournament format or exit the application."""

    format_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.tournament: TournamentState | None = None
        self._init_scheduling()
        self._ui_scale = -1.0
        self.setWindowTitle("Tourney")
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumSize(640, 600)
        self.resize(1280, 800)

        self.title_label = QLabel("Tourney")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("Choose a tournament format.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._build_menu_buttons()
        self._build_layout(self.title_label, subtitle)
        self._apply_scale()

        self.single_button.setFocus()

    def _build_menu_buttons(self) -> None:
        self.single_button = QPushButton("&Single Elimination")
        self.double_button = QPushButton("&Double Elimination")
        self.chip_button = QPushButton("&Chip Tournament")
        self.load_button = QPushButton("&Load Tournament")
        self.exit_button = QPushButton("E&xit")
        self.single_button.clicked.connect(self._select_single)
        self.double_button.clicked.connect(self._select_double)
        self.chip_button.clicked.connect(self._select_chip)
        self.load_button.clicked.connect(self._load_tournament)
        self.exit_button.clicked.connect(self.close)

    def _menu_buttons(self) -> tuple[QPushButton, ...]:
        return (
            self.single_button,
            self.double_button,
            self.chip_button,
            self.load_button,
            self.exit_button,
        )

    def _init_scheduling(self) -> None:
        self._pending_reset_zoom = False
        self.chip_tournament: ChipTournament | None = None
        self.scheduling_result: SchedulingResult | None = None
        self._schedule_generation = 0
        self._scheduling_threads: set[_SchedulingThread] = set()
        self._closing = False
        self.document: TournamentDocument | None = None
        self.tournament_path: Path | None = None
        self._pending_document: TournamentDocument | None = None
        self._pending_path: Path | None = None
        self._pending_status = ""
        self._saving = False

    def _build_layout(self, title: QLabel, subtitle: QLabel) -> None:
        self.menu_page = QWidget()
        self._menu_layout = QVBoxLayout(self.menu_page)
        self._menu_content = QWidget()
        self._menu_content.setFixedWidth(540)
        self._menu_content_layout = QVBoxLayout(self._menu_content)
        layout = self._menu_content_layout
        layout.setContentsMargins(0, 0, 0, 0)
        self._menu_layout.addStretch()
        self._menu_layout.addWidget(self._menu_content, 0, Qt.AlignmentFlag.AlignHCenter)
        self._menu_layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        for button in self._menu_buttons():
            button.setMinimumHeight(40)
            button.setAutoDefault(True)
            layout.addWidget(button)
        self.setTabOrder(self.single_button, self.double_button)
        self.setTabOrder(self.double_button, self.chip_button)
        self.setTabOrder(self.chip_button, self.load_button)
        self.setTabOrder(self.load_button, self.exit_button)
        self._build_pages()

    def _build_pages(self) -> None:
        self.player_entry = PlayerEntry()
        self.player_entry.back_requested.connect(self._show_menu)
        self.player_entry.start_requested.connect(self._show_preview)
        self.bracket_view = BracketView()
        self.bracket_view.back_requested.connect(self._show_setup)
        self.bracket_view.save_requested.connect(self._save_tournament)
        self.bracket_view.result_requested.connect(self._record_result)
        self.bracket_view.undo_requested.connect(self._undo_result)
        self.chip_view = ChipView()
        self.chip_view.back_requested.connect(self._show_menu)
        self.chip_view.save_requested.connect(self._save_tournament)
        self.chip_view.result_requested.connect(self._record_chip_result)
        self.chip_view.undo_requested.connect(self._undo_result)
        self.pages = QStackedLayout(self)
        self.pages.setContentsMargins(0, 0, 0, 0)
        self.pages.addWidget(self.menu_page)
        self.pages.addWidget(self.player_entry)
        self.pages.addWidget(self.bracket_view)
        self.pages.addWidget(self.chip_view)
        self.setMinimumSize(self.minimumSize().expandedTo(self.pages.minimumSize()))
        shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Open), self.menu_page)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.load_button.click)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Scale controls against the full-HD reference as the window changes."""
        super().resizeEvent(event)
        if hasattr(self, "pages"):
            self._apply_scale()

    def _apply_scale(self) -> None:
        scale = max(
            MINIMUM_SCALE,
            min(1.0, self.width() / REFERENCE_WIDTH, self.height() / REFERENCE_HEIGHT),
        )
        if abs(scale - self._ui_scale) < _SCALE_CHANGE_THRESHOLD:
            return
        self._ui_scale = scale
        font = QFont(self.font())
        font.setPointSizeF(BODY_POINT_SIZE * scale)
        self.setFont(font)
        heading = QFont(font)
        heading.setPointSizeF(40 * scale)
        heading.setBold(True)
        self.title_label.setFont(heading)
        self._menu_content.setFixedWidth(round(720 * scale))
        self._menu_content_layout.setSpacing(round(LAYOUT_SPACING * scale))
        margin = round(PAGE_MARGIN * scale)
        self._menu_layout.setContentsMargins(margin, margin, margin, margin)
        for button in self._menu_buttons():
            button.setMinimumHeight(round(BUTTON_HEIGHT * scale))
        self.player_entry._apply_scale(scale)
        self.bracket_view._apply_scale(scale)
        self.chip_view._apply_scale(scale)

    @Slot()
    def _select_single(self) -> None:
        self._select_format("Single Elimination")

    @Slot()
    def _select_double(self) -> None:
        self._select_format("Double Elimination")

    @Slot()
    def _select_chip(self) -> None:
        self._select_format("Chip Tournament")

    def _select_format(self, tournament_format: str) -> None:
        self.player_entry.set_format(tournament_format)
        for button in self._menu_buttons():
            button.setDefault(False)
        self.pages.setCurrentWidget(self.player_entry)
        self.player_entry.name_input.setFocus()
        self.format_selected.emit(tournament_format)

    @Slot()
    def _show_menu(self) -> None:
        if self._pending_document is not None or self._saving:
            return
        if self.pages.currentWidget() is not self.menu_page:
            answer = self._confirm_action("Return to Main Menu?", "Return to the main menu?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.pages.setCurrentWidget(self.menu_page)
        self.single_button.setFocus()

    @Slot(str, list, int)
    def _show_preview(self, tournament_format: str, names: list[str], table_count: int) -> None:
        if self._pending_document is not None or self._saving:
            return
        path = self._choose_tournament_path("Create Tournament File")
        if path is None:
            return
        if tournament_format == "Chip Tournament":
            counts = [
                count for count in self.player_entry.player_chip_counts() if count is not None
            ]
            try:
                candidate = TournamentDocument(start_chip_tournament(names, counts, table_count))
                self._commit_document(candidate, path)
            except ValueError as error:
                self._show_warning("Could Not Start Tournament", str(error))
            return
        draw = build_preview(shuffle_names(names), tournament_format)
        self._pending_document = TournamentDocument(
            TournamentState(draw, tuple(names), table_count, draw_locked=True)
        )
        self._pending_path = path
        self._pending_reset_zoom = True
        self._schedule_tables()

    def _present_tournament(self, state: TournamentState) -> None:
        self.chip_tournament = None
        self.tournament = state
        self.bracket_view.show_tournament(self.tournament)
        for button in self._menu_buttons():
            button.setDefault(False)
        self.pages.setCurrentWidget(self.bracket_view)
        self.bracket_view.graphics.horizontalScrollBar().setValue(0)
        self.bracket_view.graphics.verticalScrollBar().setValue(0)
        self.bracket_view.back_button.setFocus()

    def _present_chip_tournament(self, state: ChipTournament) -> None:
        self._schedule_generation += 1
        self.tournament = None
        self.scheduling_result = None
        self.bracket_view.set_scheduling(False)
        self.chip_tournament = state
        self.chip_view.show_tournament(self.chip_tournament)
        for button in self._menu_buttons():
            button.setDefault(False)
        self.pages.setCurrentWidget(self.chip_view)
        self.chip_view.back_button.setFocus()

    @Slot(str, int)
    def _record_chip_result(self, match_id: str, winner_index: int) -> None:
        if (
            self.chip_tournament is None
            or self.document is None
            or self._pending_document
            or self._saving
        ):
            return
        try:
            updated = record_chip_result(self.chip_tournament, match_id, winner_index)
        except ValueError as error:
            self._show_warning("Could Not Record Result", str(error))
            return
        self._save_result(match_id, winner_index, updated)

    def _save_result(self, match_id: str, winner_index: int, updated: TournamentSnapshot) -> None:
        assert self.document is not None and self.tournament_path is not None
        candidate = TournamentDocument(
            updated,
            (*self.document.history, ResultRecord(match_id, winner_index, self.document.state)),
        )
        if isinstance(updated, TournamentState):
            self._pending_document = candidate
            self._pending_path = self.tournament_path
            self._schedule_tables()
        else:
            self._commit_document(candidate, self.tournament_path)

    def _schedule_tables(self) -> None:
        assert self._pending_document is not None
        state = self._pending_document.state
        assert isinstance(state, TournamentState)
        self._schedule_generation += 1
        self._pending_status = self.bracket_view.status_label.text()
        self.bracket_view.set_scheduling(True)
        self._update_file_controls()
        if state.draw.tournament_format == "Single Elimination":
            try:
                result = schedule_tables(state)
            except Exception as error:
                self._schedule_failed(str(error), self._schedule_generation)
            else:
                self._apply_schedule(result, self._schedule_generation)
            return
        worker = _SchedulingThread(state, self._schedule_generation, self)
        self._scheduling_threads.add(worker)
        worker.scheduled.connect(self._apply_schedule)
        worker.failed.connect(self._schedule_failed)
        worker.finished.connect(self._retire_worker)
        worker.start()

    @Slot(object, int)
    def _apply_schedule(self, result: SchedulingResult, generation: int) -> None:
        if generation != self._schedule_generation or self._closing:
            return
        if self._pending_document is None or self._pending_path is None:
            return
        graphics = self.bracket_view.graphics
        reset_zoom = self._pending_reset_zoom
        position = (graphics.horizontalScrollBar().value(), graphics.verticalScrollBar().value())
        candidate = replace(self._pending_document, state=result.state)
        if self._commit_document(candidate, self._pending_path):
            self.scheduling_result = result
        self._finish_pending()
        if not reset_zoom:
            graphics.horizontalScrollBar().setValue(position[0])
            graphics.verticalScrollBar().setValue(position[1])

    @Slot(str, int)
    def _schedule_failed(self, message: str, generation: int) -> None:
        if generation != self._schedule_generation or self._closing or not self._pending_document:
            return
        self._finish_pending()
        self._show_warning("Could Not Schedule Matches", message)

    @Slot()
    def _retire_worker(self) -> None:
        worker = self.sender()
        assert isinstance(worker, _SchedulingThread)
        self._scheduling_threads.discard(worker)
        worker.deleteLater()
        if self._closing and not self._scheduling_threads:
            self.close()

    @Slot(str, int)
    def _record_result(self, match_id: str, winner_index: int) -> None:
        if (
            self.tournament is None
            or self.document is None
            or self.bracket_view.scheduling
            or self._saving
        ):
            return
        try:
            updated = record_result(self.tournament, match_id, winner_index)
        except ValueError as error:
            self._show_warning("Could Not Record Result", str(error))
            return
        self._save_result(match_id, winner_index, updated)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Let bounded native solves finish before their QThreads are destroyed."""
        self._closing = True
        self._schedule_generation += 1
        if self._scheduling_threads:
            self.setEnabled(False)
            event.ignore()
        else:
            self.done(QDialog.DialogCode.Rejected)
            event.accept()

    def reject(self) -> None:
        """Route Escape through the same worker cleanup as closing the window."""
        self.close()

    @Slot()
    def _show_setup(self) -> None:
        if self.tournament is not None and (self.tournament.draw_locked or self.document is None):
            self._show_menu()
            return
        self.pages.setCurrentWidget(self.player_entry)
        self.player_entry.name_input.setFocus()

    def _choose_tournament_path(self, title: str) -> Path | None:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            title,
            str(self.tournament_path or "tournament.json"),
            "Tournament JSON (*.json)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not selected:
            return None
        path = Path(selected)
        if path.suffix.lower() != ".json":
            path = path.with_name(path.name + ".json")
        if path.exists() and not self._confirm_overwrite(path):
            return None
        return path

    def _commit_document(self, candidate: TournamentDocument, path: Path) -> bool:
        self._saving = True
        self._update_file_controls()
        try:
            save_document(path, candidate)
        except (OSError, ValueError) as error:
            self._show_warning("Could Not Save Tournament", str(error))
            return False
        finally:
            self._saving = False
            self._update_file_controls()
        self.document = candidate
        self.tournament_path = path
        self.bracket_view.set_scheduling(False)
        if self._pending_reset_zoom:
            self.bracket_view.reset_zoom()
        self._present_snapshot(candidate.state)
        self._update_file_controls()
        return True

    def _present_snapshot(self, state: TournamentSnapshot) -> None:
        if isinstance(state, ChipTournament):
            self._present_chip_tournament(state)
        else:
            self._present_tournament(state)

    def _finish_pending(self) -> None:
        if self.bracket_view.scheduling:
            self.bracket_view.status_label.setText(self._pending_status)
        self._pending_document = None
        self._pending_path = None
        self._pending_reset_zoom = False
        self.bracket_view.set_scheduling(False)
        self._update_file_controls()
        if self.pages.currentWidget() is self.bracket_view:
            self.bracket_view.back_button.setFocus()

    def _update_file_controls(self) -> None:
        busy = self._pending_document is not None or self._saving
        editable = self.document is not None
        for view in (self.bracket_view, self.chip_view):
            view.read_only = not editable
            view.save_action.setEnabled(editable and not busy)
            view.undo_button.setEnabled(bool(self.document and self.document.history) and not busy)
            view.back_button.setEnabled(not busy)
            text = (
                f"Tournament file: {self.tournament_path}"
                if editable
                else "Viewing only: legacy JSON"
            )
            view.file_label.setText(text)
            if not editable:
                view.back_button.setText("&Back to Menu")
        self.chip_view.busy = busy
        assignments = self._active_assignments(self.chip_tournament) if self.chip_tournament else {}
        for identifier, card in self.chip_view.match_cards.items():
            card.setEnabled(editable and not busy and identifier in assignments)
        self.player_entry.setEnabled(not busy)
        for button in self._menu_buttons():
            button.setEnabled(not busy)

    @Slot()
    def _undo_result(self) -> None:
        if (
            self.document is None
            or not self.document.history
            or self._pending_document
            or self._saving
        ):
            return
        answer = self._confirm_action("Undo Last Result?", self._undo_description())
        if answer != QMessageBox.StandardButton.Yes:
            return
        assert self.tournament_path is not None
        self._commit_document(undo_result(self.document), self.tournament_path)

    def _confirm_action(self, title: str, text: str) -> QMessageBox.StandardButton:
        dialog = _MessageDialog(title, text, self)
        dialog.exec()
        button = dialog.clickedButton()
        answer = (
            dialog.standardButton(button) if button is not None else QMessageBox.StandardButton.No
        )
        dialog.deleteLater()
        return answer

    def _show_warning(self, title: str, text: str) -> None:
        dialog = _MessageDialog(title, text, self, warning=True)
        dialog.exec()
        dialog.deleteLater()

    def _undo_description(self) -> str:
        assert self.document is not None
        record = self.document.history[-1]
        table = self._active_assignments(record.before)[record.match_id]
        current_box = next(
            (
                identifier
                for identifier, number in self._active_assignments(self.document.state).items()
                if number == table
            ),
            "unassigned",
        )
        return (
            f"Do you want to return table {table} assignment from {_display_match_id(current_box)} "
            f"back to {_display_match_id(record.match_id)}?"
        )

    @staticmethod
    def _active_assignments(state: TournamentSnapshot) -> dict[str, int]:
        if isinstance(state, TournamentState):
            return {
                item.match_id: item.table_number
                for item in state.progress
                if item.status == "in_progress" and item.table_number is not None
            }
        return {
            match.identifier: match.table_number
            for match in state.rounds[-1].matches
            if match.table_number is not None
        }

    @Slot()
    def _save_tournament(self) -> None:
        if self.document is None or self._pending_document or self._saving:
            return
        path = self._choose_tournament_path("Save Tournament As")
        if path is None:
            return
        self._saving = True
        self._update_file_controls()
        try:
            self._write_tournament(path)
        except (OSError, ValueError) as error:
            self._show_warning("Could Not Save Tournament", str(error))
            return
        finally:
            self._saving = False
            self._update_file_controls()
        self.tournament_path = path
        self._update_file_controls()

    def _write_tournament(self, path: Path) -> None:
        assert self.document is not None
        save_document(path, self.document)

    def _confirm_overwrite(self, path: Path) -> bool:
        answer = self._confirm_action("Replace Saved Tournament?", f"Replace {path.name}?")
        return answer == QMessageBox.StandardButton.Yes

    @Slot()
    def _load_tournament(self) -> None:
        if self._pending_document or self._saving:
            return
        selected, _ = QFileDialog.getOpenFileName(
            self, "Load Tournament", "", "Tournament JSON (*.json)"
        )
        if not selected:
            return
        try:
            loaded = read_tournament_file(Path(selected))
        except (OSError, ValueError) as error:
            self._show_warning("Could Not Load Tournament", str(error))
            return
        self._schedule_generation += 1
        self.document = loaded if isinstance(loaded, TournamentDocument) else None
        self.tournament_path = Path(selected)
        state = loaded.state if isinstance(loaded, TournamentDocument) else loaded
        self.bracket_view.set_scheduling(False)
        self._restore_setup(state)
        if isinstance(state, TournamentState):
            self.bracket_view.reset_zoom()
        self._present_snapshot(state)
        self._update_file_controls()

    def _restore_setup(self, state: TournamentSnapshot) -> None:
        if isinstance(state, ChipTournament):
            self.player_entry.restore_chip_setup(
                [player.name for player in state.players],
                [player.starting_chips for player in state.players],
                state.table_count,
            )
            return
        self.player_entry.restore_setup(
            state.draw.tournament_format, state.entry_names, state.table_count
        )

    def _read_tournament(self, path: Path) -> TournamentState | ChipTournament:
        loaded = read_tournament_file(path)
        return loaded.state if isinstance(loaded, TournamentDocument) else loaded


def main() -> int:
    """Show the main menu and run the desktop application's event loop."""
    application = QApplication(sys.argv)
    application.setApplicationName("Tourney")
    window = MainMenu()
    window.showMaximized()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
