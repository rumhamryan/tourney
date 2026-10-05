"""The player-entry page used by either tournament format."""

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_MAX_PLAYERS = 32


class PlayerEntry(QWidget):
    """Collect player names without shuffling or starting a tournament."""

    back_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.format_label = QLabel()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter a player's name")
        self.player_list = QListWidget()
        self.player_list.setAccessibleName("Players")
        self.player_list.setMinimumHeight(100)
        self.add_button = QPushButton("&Add")
        self.remove_button = QPushButton("&Remove Selected")
        self.back_button = QPushButton("&Back to Menu")
        self.count_label = QLabel()
        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setMinimumHeight(32)
        self._build_layout()
        self._connect_controls()
        self._update_controls()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        title = QLabel("Players")
        font = title.font()
        font.setPointSize(20)
        font.setBold(True)
        title.setFont(font)
        format_row = QHBoxLayout()
        format_row.addWidget(self.format_label)
        format_row.addStretch()
        format_row.addWidget(self.count_label)
        name_label = QLabel("Player &name:")
        name_label.setBuddy(self.name_input)
        name_row = QHBoxLayout()
        name_row.addWidget(self.name_input)
        name_row.addWidget(self.add_button)
        actions = QHBoxLayout()
        actions.addWidget(self.remove_button)
        actions.addWidget(self.back_button)
        layout.addWidget(title)
        layout.addLayout(format_row)
        layout.addWidget(name_label)
        layout.addLayout(name_row)
        layout.addWidget(self.player_list, 1)
        layout.addWidget(self.feedback_label)
        layout.addLayout(actions)

    def _connect_controls(self) -> None:
        self.name_input.returnPressed.connect(self._add_player)
        self.add_button.clicked.connect(self._add_player)
        self.remove_button.clicked.connect(self._remove_player)
        self.back_button.clicked.connect(self.back_requested.emit)
        self.player_list.itemSelectionChanged.connect(self._update_controls)
        delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.player_list)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self._remove_player)
        for button in [self.add_button, self.remove_button, self.back_button]:
            button.setMinimumHeight(40)
            button.setAutoDefault(False)
            for key in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
                shortcut = QShortcut(QKeySequence(key), button)
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
                shortcut.activated.connect(button.click)
        self.setTabOrder(self.name_input, self.add_button)
        self.setTabOrder(self.add_button, self.player_list)
        self.setTabOrder(self.player_list, self.remove_button)
        self.setTabOrder(self.remove_button, self.back_button)

    def set_format(self, tournament_format: str) -> None:
        """Display the chosen format while preserving the entered names."""
        self.format_label.setText(tournament_format)

    def player_names(self) -> list[str]:
        """Return an independent copy of the names in entry order."""
        names: list[str] = []
        for row in range(self.player_list.count()):
            item = self.player_list.item(row)
            assert item is not None
            names.append(item.text())
        return names

    @Slot()
    def _add_player(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            self.feedback_label.setText("Enter a player name.")
            self.name_input.setFocus()
            return
        if self.player_list.count() >= _MAX_PLAYERS:
            self._update_controls()
            return
        self.player_list.addItem(name)
        self.player_list.setCurrentRow(self.player_list.count() - 1)
        self.name_input.clear()
        self.feedback_label.clear()
        self._update_controls()
        self.name_input.setFocus()

    @Slot()
    def _remove_player(self) -> None:
        for item in self.player_list.selectedItems():
            self.player_list.takeItem(self.player_list.row(item))
        self.feedback_label.clear()
        self._update_controls()

    @Slot()
    def _update_controls(self) -> None:
        count = self.player_list.count()
        self.count_label.setText(f"Players: {count} / {_MAX_PLAYERS}")
        self.add_button.setEnabled(count < _MAX_PLAYERS)
        self.remove_button.setEnabled(bool(self.player_list.selectedItems()))
        if count == _MAX_PLAYERS:
            self.feedback_label.setText("32-player limit reached. Remove a player to add another.")
