"""Collect players and format-specific settings before a tournament starts."""

import csv
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Qt, Signal, Slot
from PySide6.QtGui import (
    QFont,
    QIntValidator,
    QKeySequence,
    QPainter,
    QPalette,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpacerItem,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from chip_tournament import MAX_CHIPS as _MAX_CHIPS
from ui_metrics import (
    BUTTON_HEIGHT,
    INPUT_HEIGHT,
    LAYOUT_SPACING,
    OPERATOR_DIALOG_SCALE,
    PAGE_MARGIN,
    PAGE_TITLE_POINT_SIZE,
    PLAYER_ROW_HEIGHT,
)

_MAX_PLAYERS = 32
_MIN_PLAYERS = 2
_DEFAULT_IMPORT_CHIPS = 4


def _parse_import_row(row: list[str]) -> tuple[str, int]:
    if len(row) not in {1, 2}:
        raise ValueError("Use name or name,chips, with no extra columns.")
    name = row[0].strip()
    if not name:
        raise ValueError("Player names cannot be blank.")
    text = row[1].strip() if len(row) > 1 else ""
    if not text:
        return name, _DEFAULT_IMPORT_CHIPS
    digits = text.lstrip("0") or "0"
    if not text.isascii() or not text.isdecimal() or len(digits) > len(str(_MAX_CHIPS)):
        raise ValueError(f"Chips must be a whole number between 1 and {_MAX_CHIPS}.")
    chips = int(digits)
    if not 1 <= chips <= _MAX_CHIPS:
        raise ValueError(f"Chips must be a whole number between 1 and {_MAX_CHIPS}.")
    return name, chips


@dataclass
class _PlayerImport:
    """Accumulate usable players and a reason for every skipped record."""

    players: list[tuple[str, int]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    _names: set[str] = field(default_factory=set)

    def _add_row(self, row: list[str], line_number: int) -> None:
        try:
            name, chips = _parse_import_row(row)
            if name in self._names:
                raise ValueError(f"Duplicate player name: {name}.")
            self._names.add(name)
            if len(self.players) >= _MAX_PLAYERS:
                raise ValueError(f"32-player limit reached; skipped {name}.")
            self.players.append((name, chips))
        except ValueError as error:
            self.issues.append(f"Line {line_number}: {error}")


def _read_import_players(path: str) -> _PlayerImport:
    source = Path(path)
    if source.suffix.lower() not in {".txt", ".csv"}:
        raise ValueError("Choose a .txt or .csv file.")
    result = _PlayerImport()
    first_row = True
    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True, skipinitialspace=True)
        try:
            for row in reader:
                if not row or (len(row) == 1 and not row[0].strip()):
                    continue
                header = [value.strip().lower() for value in row]
                if first_row and header in (["name"], ["name", "chips"]):
                    first_row = False
                    continue
                first_row = False
                result._add_row(row, reader.line_num)
        except csv.Error as error:
            raise ValueError(f"Line {reader.line_num}: {error}") from error
        except UnicodeDecodeError as error:
            raise ValueError(
                "Use a UTF-8 TXT or CSV file; the file's encoding is unsupported."
            ) from error
    return result


class _ImportResultsDialog(QMessageBox):
    """Keep the import report 50% wider than Qt's natural message-box width."""

    _widened = False

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._widened:
            return
        self._widened = True
        width = round(self.width() * 1.5)
        layout = self.layout()
        assert isinstance(layout, QGridLayout)
        margins = layout.contentsMargins()
        spacer = QSpacerItem(max(0, width - margins.left() - margins.right()), 0)
        layout.addItem(spacer, layout.rowCount(), 0, 1, layout.columnCount())
        layout.activate()
        self.setMinimumWidth(width)


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
        self._editing_item: QListWidgetItem | None = None
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
        self.import_button = QPushButton("&Import Players…")
        self.import_button.setToolTip(
            "Replace the roster from a TXT or CSV file: name or name,chips. "
            "Missing chips default to 4."
        )
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
        self.chip_count_input.setPlaceholderText(f"Enter starting chips (1–{_MAX_CHIPS})")
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
        for button in [
            self.add_button,
            self.import_button,
            self.remove_button,
            self.back_button,
            self.start_button,
        ]:
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
        row.addWidget(self.import_button)
        return row

    def _connect_controls(self) -> None:
        self.name_input.returnPressed.connect(self._name_entered)
        self.chip_count_input.returnPressed.connect(self._add_player)
        self.add_button.clicked.connect(self._add_player)
        self.import_button.clicked.connect(self._import_players)
        self.remove_button.clicked.connect(self._remove_player)
        self.back_button.clicked.connect(self.back_requested.emit)
        self.start_button.clicked.connect(self._request_start)
        self.name_input.textChanged.connect(self._update_start_button)
        self.chip_count_input.textChanged.connect(self._update_start_button)
        self.table_count_input.valueChanged.connect(self._update_start_button)
        self.player_list.itemSelectionChanged.connect(self._update_controls)
        self.player_list.itemClicked.connect(self._edit_chip_player)
        self.player_list.itemActivated.connect(self._edit_chip_player)
        delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.player_list)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self._remove_player)
        for button in [
            self.add_button,
            self.import_button,
            self.remove_button,
            self.back_button,
            self.start_button,
        ]:
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
        self.setTabOrder(self.table_count_input, self.import_button)
        self.setTabOrder(self.import_button, self.name_input)

    @Slot()
    def _import_players(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Players", "", "Player files (*.txt *.csv)"
        )
        if not path:
            return
        try:
            result = _read_import_players(path)
        except (OSError, ValueError) as error:
            self.feedback_label.setText(f"Could not import players: {error}")
            return
        summary = "Could not import players: The file must contain at least one usable player."
        if result.players:
            self._replace_import_players(result.players)
            count = len(result.players)
            summary = f"Imported {count} player" + ("s." if count != 1 else ".")
        if result.issues:
            count = len(result.issues)
            summary += f" Skipped {count} line" + ("s." if count != 1 else ".")
        self.feedback_label.setText(summary)
        if result.issues:
            self._show_import_report(summary, result.issues)

    def _replace_import_players(self, players: Sequence[tuple[str, int]]) -> None:
        self._editing_item = None
        self.player_list.clear()
        for name, chips in players:
            self._store_player(name, chips)
        self.name_input.clear()
        self.chip_count_input.clear()
        self.set_format(self.format_label.text())
        self._update_controls()
        self.name_input.setFocus()

    def _show_import_report(self, summary: str, issues: Sequence[str]) -> None:
        dialog = _ImportResultsDialog(
            QMessageBox.Icon.Information,
            "Import Results",
            summary,
            QMessageBox.StandardButton.Ok,
            self,
        )
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setInformativeText("Open Show Details to see each skipped row and its reason.")
        dialog.setDetailedText("\n".join(issues))
        font = QFont(self.font())
        font.setPointSizeF(font.pointSizeF() * OPERATOR_DIALOG_SCALE * 0.50)
        dialog.setFont(font)
        dialog.exec()
        dialog.deleteLater()

    def set_format(self, tournament_format: str) -> None:
        """Display the chosen format while preserving the entered names."""
        self.format_label.setText(tournament_format)
        self._editing_item = None
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
        self._editing_item = None
        self.player_list.clear()
        self.player_list.addItems(players)
        self.table_count_input.setValue(table_count)
        self.set_format(tournament_format)
        self.feedback_label.clear()
        self._update_controls()

    def restore_chip_setup(
        self, names: Sequence[str], chip_counts: Sequence[int], table_count: int
    ) -> None:
        """Restore initial chip allowances while preserving the original entry order."""
        if len(names) != len(chip_counts) or any(
            type(count) is not int or not 1 <= count <= _MAX_CHIPS for count in chip_counts
        ):
            raise ValueError(
                f"Every player needs a whole-number chip count from 1 to {_MAX_CHIPS}."
            )
        self.restore_setup("Single Elimination", names, table_count)
        for row, chips in enumerate(chip_counts):
            item = self.player_list.item(row)
            assert item is not None
            item.setData(Qt.ItemDataRole.UserRole, chips)
        self.set_format("Chip Tournament")
        self._update_controls()

    @Slot(QListWidgetItem)
    def _edit_chip_player(self, item: QListWidgetItem) -> None:
        if self.format_label.text() != "Chip Tournament":
            return
        self._editing_item = item
        self.name_input.setText(item.text())
        chips = item.data(Qt.ItemDataRole.UserRole)
        self.chip_count_input.setText("" if chips is None else str(chips))
        self.add_button.setText("&Update Player")
        self.add_button.setEnabled(True)
        self.chip_count_input.setFocus()

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
        """Return counts in entry order; manually added bracket players have no count."""
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
        chip_mode = self.format_label.text() == "Chip Tournament"
        chips_ready = not chip_mode or all(count is not None for count in self.player_chip_counts())
        count = self.player_list.count()
        pending_name = bool(self.name_input.text().strip()) or (
            chip_mode and bool(self.chip_count_input.text().strip())
        )
        self.start_button.setEnabled(
            _MIN_PLAYERS <= count <= _MAX_PLAYERS
            and not pending_name
            and bool(self.format_label.text())
            and chips_ready
        )
        if count < _MIN_PLAYERS:
            self.start_button.setToolTip("Add at least two players to start.")
        elif pending_name:
            self.start_button.setToolTip("Add the entered name before starting.")
        elif not chips_ready:
            self.start_button.setToolTip(
                "Select each player without chips and enter their chip count."
            )
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
        if self.player_list.count() >= _MAX_PLAYERS and self._editing_item is None:
            self._update_controls()
            return
        for row in range(self.player_list.count()):
            existing = self.player_list.item(row)
            assert existing is not None
            if existing is not self._editing_item and existing.text() == name:
                self.feedback_label.setText("A player with this name already exists.")
                self.name_input.setFocus()
                return
        chip_mode = self.format_label.text() == "Chip Tournament"
        chips = self._entered_chips() if chip_mode else None
        if chip_mode and chips is None:
            self.feedback_label.setText(
                f"Enter a positive whole number from 1 to {_MAX_CHIPS} for the chip count."
            )
            self.chip_count_input.setFocus()
            return
        item = self._store_player(name, chips)
        self.player_list.setCurrentRow(self.player_list.row(item))
        self.name_input.clear()
        self.chip_count_input.clear()
        self._editing_item = None
        self.add_button.setText("&Add Player" if chip_mode else "&Add")
        self.feedback_label.clear()
        self._update_controls()
        self.name_input.setFocus()

    def _store_player(self, name: str, chips: int | None) -> QListWidgetItem:
        item = self._editing_item
        if item is None:
            item = QListWidgetItem(name)
            self.player_list.addItem(item)
        item.setText(name)
        item.setData(Qt.ItemDataRole.UserRole, chips)
        item.setToolTip(name if chips is None else f"{name} · {chips} chips")
        item.setData(Qt.ItemDataRole.AccessibleTextRole, item.toolTip())
        return item

    @Slot()
    def _remove_player(self) -> None:
        if self._editing_item in self.player_list.selectedItems():
            self._editing_item = None
            self.name_input.clear()
            self.chip_count_input.clear()
            self.add_button.setText("&Add Player")
        for item in self.player_list.selectedItems():
            self.player_list.takeItem(self.player_list.row(item))
        self.feedback_label.clear()
        self._update_controls()

    @Slot()
    def _update_controls(self) -> None:
        count = self.player_list.count()
        self._size_player_rows()
        self.count_label.setText(f"Players: {count} / {_MAX_PLAYERS}")
        self.add_button.setEnabled(count < _MAX_PLAYERS or self._editing_item is not None)
        self.remove_button.setEnabled(bool(self.player_list.selectedItems()))
        self._update_start_button()
        if count == _MAX_PLAYERS:
            self.feedback_label.setText("32-player limit reached. Remove a player to add another.")
