"""Display tournament progress and collect results for active matches."""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QResizeEvent,
    QShortcut,
    QTransform,
)
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from bracket_preview import Draw, PreviewMatch, Source
from tournament_state import (
    Outcome,
    TournamentState,
    champion_index,
    match_players,
    resolved_outcomes,
    validate_tournament,
)
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
_COLUMN_STEP = 460
_ROW_STEP = 204
_LINE_WIDTH = 2.0
_LIGHT_BACKGROUND_THRESHOLD = 128
_MIN_ZOOM = 25
_MAX_ZOOM = 200
_DEFAULT_ZOOM = 100
_ZOOM_STEP = 5


def _display_match_id(identifier: str) -> str:
    return "F1" if identifier == "GF" else identifier


class _BracketHeading(QWidget):
    """Readable headings outside the scrolling, zoomable match viewport."""

    def __init__(self, parent: QGraphicsView) -> None:
        super().__init__(parent)
        self.setAccessibleName("Bracket headings")
        self.round_labels: list[QLabel] = []
        self._columns: tuple[tuple[str, QRectF], ...] = ()
        self.round_rows = 1

    def show_columns(
        self, columns: tuple[tuple[str, QRectF], ...], graphics: QGraphicsView
    ) -> None:
        if columns != self._columns:
            for label in self.round_labels:
                label.hide()
                label.deleteLater()
            self.round_labels.clear()
            self._columns = columns
            for text, _ in columns:
                label = QLabel(text, self)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setToolTip(text)
                label.setAccessibleName(text)
                self.round_labels.append(label)
        for index, (label, (text, column)) in enumerate(
            zip(self.round_labels, columns, strict=True)
        ):
            self._align_heading(
                label,
                (text, column),
                graphics,
                row=index % self.round_rows,
                span=self.round_rows,
            )

    def _align_heading(
        self,
        label: QLabel,
        heading: tuple[str, QRectF],
        graphics: QGraphicsView,
        *,
        row: int,
        span: int = 1,
    ) -> None:
        text, column = heading
        center = column.center()
        half_width = QPointF(column.width() * span / 2, 0)
        left = max(0, graphics.mapFromScene(center - half_width).x())
        right = min(self.width(), graphics.mapFromScene(center + half_width).x())
        width = max(0, min(right - left - 8, label.fontMetrics().horizontalAdvance(text) + 8))
        label.setVisible(
            width > 0
            and graphics.mapFromScene(column.topRight()).x() > 0
            and graphics.mapFromScene(column.topLeft()).x() < self.width()
        )
        label.setGeometry(
            max(left + 4, min(graphics.mapFromScene(center).x() - width // 2, right - width - 4)),
            self.height() // self.round_rows * row,
            width,
            self.height() // self.round_rows,
        )
        label.setText(label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width))


class _BracketGraphics(QGraphicsView):
    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self.columns: tuple[tuple[str, QRectF], ...] = ()
        self.heading = _BracketHeading(self)
        self.horizontalScrollBar().valueChanged.connect(self._refresh_headings)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "heading"):
            self._refresh_headings()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if hasattr(self, "heading") and event.type() == QEvent.Type.FontChange:
            self._refresh_headings()

    def _refresh_headings(self) -> None:
        self.heading.round_rows = self._round_rows()
        height = (
            self.heading.round_rows * (self.fontMetrics().lineSpacing() + 6) if self.columns else 0
        )
        if self.viewportMargins().top() != height:
            self.setViewportMargins(0, height, 0, 0)
        viewport = self.viewport().geometry()
        self.heading.setGeometry(viewport.left(), self.frameWidth(), viewport.width(), height)
        self.heading.setVisible(bool(self.columns))
        self.heading.show_columns(self.columns, self)

    def _round_rows(self) -> int:
        metrics = self.fontMetrics()
        for text, column in self.columns:
            width = column.width() * self.transform().m11()
            if metrics.horizontalAdvance(text) + 8 > width:
                return 2
        return 1


