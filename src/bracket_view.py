"""Display a scrollable, read-only tournament draw."""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QFont,
    QFontMetrics,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bracket_preview import Draw, PreviewMatch, Source
from tournament_state import Outcome, TournamentState, resolved_outcomes, validate_tournament

_CARD_WIDTH = 216
_CARD_HEIGHT = 100
_COLUMN_STEP = 292
_ROW_STEP = 124


class BracketView(QWidget):
    """Show match sources, automatic byes, and the conditional grand final."""

    back_requested = Signal()
    save_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.draw: Draw | None = None
        self.tournament: TournamentState | None = None
        self.outcomes: dict[str, Outcome] = {}
        self.table_count = 1
        self.match_rects: dict[str, QRectF] = {}
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(32)
        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(self.palette().brush(QPalette.ColorRole.Window))
        self.graphics = QGraphicsView(self.scene)
        self.graphics.setAccessibleName("Tournament bracket")
        self.graphics.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.graphics.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.graphics.setMinimumSize(260, 200)
        self.back_button = QPushButton("&Back to Setup")
        self.back_button.setMinimumHeight(40)
        self.back_button.setAutoDefault(False)
        self.back_button.clicked.connect(self.back_requested.emit)
        self.save_button = QPushButton("&Save As…")
        self.save_button.setMinimumHeight(40)
        self.save_button.setAutoDefault(False)
        self.save_button.clicked.connect(self.save_requested.emit)
        self._build_layout()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Bracket Preview")
        font = title.font()
        font.setPointSize(20)
        font.setBold(True)
        title.setFont(font)
        self.hint_label = QLabel("Scroll to see all rounds. Return to setup to edit the draw.")
        self.hint_label.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.graphics, 1)
        actions = QHBoxLayout()
        actions.addWidget(self.save_button)
        actions.addWidget(self.back_button)
        layout.addLayout(actions)
        self._connect_keyboard()

    def _connect_keyboard(self) -> None:
        for button in [self.save_button, self.back_button]:
            self._button_shortcuts(button)
        shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.SaveAs), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.save_button.click)

    def _button_shortcuts(self, button: QPushButton) -> None:
        for key in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
            shortcut = QShortcut(QKeySequence(key), button)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(button.click)

    def show_draw(self, draw: Draw, table_count: int) -> None:
        """Replace the preview while preserving its immutable setup snapshot."""
        if table_count < 1:
            raise ValueError("At least one table is required.")
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
        self.hint_label.setText(
            "Scroll to see all rounds. The draw is locked because play has started."
            if locked
            else "Scroll to see all rounds. Return to setup to edit the draw."
        )
        table_word = "table" if table_count == 1 else "tables"
        self.summary_label.setText(
            f"{draw.tournament_format} · {len(draw.names)} players · {table_count} {table_word}"
        )
        self.scene.clear()
        self.scene.setBackgroundBrush(self.palette().brush(QPalette.ColorRole.Window))
        self.match_rects.clear()
        winners = [match for match in draw.matches if match.section == "Winners"]
        bottom = self._place_section(winners, "Winners' bracket", 20)
        if draw.tournament_format == "Double Elimination":
            losers = [match for match in draw.matches if match.section == "Losers"]
            self._place_section(losers, "Losers' bracket", bottom + 40)
            self._place_finals(draw)
        self._draw_connectors(draw)
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20))
        self.graphics.horizontalScrollBar().setValue(0)
        self.graphics.verticalScrollBar().setValue(0)

    def _place_section(self, matches: list[PreviewMatch], title: str, top: float) -> float:
        self._text(title, QPointF(20, top), bold=True)
        if not matches:
            self._text("Loser of W1 advances to the grand final.", QPointF(20, top + 30))
            return top + 90
        rounds: dict[int, list[PreviewMatch]] = {}
        for match in matches:
            rounds.setdefault(match.round_number, []).append(match)
        height = max(len(group) for group in rounds.values()) * _ROW_STEP
        for round_number, group in rounds.items():
            x = 20 + (round_number - 1) * _COLUMN_STEP
            self._text(f"Round {round_number}", QPointF(x, top + 28))
            for index, match in enumerate(group):
                y = top + 60 + (index + 0.5) * height / len(group) - _CARD_HEIGHT / 2
                self._card(match, QRectF(x, y, _CARD_WIDTH, _CARD_HEIGHT))
        return top + 60 + height

    def _place_finals(self, draw: Draw) -> None:
        columns = max(match.round_number for match in draw.matches if match.section != "Finals")
        x = 20 + columns * _COLUMN_STEP
        upper = [rect.center().y() for key, rect in self.match_rects.items() if key.startswith("W")]
        lower = [rect.center().y() for key, rect in self.match_rects.items() if key.startswith("L")]
        y = (sum(upper) / len(upper) + (sum(lower) / len(lower) if lower else max(upper) + 160)) / 2
        self._text("Grand final", QPointF(x, y - 80), bold=True)
        for match in draw.matches:
            if match.section == "Finals":
                self._card(match, QRectF(x, y - _CARD_HEIGHT / 2, _CARD_WIDTH, _CARD_HEIGHT))
                x += _COLUMN_STEP

    def _text(
        self,
        text: str,
        position: QPointF,
        *,
        bold: bool = False,
        color_role: QPalette.ColorRole = QPalette.ColorRole.WindowText,
    ) -> QGraphicsTextItem:
        font = QFont(self.font())
        font.setBold(bold)
        item = self.scene.addText(text, font)
        item.setDefaultTextColor(self.palette().color(color_role))
        item.setPos(position)
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
            return f"{outcome} of {source.match_id}"
        return "Bye"

    def _card(self, match: PreviewMatch, rectangle: QRectF) -> None:
        self.match_rects[match.identifier] = rectangle
        self.scene.addRect(
            rectangle,
            QPen(Qt.GlobalColor.white),
            self.palette().brush(QPalette.ColorRole.Base),
        )
        origin = rectangle.topLeft()
        self._card_text(match.identifier, origin + QPointF(8, 2), bold=True)
        for source, offset in zip(match.slots, [28, 51], strict=True):
            self._card_text(self._slot_label(source), origin + QPointF(8, offset))
        self._card_text(self._match_note(match), origin + QPointF(8, 74))

    def _card_text(self, text: str, position: QPointF, *, bold: bool = False) -> None:
        item = self._text(text, position, bold=bold, color_role=QPalette.ColorRole.Text)
        item.setPlainText(
            QFontMetrics(item.font()).elidedText(
                text, Qt.TextElideMode.ElideRight, _CARD_WIDTH - 24
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
            return "If losers' finalist wins GF"
        if all(source.empty for source in match.slots):
            return "Unused slot"
        if any(source.empty for source in match.slots):
            return "Bye: automatic advance"
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
        start = QPointF(source.right(), source.center().y())
        end = QPointF(target.left(), target.top() + 40 + slot * 23)
        middle_x = end.x() - 30
        path = QPainterPath(start)
        path.lineTo(middle_x, start.y())
        path.lineTo(middle_x, end.y())
        path.lineTo(end)
        pen = QPen(Qt.GlobalColor.white)
        if loser:
            pen.setStyle(Qt.PenStyle.DashLine)
        self.scene.addPath(path, pen).setZValue(-1)
