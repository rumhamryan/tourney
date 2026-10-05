"""Collect players and format-specific settings before a tournament starts."""

from collections.abc import Sequence

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Qt, Signal, Slot
from PySide6.QtGui import QFont, QIntValidator, QKeySequence, QPainter, QPalette, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ui_metrics import (
    BUTTON_HEIGHT,
    INPUT_HEIGHT,
    LAYOUT_SPACING,
    PAGE_MARGIN,
    PAGE_TITLE_POINT_SIZE,
    PLAYER_ROW_HEIGHT,
)

_MAX_PLAYERS = 32
_MIN_PLAYERS = 2
_MAX_CHIPS = 2**31 - 1


class _ChipCountDelegate(QStyledItemDelegate):
    """Keep player names and chip counts in aligned columns in the shared roster."""

    enabled = False

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        if not self.enabled or option.widget is None:
            super().paint(painter, option, index)
            return
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        name = item.text
        chips = index.data(Qt.ItemDataRole.UserRole)
        count = "Chips not set" if chips is None else f"{chips} chip" + ("s" if chips != 1 else "")
        item.text = ""
        option.widget.style().drawControl(
            QStyle.ControlElement.CE_ItemViewItem, item, painter, item.widget
        )
        rectangle = item.rect.adjusted(12, 0, -12, 0)
        count_width = item.fontMetrics.horizontalAdvance(count)
        name_rectangle = rectangle.adjusted(0, 0, -count_width - 24, 0)
        color = (
            QPalette.ColorRole.HighlightedText
            if item.state & QStyle.StateFlag.State_Selected
            else QPalette.ColorRole.Text
        )
        painter.save()
        painter.setFont(item.font)
        painter.setPen(item.palette.color(color))
        painter.drawText(
            name_rectangle,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            item.fontMetrics.elidedText(name, Qt.TextElideMode.ElideRight, name_rectangle.width()),
        )
        painter.drawText(
            rectangle, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, count
        )
        painter.restore()


