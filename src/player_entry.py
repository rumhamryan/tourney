"""The tournament-setup page used by either tournament format."""

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

_MAX_PLAYERS = 32
_MIN_PLAYERS = 2


class PlayerEntry(QWidget):
    """Collect player names and a table count for the selected format."""

    back_requested = Signal()
    start_requested = Signal(str, list, int)

    def __init__(self) -> None:
        super().__init__()
        self.format_label = QLabel()
        self.table_count_input = QSpinBox()
        self.table_count_input.setRange(1, 2**31 - 1)
        self.table_count_input.setKeyboardTracking(False)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter a player's name")
        self.player_list = QListWidget()
        self.player_list.setAccessibleName("Players")
        self.player_list.setMinimumHeight(100)
        self.add_button = QPushButton("&Add")
        self.remove_button = QPushButton("&Remove Selected")
        self.back_button = QPushButton("&Back to Menu")
        self.start_button = QPushButton("&Start")
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
        title = QLabel("Tournament Setup")
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
        layout.addLayout(self._table_row())
        layout.addWidget(name_label)
        layout.addLayout(name_row)
        layout.addWidget(self.player_list, 1)
        layout.addWidget(self.feedback_label)
        layout.addLayout(actions)
        layout.addWidget(self.start_button)

    def _table_row(self) -> QHBoxLayout:
        label = QLabel("Number of &tables:")
        label.setBuddy(self.table_count_input)
        row = QHBoxLayout()
        row.addWidget(label)
        row.addWidget(self.table_count_input)
        row.addStretch()
        return row

    def _connect_controls(self) -> None:
        self.name_input.returnPressed.connect(self._add_player)
        self.add_button.clicked.connect(self._add_player)
        self.remove_button.clicked.connect(self._remove_player)
        self.back_button.clicked.connect(self.back_requested.emit)
        self.start_button.clicked.connect(self._request_start)
        self.name_input.textChanged.connect(self._update_start_button)
        self.table_count_input.valueChanged.connect(self._update_start_button)
        self.player_list.itemSelectionChanged.connect(self._update_controls)
        delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.player_list)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self._remove_player)
        for button in [self.add_button, self.remove_button, self.back_button, self.start_button]:
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
        self.setTabOrder(self.back_button, self.start_button)
        self.setTabOrder(self.start_button, self.table_count_input)
        self.setTabOrder(self.table_count_input, self.name_input)

    def set_format(self, tournament_format: str) -> None:
        """Display the chosen format while preserving the entered names."""
        self.format_label.setText(tournament_format)
        self._update_start_button()

    def player_names(self) -> list[str]:
        """Return an independent copy of the names in entry order."""
        names: list[str] = []
        for row in range(self.player_list.count()):
            item = self.player_list.item(row)
            assert item is not None
            names.append(item.text())
        return names

    def table_count(self) -> int:
        """Return the current valid table count for the future table panel."""
        self.table_count_input.interpretText()
        return self.table_count_input.value()

    @Slot()
    def _request_start(self) -> None:
        self._update_start_button()
        if not self.start_button.isEnabled():
            return
        names = self.player_names()
        tournament_format = self.format_label.text()
        table_count = self.table_count()
        table_word = "table" if table_count == 1 else "tables"
        self.feedback_label.setText(
            f"Setup confirmed: {tournament_format}, {len(names)} players, "
            f"{table_count} {table_word}."
        )
        self.start_requested.emit(tournament_format, names, table_count)

    @Slot()
    def _update_start_button(self) -> None:
        count = self.player_list.count()
        pending_name = bool(self.name_input.text().strip())
        self.start_button.setEnabled(
            _MIN_PLAYERS <= count <= _MAX_PLAYERS
            and not pending_name
            and bool(self.format_label.text())
        )
        if count < _MIN_PLAYERS:
            self.start_button.setToolTip("Add at least two players to start.")
        elif pending_name:
            self.start_button.setToolTip("Add the entered name before starting.")
        else:
            self.start_button.setToolTip("Confirm tournament setup.")
        if self.feedback_label.text().startswith("Setup confirmed:"):
            self.feedback_label.clear()

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
        self._update_start_button()
        if count == _MAX_PLAYERS:
            self.feedback_label.setText("32-player limit reached. Remove a player to add another.")
