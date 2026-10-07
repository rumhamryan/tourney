"""A live chip leaderboard beside a responsive grid of round matchups."""

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chip_tournament import ChipMatch, ChipTournament, champion_index, validate_tournament
from ui_metrics import (
    BODY_POINT_SIZE,
    BUTTON_HEIGHT,
    LAYOUT_SPACING,
    OPERATOR_DIALOG_SCALE,
    PAGE_MARGIN,
    PAGE_TITLE_POINT_SIZE,
)

_CARD_WIDTH = 384
_CARD_HEIGHT = 164
_LIGHT_BACKGROUND_THRESHOLD = 128


def _label(text: str, *, bold: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    font = QFont()
    font.setBold(bold)
    label.setFont(font)
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return label


def _keyboard_button(button: QPushButton) -> None:
    button.setAutoDefault(False)
    for key in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
        shortcut = QShortcut(QKeySequence(key), button)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut.activated.connect(button.click)


class _ResultDialog(QDialog):
    def __init__(self, state: ChipTournament, match: ChipMatch, parent: QWidget) -> None:
        super().__init__(parent)
        self.winner_index: int | None = None
        self.setWindowTitle(f"Record Result · {match.identifier} · Table {match.table_number}")
        self.setMinimumWidth(480)
        self.winner_buttons: list[QPushButton] = []
        layout = QVBoxLayout(self)
        layout.addWidget(_label("Select the winner."))
        names = [state.players[index].name for index in match.players]
        for index, name, position in zip(
            match.players, names, ["Top player", "Bottom player"], strict=True
        ):
            label = f"{position}: {name}" if names[0] == names[1] else name
            button = self._winner_button(label, index)
            layout.addWidget(button)
            self.winner_buttons.append(button)
        self.setTabOrder(self.winner_buttons[0], self.winner_buttons[1])
        self._enlarge()

    def _enlarge(self) -> None:
        layout = self.layout()
        assert layout is not None
        original = self.sizeHint().expandedTo(self.minimumSize())
        self.setMinimumSize(
            round(original.width() * OPERATOR_DIALOG_SCALE),
            round(original.height() * OPERATOR_DIALOG_SCALE),
        )
        font = QFont(self.font())
        font.setPointSizeF(font.pointSizeF() * OPERATOR_DIALOG_SCALE)
        self.setFont(font)
        margins = layout.contentsMargins()
        layout.setContentsMargins(
            round(margins.left() * OPERATOR_DIALOG_SCALE),
            round(margins.top() * OPERATOR_DIALOG_SCALE),
            round(margins.right() * OPERATOR_DIALOG_SCALE),
            round(margins.bottom() * OPERATOR_DIALOG_SCALE),
        )
        layout.setSpacing(round(layout.spacing() * OPERATOR_DIALOG_SCALE))
        for button in self.winner_buttons:
            button.setMinimumHeight(round(button.minimumHeight() * OPERATOR_DIALOG_SCALE))
            text = QFontMetrics(button.font()).elidedText(
                button.toolTip(),
                Qt.TextElideMode.ElideRight,
                round(520 * OPERATOR_DIALOG_SCALE),
            )
            button.setText(text.replace("&", "&&"))

    def _winner_button(self, label: str, index: int) -> QPushButton:
        button = QPushButton()
        text = QFontMetrics(button.font()).elidedText(label, Qt.TextElideMode.ElideRight, 520)
        button.setText(text.replace("&", "&&"))
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.setMinimumHeight(48)
        _keyboard_button(button)
        button.clicked.connect(lambda: self._choose(index))
        return button

    def _choose(self, index: int) -> None:
        self.winner_index = index
        self.accept()


class _MatchCard(QPushButton):
    def __init__(self, state: ChipTournament, match: ChipMatch, parent: QWidget) -> None:
        super().__init__(parent)
        _keyboard_button(self)
        self.setStyleSheet(
            "QPushButton { background: palette(base); border: 2px solid white; padding: 12px; }"
            "QPushButton:focus { border: 2px solid palette(highlight); }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        header = QHBoxLayout()
        header.addWidget(_label(match.identifier, bold=True))
        header.addStretch()
        badge = _label(
            f"Table {match.table_number}" if match.table_number else "Waiting", bold=True
        )
        if match.table_number is not None:
            color = (
                "#15803d"
                if self.palette().base().color().lightness() >= _LIGHT_BACKGROUND_THRESHOLD
                else "#4ade80"
            )
            badge.setStyleSheet(f"color: {color};")
        header.addWidget(badge)
        layout.addLayout(header)
        self.player_labels = [_label(state.players[index].name) for index in match.players]
        for label in self.player_labels:
            label.setToolTip(label.text())
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            layout.addWidget(label)
        layout.addWidget(_label("In progress" if match.table_number else "Waiting for a table"))
        self.setEnabled(match.table_number is not None)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if self.isEnabled() else Qt.CursorShape.ArrowCursor
        )
        self.setAccessibleName(
            f"{match.identifier}, {badge.text()}, "
            + " versus ".join(label.text() for label in self.player_labels)
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        for label in self.player_labels:
            label.setText(
                QFontMetrics(label.font()).elidedText(
                    label.toolTip(), Qt.TextElideMode.ElideRight, max(0, self.width() - 32)
                )
            )


class ChipView(QWidget):
    back_requested = Signal()
    save_requested = Signal()
    result_requested = Signal(str, int)
    undo_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.tournament: ChipTournament | None = None
        self.read_only = False
        self.busy = False
        self.match_cards: dict[str, _MatchCard] = {}
        self._scale = 1.0
        self._columns = 1
        self.title_label = _label("Chip Tournament", bold=True)
        self.summary_label = _label("")
        self.status_label = _label("")
        self.file_label = _label("")
        self.file_label.setWordWrap(True)
        self.status_label.setWordWrap(True)
        self.back_button = QPushButton("&Back to Menu")
        self.save_button = QPushButton("&Save As…")
        self.undo_button = QPushButton("&Undo Last Result")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo_requested.emit)
        self.back_button.clicked.connect(self.back_requested.emit)
        self.save_button.clicked.connect(self.save_requested.emit)
        self._build_layout()
        self._connect_keyboard()

    def _build_layout(self) -> None:
        self._layout = QVBoxLayout(self)
        self._layout.addWidget(self.title_label)
        self._layout.addWidget(self.summary_label)
        self._layout.addWidget(_label("Click an active matchup to select its winner."))
        self._layout.addWidget(self.status_label)
        self._layout.addWidget(self.file_label)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self._build_leaderboard()
        self._build_matches()
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([350, 1050])
        self._layout.addWidget(self.splitter, 1)
        footer = QHBoxLayout()
        footer.addWidget(self.save_button)
        footer.addWidget(self.undo_button)
        footer.addWidget(self.back_button)
        self._layout.addLayout(footer)

    def _build_leaderboard(self) -> None:
        self.leaderboard_pane = QWidget()
        layout = QVBoxLayout(self.leaderboard_pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_label("Leaderboard", bold=True))
        self.leaderboard = QTreeWidget()
        self.leaderboard.setAccessibleName("Current chip leaderboard")
        self.leaderboard.setColumnCount(2)
        self.leaderboard.setHeaderLabels(["Player", "Chips"])
        self.leaderboard.setRootIsDecorated(False)
        self.leaderboard.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.leaderboard.header().setStretchLastSection(False)
        self.leaderboard.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.leaderboard.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.leaderboard, 1)
        self.bye_label = _label("")
        self.bye_label.setWordWrap(True)
        layout.addWidget(self.bye_label)
        self.splitter.addWidget(self.leaderboard_pane)

    def _build_matches(self) -> None:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_label("Matchups", bold=True))
        self.match_scroll = QScrollArea()
        self.match_scroll.setWidgetResizable(True)
        self.match_scroll.setAccessibleName("Current round matchups")
        self._match_content = QWidget()
        self._grid = QGridLayout(self._match_content)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.match_scroll.setWidget(self._match_content)
        self.match_scroll.viewport().installEventFilter(self)
        layout.addWidget(self.match_scroll, 1)
        self.splitter.addWidget(pane)

    def _connect_keyboard(self) -> None:
        for button in [self.save_button, self.undo_button, self.back_button]:
            _keyboard_button(button)
        shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.SaveAs), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.save_button.click)
        undo = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self)
        undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo.activated.connect(self.undo_button.click)

    def _apply_scale(self, scale: float) -> None:
        self._scale = scale
        font = QFont(self.font())
        font.setPointSizeF(BODY_POINT_SIZE * scale)
        self.setFont(font)
        font.setPointSizeF(PAGE_TITLE_POINT_SIZE * scale)
        font.setBold(True)
        self.title_label.setFont(font)
        margin = round(PAGE_MARGIN * scale)
        self._layout.setContentsMargins(margin, margin, margin, margin)
        self._layout.setSpacing(round(LAYOUT_SPACING * scale))
        self.leaderboard_pane.setMinimumWidth(round(240 * scale))
        self.match_scroll.setMinimumWidth(round(400 * scale))
        for button in [self.save_button, self.undo_button, self.back_button]:
            button.setMinimumHeight(round(BUTTON_HEIGHT * scale))
        for card in self.match_cards.values():
            card.setMinimumWidth(round(_CARD_WIDTH * scale))
            card.setFixedHeight(round(_CARD_HEIGHT * scale))
            for label in card.findChildren(QLabel):
                label_font = QFont(label.font())
                label_font.setPointSizeF(BODY_POINT_SIZE * scale)
                label.setFont(label_font)
        self._reflow()

    def show_tournament(self, state: ChipTournament) -> None:
        """Update chip standings and remove completed matchups from the visible grid."""
        validate_tournament(state)
        self.tournament = state
        round_ = state.rounds[-1]
        table_word = "table" if state.table_count == 1 else "tables"
        self.summary_label.setText(
            f"Round {round_.number} · {len(state.players)} players · "
            f"{state.table_count} {table_word}"
        )
        champion = champion_index(state)
        self.status_label.setText(
            f"Champion: {state.players[champion].name}"
            if champion is not None
            else f"{sum(player.chips > 0 for player in state.players)} players remaining"
        )
        self._show_leaderboard(state)
        self._show_matches(state)
        self._apply_scale(self._scale)

    def _show_leaderboard(self, state: ChipTournament) -> None:
        self.leaderboard.clear()
        ordered = sorted(range(len(state.players)), key=lambda index: -state.players[index].chips)
        for index in ordered:
            player = state.players[index]
            name = f"{player.name} · Eliminated" if player.chips == 0 else player.name
            item = QTreeWidgetItem([name, str(player.chips)])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            status = "Eliminated" if player.chips == 0 else f"{player.chips} chips remaining"
            item.setToolTip(0, f"{player.name} · {status}")
            if player.chips == 0:
                brush = self.palette().placeholderText()
                item.setForeground(0, brush)
                item.setForeground(1, brush)
            self.leaderboard.addTopLevelItem(item)
        bye = state.rounds[-1].bye_index
        self.bye_label.setText(
            f"Bye this round: {state.players[bye].name}" if bye is not None else ""
        )

    def _show_matches(self, state: ChipTournament) -> None:
        position = self.match_scroll.verticalScrollBar().value()
        for card in self.match_cards.values():
            self._grid.removeWidget(card)
            card.hide()
            card.deleteLater()
        self.match_cards.clear()
        for match in state.rounds[-1].matches:
            if match.winner_index is not None:
                continue
            card = _MatchCard(state, match, self._match_content)
            card.clicked.connect(
                lambda checked=False, identifier=match.identifier: self._open_result(identifier)
            )
            self.match_cards[match.identifier] = card
        self._reflow()
        self.match_scroll.verticalScrollBar().setValue(position)

    def _reflow(self) -> None:
        if not hasattr(self, "match_scroll"):
            return
        spacing = round(LAYOUT_SPACING * self._scale)
        columns = max(
            1, self.match_scroll.viewport().width() // (round(_CARD_WIDTH * self._scale) + spacing)
        )
        for column in range(max(columns, self._columns)):
            self._grid.setColumnStretch(column, int(column < columns))
        self._columns = columns
        self._grid.setSpacing(spacing)
        for index, card in enumerate(self.match_cards.values()):
            self._grid.addWidget(card, index // columns, index % columns)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.match_scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._reflow()
        return super().eventFilter(watched, event)

    def _open_result(self, identifier: str) -> None:
        if self.tournament is None or self.read_only or self.busy:
            return
        match = next(
            (
                match
                for match in self.tournament.rounds[-1].matches
                if match.identifier == identifier
            ),
            None,
        )
        if match is None or match.table_number is None or match.winner_index is not None:
            return
        dialog = _ResultDialog(self.tournament, match, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            assert dialog.winner_index is not None
            self.result_requested.emit(match.identifier, dialog.winner_index)
        dialog.deleteLater()
