"""Launch the Tourney desktop main menu."""

import sys

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout


class MainMenu(QDialog):
    """Choose a tournament format or exit the application."""

    format_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
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
        self.exit_button = QPushButton("E&xit")
        self.selection_label = QLabel("")
        self.selection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selection_label.setWordWrap(True)
        self.selection_label.setMinimumHeight(32)
        self._build_layout(title, subtitle)

        self.single_button.clicked.connect(self._select_single)
        self.double_button.clicked.connect(self._select_double)
        self.exit_button.clicked.connect(self.close)
        self.single_button.setFocus()

    def _build_layout(self, title: QLabel, subtitle: QLabel) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        for button in [self.single_button, self.double_button, self.exit_button]:
            button.setMinimumHeight(40)
            button.setAutoDefault(True)
            layout.addWidget(button)
        layout.addWidget(self.selection_label)
        layout.addStretch()
        self.setTabOrder(self.single_button, self.double_button)
        self.setTabOrder(self.double_button, self.exit_button)

    @Slot()
    def _select_single(self) -> None:
        self._select_format("Single Elimination")

    @Slot()
    def _select_double(self) -> None:
        self._select_format("Double Elimination")

    def _select_format(self, tournament_format: str) -> None:
        self.selection_label.setText(f"Selected: {tournament_format}")
        self.format_selected.emit(tournament_format)


def main() -> int:
    """Show the main menu and run the desktop application's event loop."""
    application = QApplication(sys.argv)
    application.setApplicationName("Tourney")
    window = MainMenu()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
