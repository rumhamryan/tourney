"""Generate a complete draw for display without recording match results."""

from collections.abc import Sequence
from dataclasses import dataclass

from bracket import create_bracket


@dataclass(frozen=True)
class Source:
    """A player, an earlier match's outcome, or an empty bye slot."""

    player_index: int | None = None
    match_id: str | None = None
    loser: bool = False

    @property
    def empty(self) -> bool:
        return self.player_index is None and self.match_id is None


@dataclass(frozen=True)
class PreviewMatch:
    """One numbered position in the draw, including automatic byes."""

    identifier: str
    section: str
    round_number: int
    slots: tuple[Source, Source]
    conditional: bool = False


@dataclass(frozen=True)
class Draw:
    """An immutable draw; player indices distinguish repeated names."""

    names: tuple[str, ...]
    tournament_format: str
    matches: tuple[PreviewMatch, ...]


def _outcome(match: PreviewMatch, *, loser: bool = False) -> Source:
    present = [source for source in match.slots if not source.empty]
    if len(present) < len(match.slots):
        return present[0] if present and not loser else Source()
    return Source(match_id=match.identifier, loser=loser)


def _pairs(sources: Sequence[Source]) -> list[tuple[Source, Source]]:
    return list(zip(sources[::2], sources[1::2], strict=True))


def _add_round(
    matches: list[PreviewMatch],
    slots: Sequence[tuple[Source, Source]],
    *,
    section: str,
    round_number: int,
) -> list[PreviewMatch]:
    prefix = "W" if section == "Winners" else "L"
    offset = sum(match.section == section for match in matches)
    new_matches = [
        PreviewMatch(f"{prefix}{offset + index + 1}", section, round_number, pair)
        for index, pair in enumerate(slots)
    ]
    matches.extend(new_matches)
    return new_matches


def _winners_rounds(names: Sequence[str], matches: list[PreviewMatch]) -> list[list[PreviewMatch]]:
    openings = create_bracket([str(index) for index in range(len(names))])
    slots = [
        (
            Source(player_index=int(first)),
            Source(player_index=int(second)) if second is not None else Source(),
        )
        for first, second in openings
    ]
    rounds = [_add_round(matches, slots, section="Winners", round_number=1)]
    while len(rounds[-1]) > 1:
        sources = [_outcome(match) for match in rounds[-1]]
        rounds.append(
            _add_round(matches, _pairs(sources), section="Winners", round_number=len(rounds) + 1)
        )
    return rounds


def _losers_finalist(winners: list[list[PreviewMatch]], matches: list[PreviewMatch]) -> Source:
    sources = [_outcome(match, loser=True) for match in winners[0]]
    if len(sources) == 1:
        return sources[0]
    last = _add_round(matches, _pairs(sources), section="Losers", round_number=1)
    round_number = 1
    for index, winner_round in enumerate(winners[1:], start=1):
        incoming = [_outcome(match, loser=True) for match in reversed(winner_round)]
        surviving = [_outcome(match) for match in last]
        round_number += 1
        last = _add_round(
            matches,
            list(zip(surviving, incoming, strict=True)),
            section="Losers",
            round_number=round_number,
        )
        if index < len(winners) - 1:
            round_number += 1
            last = _add_round(
                matches,
                _pairs([_outcome(match) for match in last]),
                section="Losers",
                round_number=round_number,
            )
    return _outcome(last[0])


def build_preview(names: Sequence[str], tournament_format: str) -> Draw:
    """Build a 2–32-player draw in input order, including a conditional reset.

    Automatic bye outcomes are propagated into later slots. Losers enter
    the opposite lower-bracket grouping to avoid immediate rematches.
    Names are not shuffled here; callers control the initial draw order.
    """
    if tournament_format not in {"Single Elimination", "Double Elimination"}:
        raise ValueError(f"Unknown tournament format: {tournament_format}")
    matches: list[PreviewMatch] = []
    winners = _winners_rounds(names, matches)
    if tournament_format == "Double Elimination":
        lower = _losers_finalist(winners, matches)
        final = PreviewMatch("GF", "Finals", 1, (_outcome(winners[-1][0]), lower))
        matches.append(final)
        matches.append(
            PreviewMatch("RESET", "Finals", 2, (_outcome(final), _outcome(final, loser=True)), True)
        )
    return Draw(tuple(names), tournament_format, tuple(matches))