class PlayerEntry(QWidget):
    """Collect player names and a table count for the selected format."""

    back_requested = Signal()
    start_requested = Signal(str, list, int)

    def __init__(self) -> None:
        super().__init__()
        self._row_height = round(PLAYER_ROW_HEIGHT * 0.75)
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
        self._build_chip_controls()
        self._build_layout()
        self._connect_controls()
        self._update_controls()

    def _build_chip_controls(self) -> None:
        self.chip_count_input = QLineEdit()
        self.chip_count_input.setPlaceholderText("Enter starting chips")
        self.chip_count_input.setValidator(QIntValidator(1, _MAX_CHIPS, self.chip_count_input))
        self.chip_count_input.setInputMethodHints(Qt.InputMethodHint.ImhDigitsOnly)
        self.chip_label = QLabel("Chip &count:")
        self.chip_label.setBuddy(self.chip_count_input)
        self.chip_count_input.hide()
        self.chip_label.hide()
        self._chip_delegate = _ChipCountDelegate(self.player_list)
        self.player_list.setItemDelegate(self._chip_delegate)

    def _build_layout(self) -> None:
        self._page_layout = QHBoxLayout(self)
        self._content = QWidget()
        self._content.setMaximumWidth(1280)
        self._page_layout.addStretch()
        self._page_layout.addWidget(self._content, 1)
        self._page_layout.addStretch()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        layout = self._content_layout
        self.title_label = QLabel("Tournament Setup")
        format_row = QHBoxLayout()
        format_row.addWidget(self.format_label)
        format_row.addStretch()
        format_row.addWidget(self.count_label)
        actions = QHBoxLayout()
        actions.addWidget(self.remove_button)
        actions.addWidget(self.back_button)
        layout.addWidget(self.title_label)
        layout.addLayout(format_row)
        layout.addLayout(self._table_row())
        self._build_player_inputs()
        layout.addWidget(self.player_list, 1)
        layout.addWidget(self.feedback_label)
        layout.addLayout(actions)
        layout.addWidget(self.start_button)

    def _build_player_inputs(self) -> None:
        layout = self._content_layout
        name_label = QLabel("Player &name:")
        name_label.setBuddy(self.name_input)
        layout.addWidget(name_label)
        self._name_layout = self._name_row()
        layout.addLayout(self._name_layout)
        layout.addWidget(self.chip_label)
        self._chip_row = QHBoxLayout()
        self._chip_row.addWidget(self.chip_count_input)
        layout.addLayout(self._chip_row)

    def _name_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(self.name_input)
        row.addWidget(self.add_button)
        return row

    def _apply_scale(self, scale: float) -> None:
        font = QFont(self.font())
        font.setPointSizeF(PAGE_TITLE_POINT_SIZE * scale)
        font.setBold(True)
        self.title_label.setFont(font)
        margin = round(PAGE_MARGIN * scale)
        self._page_layout.setContentsMargins(margin, margin, margin, margin)
        self._content_layout.setSpacing(round(LAYOUT_SPACING * scale))
        self._content.setMaximumWidth(round(1280 * scale))
        self.name_input.setMinimumHeight(round(INPUT_HEIGHT * scale))
        self.chip_count_input.setMinimumHeight(round(INPUT_HEIGHT * scale))
        self.table_count_input.setMinimumHeight(round(INPUT_HEIGHT * scale))
        self.table_count_input.setMinimumWidth(round(200 * scale))
        self.add_button.setMinimumWidth(round(144 * scale))
        self.feedback_label.setMinimumHeight(round(32 * scale))
        for button in [self.add_button, self.remove_button, self.back_button, self.start_button]:
            button.setMinimumHeight(round(BUTTON_HEIGHT * scale))
        self._row_height = round(PLAYER_ROW_HEIGHT * scale)
        self._size_player_rows()

    def _size_player_rows(self) -> None:
        for row in range(self.player_list.count()):
            item = self.player_list.item(row)
            assert item is not None
            item.setSizeHint(QSize(0, self._row_height))

    def _table_row(self) -> QHBoxLayout:
        label = QLabel("Number of &tables:")
        label.setBuddy(self.table_count_input)
        row = QHBoxLayout()
        row.addWidget(label)
        row.addWidget(self.table_count_input)
        row.addStretch()
        return row

    def _connect_controls(self) -> None:
        self.name_input.returnPressed.connect(self._name_entered)
        self.chip_count_input.returnPressed.connect(self._add_player)
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
        self.setTabOrder(self.name_input, self.chip_count_input)
        self.setTabOrder(self.chip_count_input, self.add_button)
        self.setTabOrder(self.add_button, self.player_list)
        self.setTabOrder(self.player_list, self.remove_button)
        self.setTabOrder(self.remove_button, self.back_button)
        self.setTabOrder(self.back_button, self.start_button)
        self.setTabOrder(self.start_button, self.table_count_input)
        self.setTabOrder(self.table_count_input, self.name_input)

    def set_format(self, tournament_format: str) -> None:
        """Display the chosen format while preserving the entered names."""
        self.format_label.setText(tournament_format)
        chip_mode = tournament_format == "Chip Tournament"
        self.chip_label.setVisible(chip_mode)
        self.chip_count_input.setVisible(chip_mode)
        self._chip_delegate.enabled = chip_mode
        self.player_list.viewport().update()
        source, destination = (
            (self._name_layout, self._chip_row)
            if chip_mode
            else (self._chip_row, self._name_layout)
        )
        source.removeWidget(self.add_button)
        destination.addWidget(self.add_button)
        self.add_button.setText("&Add Player" if chip_mode else "&Add")
        self._update_start_button()

    def restore_setup(self, tournament_format: str, names: Sequence[str], table_count: int) -> None:
        """Restore a validated setup without adding names through input controls."""
        players = list(names)
        if tournament_format not in {"Single Elimination", "Double Elimination"}:
            raise ValueError("Unknown tournament format.")
        if not _MIN_PLAYERS <= len(players) <= _MAX_PLAYERS or any(
            not isinstance(name, str) or not name.strip() or name != name.strip()
            for name in players
        ):
            raise ValueError("Setup must contain 2–32 nonblank player names.")
        if type(table_count) is not int or not 1 <= table_count <= self.table_count_input.maximum():
            raise ValueError("Invalid table count.")
        self.name_input.clear()
        self.chip_count_input.clear()
        self.player_list.clear()
        self.player_list.addItems(players)
        self.table_count_input.setValue(table_count)
        self.set_format(tournament_format)
        self.feedback_label.clear()
        self._update_controls()

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

    def player_chip_counts(self) -> list[int | None]:
        """Return counts in entry order; players entered in bracket modes have no count."""
        counts: list[int | None] = []
        for row in range(self.player_list.count()):
            item = self.player_list.item(row)
            assert item is not None
            value = item.data(Qt.ItemDataRole.UserRole)
            counts.append(value if type(value) is int else None)
        return counts

    def _entered_chips(self) -> int | None:
        text = self.chip_count_input.text().strip()
        if not text.isascii() or not text.isdecimal():
            return None
        value = int(text)
        return value if 1 <= value <= _MAX_CHIPS else None

    @Slot()
    def _name_entered(self) -> None:
        if self.format_label.text() == "Chip Tournament":
            self.chip_count_input.setFocus()
        else:
            self._add_player()

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
        if self.format_label.text() == "Chip Tournament":
            self.start_button.setEnabled(False)
            self.start_button.setToolTip("Chip tournament play is not available yet.")
            return
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
        chip_mode = self.format_label.text() == "Chip Tournament"
        chips = self._entered_chips() if chip_mode else None
        if chip_mode and chips is None:
            self.feedback_label.setText("Enter a positive whole number for the chip count.")
            self.chip_count_input.setFocus()
            return
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, chips)
        item.setToolTip(name if chips is None else f"{name} · {chips} chips")
        item.setData(Qt.ItemDataRole.AccessibleTextRole, item.toolTip())
        self.player_list.addItem(item)
        self.player_list.setCurrentRow(self.player_list.count() - 1)
        self.name_input.clear()
        self.chip_count_input.clear()
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
        self._size_player_rows()
        self.count_label.setText(f"Players: {count} / {_MAX_PLAYERS}")
        self.add_button.setEnabled(count < _MAX_PLAYERS)
        self.remove_button.setEnabled(bool(self.player_list.selectedItems()))
        self._update_start_button()
        if count == _MAX_PLAYERS:
            self.feedback_label.setText("32-player limit reached. Remove a player to add another.")