class _MatchCard(QGraphicsRectItem):
    def __init__(self, rectangle: QRectF, identifier: str, callback: Callable[[str], None]) -> None:
        super().__init__(rectangle)
        self._identifier = identifier
        self._callback = callback
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self._callback(self._identifier)
        else:
            super().mousePressEvent(event)


class _ResultDialog(QDialog):
    def __init__(self, state: TournamentState, parent: QWidget, match_id: str = "") -> None:
        super().__init__(parent)
        active = [item for item in state.progress if item.status == "in_progress"]
        match = next((item for item in active if item.match_id == match_id), None)
        if not match_id and active:
            match = active[0]
        if match is None:
            raise ValueError("Choose a match in progress.")
        self._match_id = match.match_id
        self._winner: int | None = None
        self.setWindowTitle(
            f"Record Result · {_display_match_id(match.match_id)} · Table {match.table_number}"
        )
        self.setMinimumWidth(480)
        self.winner_buttons: list[QPushButton] = []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select the winner."))
        players = match_players(state, self._match_id)
        assert players[0] is not None and players[1] is not None
        duplicate = state.draw.names[players[0]] == state.draw.names[players[1]]
        for player, position in zip(players, ["Top player", "Bottom player"], strict=True):
            assert player is not None
            label = state.draw.names[player]
            if duplicate:
                label = f"{position}: {label}"
            button = self._player_button(label, player)
            self.winner_buttons.append(button)
            layout.addWidget(button)
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

    def _player_button(self, label: str, player: int) -> QPushButton:
        button = QPushButton()
        button.setText(
            QFontMetrics(button.font())
            .elidedText(label, Qt.TextElideMode.ElideRight, 520)
            .replace("&", "&&")
        )
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.setMinimumHeight(48)
        button.setAutoDefault(False)
        button.clicked.connect(lambda: self._choose_winner(player))
        for key in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
            shortcut = QShortcut(QKeySequence(key), button)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(button.click)
        return button

    def _choose_winner(self, player: int) -> None:
        self._winner = player
        self.accept()

    def selection(self) -> tuple[str, int]:
        if self._winner is None:
            raise ValueError("Choose a winner before recording a result.")
        return self._match_id, self._winner


