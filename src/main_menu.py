"""Launch the Tourney desktop main menu."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
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
from tournament_state import TournamentState
from tournament_storage import load_tournament, save_tournament


class MainMenu(QDialog):
    """Choose a tournament format or exit the application."""

    format_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.tournament: TournamentState | None = None
        self.setWindowTitle("Tourney")
        self.setMinimumSize(360, 320)
        self.resize(480, 400)

        title = QLabel("Tourney")
        font = title.font()
        font.setPointSize(24)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        self._build_layout(title, subtitle)

        self.single_button.clicked.connect(self._select_single)
        self.double_button.clicked.connect(self._select_double)
        self.load_button.clicked.connect(self._load_tournament)
        self.exit_button.clicked.connect(self.close)
        self.single_button.setFocus()

    def _build_layout(self, title: QLabel, subtitle: QLabel) -> None:
        self.menu_page = QWidget()
        layout = QVBoxLayout(self.menu_page)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        for button in [self.single_button, self.double_button, self.load_button, self.exit_button]:
            button.setMinimumHeight(40)
            button.setAutoDefault(True)
            layout.addWidget(button)
        layout.addWidget(self.selection_label)
        layout.addStretch()
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
        self.pages = QStackedLayout(self)
        self.pages.setContentsMargins(0, 0, 0, 0)
        self.pages.addWidget(self.menu_page)
        self.pages.addWidget(self.player_entry)
        self.pages.addWidget(self.bracket_view)
        self.setMinimumSize(self.minimumSize().expandedTo(self.pages.minimumSize()))
        shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Open), self.menu_page)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.load_button.click)

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
        self._setup_size = self.size()
        self._present_tournament(TournamentState(draw, tuple(names), table_count))

    def _present_tournament(self, state: TournamentState) -> None:
        self.bracket_view.show_tournament(state)
        self.tournament = state
        for button in [self.single_button, self.double_button, self.load_button, self.exit_button]:
            button.setDefault(False)
        self.pages.setCurrentWidget(self.bracket_view)
        self.resize(max(self.width(), 1000), max(self.height(), 700))
        self.bracket_view.graphics.horizontalScrollBar().setValue(0)
        self.bracket_view.graphics.verticalScrollBar().setValue(0)
        self.bracket_view.back_button.setFocus()

    @Slot()
    def _show_setup(self) -> None:
        if self.tournament is not None and self.tournament.draw_locked:
            self._show_menu()
            return
        self.pages.setCurrentWidget(self.player_entry)
        self.resize(self._setup_size)
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
        self._setup_size = self.size()
        self.player_entry.restore_setup(
            state.draw.tournament_format, state.entry_names, state.table_count
        )
        self.selection_label.setText(f"Selected: {state.draw.tournament_format}")
        self._present_tournament(state)
        self.bracket_view.status_label.setText(f"Loaded: {selected}")


def main() -> int:
    """Show the main menu and run the desktop application's event loop."""
    application = QApplication(sys.argv)
    application.setApplicationName("Tourney")
    window = MainMenu()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
