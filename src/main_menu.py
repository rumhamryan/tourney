"""Launch the Tourney desktop main menu."""

import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QCloseEvent, QFont, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from bracket import shuffle_names
from bracket_preview import build_preview
from bracket_view import BracketView
from player_entry import PlayerEntry
from table_scheduler import SchedulingResult, schedule_tables
from tournament_state import TournamentState, champion_index, record_result
from tournament_storage import load_tournament, save_tournament
from ui_metrics import (
    BODY_POINT_SIZE,
    BUTTON_HEIGHT,
    LAYOUT_SPACING,
    MINIMUM_SCALE,
    PAGE_MARGIN,
    REFERENCE_HEIGHT,
    REFERENCE_WIDTH,
)

_SCALE_CHANGE_THRESHOLD = 0.01


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

        self.single_button = QPushButton("&Single Elimination")
        self.double_button = QPushButton("&Double Elimination")
        self.load_button = QPushButton("&Load Tournament")
        self.exit_button = QPushButton("E&xit")
        self.selection_label = QLabel("")
        self.selection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selection_label.setWordWrap(True)
        self.selection_label.setMinimumHeight(32)
        self._build_layout(self.title_label, subtitle)
        self._apply_scale()

        self.single_button.clicked.connect(self._select_single)
        self.double_button.clicked.connect(self._select_double)
        self.load_button.clicked.connect(self._load_tournament)
        self.exit_button.clicked.connect(self.close)
        self.single_button.setFocus()

    def _init_scheduling(self) -> None:
        self.scheduling_result: SchedulingResult | None = None
        self._schedule_generation = 0
        self._scheduling_threads: set[_SchedulingThread] = set()
        self._closing = False

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
        for button in [self.single_button, self.double_button, self.load_button, self.exit_button]:
            button.setMinimumHeight(40)
            button.setAutoDefault(True)
            layout.addWidget(button)
        layout.addWidget(self.selection_label)
        self.setTabOrder(self.single_button, self.double_button)
        self.setTabOrder(self.double_button, self.load_button)
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
        self.pages = QStackedLayout(self)
        self.pages.setContentsMargins(0, 0, 0, 0)
        self.pages.addWidget(self.menu_page)
        self.pages.addWidget(self.player_entry)
        self.pages.addWidget(self.bracket_view)
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
        self.selection_label.setMinimumHeight(round(32 * scale))
        for button in [self.single_button, self.double_button, self.load_button, self.exit_button]:
            button.setMinimumHeight(round(BUTTON_HEIGHT * scale))
        self.player_entry._apply_scale(scale)
        self.bracket_view._apply_scale(scale)

    @Slot()
    def _select_single(self) -> None:
        self._select_format("Single Elimination")

    @Slot()
    def _select_double(self) -> None:
        self._select_format("Double Elimination")

    def _select_format(self, tournament_format: str) -> None:
        self.selection_label.setText(f"Selected: {tournament_format}")
        self.player_entry.set_format(tournament_format)
        for button in [self.single_button, self.double_button, self.load_button, self.exit_button]:
            button.setDefault(False)
        self.pages.setCurrentWidget(self.player_entry)
        self.player_entry.name_input.setFocus()
        self.format_selected.emit(tournament_format)

    @Slot()
    def _show_menu(self) -> None:
        self.pages.setCurrentWidget(self.menu_page)
        self.single_button.setFocus()

    @Slot(str, list, int)
    def _show_preview(self, tournament_format: str, names: list[str], table_count: int) -> None:
        draw = build_preview(shuffle_names(names), tournament_format)
        self._present_tournament(TournamentState(draw, tuple(names), table_count))

    def _present_tournament(self, state: TournamentState) -> None:
        self.tournament = replace(state, draw_locked=True)
        self.bracket_view.show_tournament(self.tournament)
        for button in [self.single_button, self.double_button, self.load_button, self.exit_button]:
            button.setDefault(False)
        self.pages.setCurrentWidget(self.bracket_view)
        self.bracket_view.graphics.horizontalScrollBar().setValue(0)
        self.bracket_view.graphics.verticalScrollBar().setValue(0)
        self.bracket_view.back_button.setFocus()
        self._schedule_tables()

    def _schedule_tables(self) -> None:
        assert self.tournament is not None
        self._schedule_generation += 1
        self.scheduling_result = None
        self.bracket_view.set_scheduling(True)
        if self.tournament.draw.tournament_format == "Single Elimination":
            self._apply_schedule(schedule_tables(self.tournament), self._schedule_generation)
            return
        worker = _SchedulingThread(self.tournament, self._schedule_generation, self)
        self._scheduling_threads.add(worker)
        worker.scheduled.connect(self._apply_schedule)
        worker.failed.connect(self._schedule_failed)
        worker.finished.connect(self._retire_worker)
        worker.start()

    @Slot(object, int)
    def _apply_schedule(self, result: SchedulingResult, generation: int) -> None:
        if generation != self._schedule_generation or self._closing:
            return
        graphics = self.bracket_view.graphics
        position = (graphics.horizontalScrollBar().value(), graphics.verticalScrollBar().value())
        self.tournament = result.state
        self.scheduling_result = result
        self.bracket_view.set_scheduling(False)
        self.bracket_view.show_tournament(result.state)
        graphics.horizontalScrollBar().setValue(position[0])
        graphics.verticalScrollBar().setValue(position[1])

    @Slot(str, int)
    def _schedule_failed(self, message: str, generation: int) -> None:
        if generation != self._schedule_generation or self._closing:
            return
        self.bracket_view.set_scheduling(False)
        self.bracket_view.status_label.setText(f"Could not schedule matches: {message}")

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
        if self.tournament is None or self.bracket_view.scheduling:
            return
        try:
            self.tournament = record_result(self.tournament, match_id, winner_index)
        except ValueError as error:
            QMessageBox.warning(self, "Could Not Record Result", str(error))
            return
        self._schedule_tables()

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
        if self.tournament is not None and self.tournament.draw_locked:
            self._show_menu()
            return
        self.pages.setCurrentWidget(self.player_entry)
        self.player_entry.name_input.setFocus()

    @Slot()
    def _save_tournament(self) -> None:
        if self.tournament is None:
            return
        selected, _ = QFileDialog.getSaveFileName(
            self, "Save Tournament As", "tournament.json", "Tournament JSON (*.json)"
        )
        if not selected:
            return
        try:
            path = Path(selected)
            needs_suffix = path.suffix.lower() != ".json"
            if needs_suffix:
                path = path.with_name(path.name + ".json")
            if needs_suffix and path.exists() and not self._confirm_overwrite(path):
                return
            save_tournament(path, self.tournament)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Could Not Save Tournament", str(error))
            return
        self.bracket_view.status_label.setText(f"Saved: {path}")

    def _confirm_overwrite(self, path: Path) -> bool:
        answer = QMessageBox.question(
            self,
            "Replace Saved Tournament?",
            f"Replace {path.name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    @Slot()
    def _load_tournament(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "Load Tournament", "", "Tournament JSON (*.json)"
        )
        if not selected:
            return
        try:
            state = load_tournament(Path(selected))
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Could Not Load Tournament", str(error))
            return
        self.player_entry.restore_setup(
            state.draw.tournament_format, state.entry_names, state.table_count
        )
        self.selection_label.setText(f"Selected: {state.draw.tournament_format}")
        self._present_tournament(state)
        if (
            self.tournament is not None
            and not self.bracket_view.scheduling
            and champion_index(self.tournament) is None
        ):
            self.bracket_view.status_label.setText(f"Loaded: {selected}")


def main() -> int:
    """Show the main menu and run the desktop application's event loop."""
    application = QApplication(sys.argv)
    application.setApplicationName("Tourney")
    window = MainMenu()
    window.showMaximized()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