class BracketView(QWidget):
    """Show match sources, automatic byes, and the conditional grand final."""

    back_requested = Signal()
    save_requested = Signal()
    result_requested = Signal(str, int)
    undo_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.draw: Draw | None = None
        self.tournament: TournamentState | None = None
        self.outcomes: dict[str, Outcome] = {}
        self.table_count = 1
        self.scheduling = False
        self.read_only = False
        self.match_rects: dict[str, QRectF] = {}
        self._card_width = float(_CARD_WIDTH)
        self._card_height = float(_CARD_HEIGHT)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.status_label = QLabel()
        self.file_label = QLabel()
        self.file_label.setWordWrap(True)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(32)
        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(self.palette().brush(QPalette.ColorRole.Window))
        self.graphics = _BracketGraphics(self.scene)
        self.graphics.setAccessibleName("Tournament bracket")
        self.graphics.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.graphics.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.graphics.setMinimumSize(260, 200)
        self._build_actions()
        self._build_zoom_controls()
        self._build_layout()

    def _build_zoom_controls(self) -> None:
        self._window_scale = 1.0
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(_MIN_ZOOM, _MAX_ZOOM)
        self.zoom_slider.setSingleStep(_ZOOM_STEP)
        self.zoom_slider.setPageStep(25)
        self.zoom_slider.setValue(_DEFAULT_ZOOM)
        self.zoom_slider.setAccessibleName("Bracket zoom")
        self.zoom_label = QLabel("&Zoom:")
        self.zoom_label.setBuddy(self.zoom_slider)
        self.zoom_percentage = QLabel("100%")
        self.zoom_percentage.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.zoom_slider.valueChanged.connect(self._update_zoom)

    def _title_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(self.title_label, 1)
        row.addWidget(self.zoom_label)
        row.addWidget(self.zoom_slider, 1)
        row.addWidget(self.zoom_percentage)
        return row

    def _build_actions(self) -> None:
        self.back_button = QPushButton("&Back to Setup")
        self.back_button.setMinimumHeight(40)
        self.back_button.setAutoDefault(False)
        self.back_button.clicked.connect(self.back_requested.emit)
        self.save_action = QAction("Save As…", self)
        self.save_action.setShortcut(QKeySequence(QKeySequence.StandardKey.SaveAs))
        self.save_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.save_action.triggered.connect(self.save_requested.emit)
        self.addAction(self.save_action)
        self.undo_button = QPushButton("&Undo Last Result")
        self.undo_button.setAutoDefault(False)
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo_requested.emit)

    def _build_layout(self) -> None:
        self._page_layout = QVBoxLayout(self)
        layout = self._page_layout
        self.title_label = QLabel("Bracket Preview")
        self.title_label.setWordWrap(True)
        self.hint_label = QLabel("Scroll to see all rounds. Return to setup to edit the draw.")
        self.hint_label.setWordWrap(True)
        layout.addLayout(self._title_row())
        layout.addWidget(self.summary_label)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.file_label)
        layout.addWidget(self.graphics, 1)
        actions = QHBoxLayout()
        actions.addWidget(self.undo_button)
        actions.addWidget(self.back_button)
        layout.addLayout(actions)
        self._connect_keyboard()

    def _apply_scale(self, scale: float) -> None:
        font = QFont(self.font())
        font.setPointSizeF(PAGE_TITLE_POINT_SIZE * scale)
        font.setBold(True)
        self.title_label.setFont(font)
        margin = round(PAGE_MARGIN * scale)
        self._page_layout.setContentsMargins(margin, margin, margin, margin)
        self._page_layout.setSpacing(round(LAYOUT_SPACING * scale))
        self.status_label.setMinimumHeight(round(32 * scale))
        for button in [self.undo_button, self.back_button]:
            button.setMinimumHeight(round(BUTTON_HEIGHT * scale))
        self.zoom_slider.setMinimumWidth(round(120 * scale))
        self.zoom_slider.setMaximumWidth(round(240 * scale))
        self.zoom_percentage.setMinimumWidth(QFontMetrics(self.font()).horizontalAdvance("200%"))
        self._window_scale = scale
        self._update_zoom(self.zoom_slider.value())

    def _update_zoom(self, value: int) -> None:
        percentage = round(value / _ZOOM_STEP) * _ZOOM_STEP
        if percentage != value:
            self.zoom_slider.setValue(percentage)
            return
        center = self.graphics.mapToScene(self.graphics.viewport().rect().center())
        scale = self._window_scale * percentage / _DEFAULT_ZOOM
        self.graphics.setTransform(QTransform.fromScale(scale, scale))
        self.graphics.centerOn(center)
        self.graphics._refresh_headings()
        self.zoom_percentage.setText(f"{percentage}%")

    def reset_zoom(self) -> None:
        """Restore the default bracket zoom without changing the tournament."""
        self.zoom_slider.setValue(_DEFAULT_ZOOM)

    def _connect_keyboard(self) -> None:
        for button in [self.undo_button, self.back_button]:
            self._button_shortcuts(button)
        undo = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self)
        undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo.activated.connect(self.undo_button.click)
        self.setTabOrder(self.zoom_slider, self.graphics)
        self.setTabOrder(self.graphics, self.undo_button)
        self.setTabOrder(self.undo_button, self.back_button)
        self.setTabOrder(self.back_button, self.zoom_slider)

    def _button_shortcuts(self, button: QPushButton) -> None:
        for key in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
            shortcut = QShortcut(QKeySequence(key), button)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(button.click)

    def show_draw(self, draw: Draw, table_count: int) -> None:
        """Replace the preview while preserving its immutable setup snapshot."""
        if table_count < 1:
            raise ValueError("At least one table is required.")
        self.reset_zoom()
        self.tournament = None
        self.outcomes = {}
        self._display_draw(draw, table_count)

    def show_tournament(self, state: TournamentState) -> None:
        """Restore the saved graph and show its results and occupied tables."""
        validate_tournament(state)
        self.tournament = state
        self.outcomes = resolved_outcomes(state)
        self._display_draw(state.draw, state.table_count)

    def _display_draw(self, draw: Draw, table_count: int) -> None:
        self.draw = draw
        self.table_count = table_count
        self.status_label.clear()
        locked = self.tournament is not None and self.tournament.draw_locked
        self.back_button.setText("&Back to Menu" if locked else "&Back to Setup")
        self.title_label.setText("Tournament Bracket" if locked else "Bracket Preview")
        self.hint_label.setText(
            "Tables are assigned automatically. Click an active match to report its winner."
            if locked
            else "Scroll to see all rounds. Return to setup to edit the draw."
        )
        table_word = "table" if table_count == 1 else "tables"
        self.summary_label.setText(
            f"{draw.tournament_format} · {len(draw.names)} players · {table_count} {table_word}"
        )
        self._measure_cards()
        self.scene.clear()
        self.scene.setBackgroundBrush(self.palette().brush(QPalette.ColorRole.Window))
        self.match_rects.clear()
        winners = [match for match in draw.matches if match.section == "Winners"]
        bottom = self._place_section(winners, 20)
        if draw.tournament_format == "Double Elimination":
            losers = [match for match in draw.matches if match.section == "Losers"]
            self._place_section(losers, bottom + 40)
            self._place_finals(draw)
        self._draw_connectors(draw)
        self._set_column_headings(draw)
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20))
        self.graphics.horizontalScrollBar().setValue(0)
        self.graphics.verticalScrollBar().setValue(0)
        self.graphics._refresh_headings()
        self.set_scheduling(self.scheduling)
        if self.tournament is not None:
            champion = champion_index(self.tournament)
            if champion is not None:
                self.status_label.setText(f"Champion: {self.tournament.draw.names[champion]}")

    def set_scheduling(self, busy: bool) -> None:
        """Disable result entry while a scheduling snapshot is being computed."""
        self.scheduling = busy
        if busy:
            self.status_label.setText("Scheduling matches…")

    def _open_results(self, match_id: str = "") -> None:
        if self.scheduling or self.read_only or self.tournament is None:
            return
        if not any(
            item.match_id == match_id and item.status == "in_progress"
            for item in self.tournament.progress
        ):
            return
        dialog = _ResultDialog(self.tournament, self, match_id)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.result_requested.emit(*dialog.selection())

    def _measure_cards(self) -> None:
        font = QFont(self.font())
        font.setPointSize(BODY_POINT_SIZE)
        self._card_height = max(_CARD_HEIGHT, 136 + 2 * QFontMetrics(font).lineSpacing())
        font.setBold(True)
        metrics = QFontMetrics(font)
        self._card_width = max(
            _CARD_WIDTH,
            metrics.horizontalAdvance("RESET")
            + metrics.horizontalAdvance(f"Table {self.table_count}")
            + 40,
        )

    def _place_section(self, matches: list[PreviewMatch], top: float) -> float:
        if not matches:
            self._text("Loser of W1 advances to the grand final.", QPointF(20, top + 44))
            return top + 120
        rounds: dict[int, list[PreviewMatch]] = {}
        for match in matches:
            rounds.setdefault(match.round_number, []).append(match)
        height = max(len(group) for group in rounds.values()) * (
            self._card_height + _ROW_STEP - _CARD_HEIGHT
        )
        for round_number, group in rounds.items():
            x = 20 + (round_number - 1) * (self._card_width + _COLUMN_STEP - _CARD_WIDTH)
            for index, match in enumerate(group):
                y = top + (index + 0.5) * height / len(group) - self._card_height / 2
                self._card(match, QRectF(x, y, self._card_width, self._card_height))
        return top + height

    def _place_finals(self, draw: Draw) -> None:
        columns = max(match.round_number for match in draw.matches if match.section != "Finals")
        column_step = self._card_width + _COLUMN_STEP - _CARD_WIDTH
        x = 20 + columns * column_step
        upper = [rect.center().y() for key, rect in self.match_rects.items() if key.startswith("W")]
        lower = [rect.center().y() for key, rect in self.match_rects.items() if key.startswith("L")]
        y = (sum(upper) / len(upper) + (sum(lower) / len(lower) if lower else max(upper) + 160)) / 2
        for match in draw.matches:
            if match.section == "Finals":
                self._card(
                    match, QRectF(x, y - self._card_height / 2, self._card_width, self._card_height)
                )
                y += self._card_height + _ROW_STEP - _CARD_HEIGHT

    def _set_column_headings(self, draw: Draw) -> None:
        """Build the complete header once per draw, independently of the viewport."""
        columns: dict[float, tuple[str, QRectF]] = {}
        for match in draw.matches:
            rectangle = self.match_rects[match.identifier]
            label = "Final" if match.section == "Finals" else f"Round {match.round_number}"
            column = QRectF(rectangle)
            column.setWidth(self._card_width + _COLUMN_STEP - _CARD_WIDTH)
            column.moveCenter(rectangle.center())
            columns.setdefault(column.center().x(), (label, column))
        self.graphics.columns = tuple(columns[key] for key in sorted(columns))

    def _text(
        self,
        text: str,
        position: QPointF,
        *,
        bold: bool = False,
        color_role: QPalette.ColorRole = QPalette.ColorRole.WindowText,
    ) -> QGraphicsTextItem:
        font = QFont(self.font())
        font.setPointSize(BODY_POINT_SIZE)
        font.setBold(bold)
        item = self.scene.addText(text, font)
        item.setDefaultTextColor(self.palette().color(color_role))
        item.setPos(position)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        return item

    def _slot_label(self, source: Source) -> str:
        assert self.draw is not None
        if source.player_index is not None:
            return self.draw.names[source.player_index]
        if source.match_id is not None:
            if source.match_id in self.outcomes:
                player_index = self.outcomes[source.match_id][int(source.loser)]
                return self.draw.names[player_index] if player_index is not None else "Bye"
            outcome = "Loser" if source.loser else "Winner"
            return f"{outcome} of {_display_match_id(source.match_id)}"
        return "Bye"

    def _card(self, match: PreviewMatch, rectangle: QRectF) -> None:
        self.match_rects[match.identifier] = rectangle
        pen = QPen(Qt.GlobalColor.white)
        pen.setWidthF(_LINE_WIDTH)
        active = self.tournament is not None and any(
            item.match_id == match.identifier and item.status == "in_progress"
            for item in self.tournament.progress
        )
        card = (
            _MatchCard(rectangle, match.identifier, self._open_results)
            if active
            else QGraphicsRectItem(rectangle)
        )
        card.setPen(pen)
        card.setBrush(self.palette().brush(QPalette.ColorRole.Base))
        self.scene.addItem(card)
        origin = rectangle.topLeft()
        self._card_text(_display_match_id(match.identifier), origin + QPointF(12, 8), bold=True)
        self._table_badge(match, rectangle)
        for source, offset in zip(match.slots, [44, 80], strict=True):
            self._card_text(self._slot_label(source), origin + QPointF(12, offset))
        self._card_note(self._match_note(match), origin + QPointF(12, 116))

    def _table_badge(self, match: PreviewMatch, rectangle: QRectF) -> None:
        if self.tournament is None:
            return
        progress = next(
            (item for item in self.tournament.progress if item.match_id == match.identifier), None
        )
        if progress is None or progress.status != "in_progress":
            return
        assert progress.table_number is not None
        text = f"Table {progress.table_number}"
        item = self._text(text, rectangle.topLeft() + QPointF(12, 8), bold=True)
        item.setX(rectangle.right() - 12 - item.boundingRect().width())
        background = self.palette().color(QPalette.ColorRole.Base)
        item.setDefaultTextColor(
            QColor(
                "#15803d" if background.lightness() >= _LIGHT_BACKGROUND_THRESHOLD else "#4ade80"
            )
        )
        labels = {table.number: table.label for table in self.tournament.table_labels}
        item.setToolTip(labels.get(progress.table_number, text))

    def _card_note(self, text: str, position: QPointF) -> None:
        item = self._text(text, position, color_role=QPalette.ColorRole.Text)
        item.setTextWidth(self._card_width - 24)
        item.setToolTip(text)
        metrics = QFontMetrics(item.font())
        candidate = metrics.elidedText(
            text, Qt.TextElideMode.ElideRight, round(2 * (self._card_width - 32))
        )
        item.setPlainText(candidate)
        while len(candidate) > 1 and item.boundingRect().height() > 2 * metrics.lineSpacing() + 8:
            candidate = candidate[:-2].rstrip() + "…"
            item.setPlainText(candidate)

    def _card_text(self, text: str, position: QPointF, *, bold: bool = False) -> None:
        item = self._text(text, position, bold=bold, color_role=QPalette.ColorRole.Text)
        item.setPlainText(
            QFontMetrics(item.font()).elidedText(
                text, Qt.TextElideMode.ElideRight, round(self._card_width - 32)
            )
        )
        item.setToolTip(text)

    def _match_note(self, match: PreviewMatch) -> str:
        if self.tournament is not None:
            for item in self.tournament.progress:
                if item.match_id == match.identifier and item.status == "completed":
                    assert item.winner_index is not None
                    return f"Winner: {self.tournament.draw.names[item.winner_index]}"
                if item.match_id == match.identifier and item.status == "in_progress":
                    assert item.table_number is not None
                    labels = {table.number: table.label for table in self.tournament.table_labels}
                    table_label = labels.get(item.table_number, f"Table {item.table_number}")
                    return f"In progress · {table_label}"
        return self._preview_note(match)

    def _preview_note(self, match: PreviewMatch) -> str:
        if match.conditional:
            if "GF" in self.outcomes and self.tournament is not None:
                final = next(
                    item for item in self.tournament.draw.matches if item.identifier == "GF"
                )
                upper = final.slots[0]
                upper_player = (
                    self.outcomes[upper.match_id][int(upper.loser)]
                    if upper.match_id is not None
                    else upper.player_index
                )
                if self.outcomes["GF"][0] == upper_player:
                    return "Not needed"
            return "If losers' finalist wins F1"
        if all(source.empty for source in match.slots):
            return "Unused slot"
        return ""

    def _draw_connectors(self, draw: Draw) -> None:
        matches = {match.identifier: match for match in draw.matches}
        for match in draw.matches:
            for index, source in enumerate(match.slots):
                if source.match_id is None:
                    continue
                earlier = matches[source.match_id]
                if match.section in {"Finals", earlier.section}:
                    self._connector(
                        self.match_rects[source.match_id],
                        self.match_rects[match.identifier],
                        index,
                        loser=source.loser,
                    )

    def _connector(self, source: QRectF, target: QRectF, slot: int, *, loser: bool) -> None:
        if source.center().x() == target.center().x():
            path = self._vertical_path(source, target, slot)
        else:
            start = QPointF(source.right(), source.center().y())
            end = QPointF(target.left(), target.top() + 60 + slot * 36)
            middle_x = end.x() - 30
            path = QPainterPath(start)
            path.lineTo(middle_x, start.y())
            path.lineTo(middle_x, end.y())
            path.lineTo(end)
        pen = QPen(Qt.GlobalColor.white)
        pen.setWidthF(_LINE_WIDTH)
        if loser:
            pen.setStyle(Qt.PenStyle.DashLine)
        self.scene.addPath(path, pen).setZValue(-1)

    @staticmethod
    def _vertical_path(source: QRectF, target: QRectF, slot: int) -> QPainterPath:
        start = QPointF(source.center().x(), source.bottom())
        end = QPointF(target.center().x() + (slot - 0.5) * 40, target.top())
        middle_y = (start.y() + end.y()) / 2
        path = QPainterPath(start)
        path.lineTo(start.x(), middle_y)
        path.lineTo(end.x(), middle_y)
        path.lineTo(end)
        return path
