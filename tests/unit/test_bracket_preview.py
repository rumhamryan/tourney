from collections import Counter

import pytest

from bracket_preview import Draw, Source, build_preview


def test_eight_player_double_elimination_routes_losers_and_finals() -> None:
    names = [f"Player {index}" for index in range(8)]
    draw = build_preview(names, "Double Elimination")
    matches = {match.identifier: match for match in draw.matches}

    assert matches["L1"].slots == (
        Source(match_id="W1", loser=True),
        Source(match_id="W2", loser=True),
    )
    assert matches["L3"].slots == (Source(match_id="L1"), Source(match_id="W6", loser=True))
    assert matches["L4"].slots == (Source(match_id="L2"), Source(match_id="W5", loser=True))
    assert matches["GF"].slots == (Source(match_id="W7"), Source(match_id="L6"))
    assert matches["RESET"].slots == (Source(match_id="GF"), Source(match_id="GF", loser=True))
    assert matches["RESET"].conditional


@pytest.mark.parametrize("player_count", range(2, 33))
@pytest.mark.parametrize("tournament_format", ["Single Elimination", "Double Elimination"])
def test_draw_preserves_players_and_has_only_backward_references(
    player_count: int, tournament_format: str
) -> None:
    names = [f"Player {index}" for index in range(player_count)]
    draw = build_preview(names, tournament_format)
    seen: set[str] = set()
    initial_players: list[int] = []

    for match in draw.matches:
        assert match.identifier not in seen
        for source in match.slots:
            if source.match_id is not None:
                assert source.match_id in seen
            if (
                match.section == "Winners"
                and match.round_number == 1
                and source.player_index is not None
            ):
                initial_players.append(source.player_index)
        seen.add(match.identifier)

    assert initial_players == list(range(player_count))
    assert draw.names == tuple(names)
    assert names == [f"Player {index}" for index in range(player_count)]


def _resolve(source: Source, results: dict[str, tuple[int | None, int | None]]) -> int | None:
    if source.match_id is None:
        return source.player_index
    return results[source.match_id][int(source.loser)]


def _play_draw(draw: Draw, lower_finalist_wins: bool) -> tuple[Counter[int], int]:
    results: dict[str, tuple[int | None, int | None]] = {}
    losses: Counter[int] = Counter()
    played = 0
    for match in draw.matches:
        if match.conditional and not lower_finalist_wins:
            continue
        players = [_resolve(source, results) for source in match.slots]
        present = [player for player in players if player is not None]
        if len(present) < len(match.slots):
            results[match.identifier] = (present[0] if present else None, None)
            continue
        assert present[0] != present[1]
        if match.section == "Losers":
            assert [losses[player] for player in present] == [1, 1]
        elif match.section == "Winners":
            assert [losses[player] for player in present] == [0, 0]
        winner_index = int(match.identifier == "GF" and lower_finalist_wins)
        winner, loser = present[winner_index], present[1 - winner_index]
        losses[loser] += 1
        results[match.identifier] = (winner, loser)
        played += 1
    return losses, played


@pytest.mark.parametrize("player_count", range(2, 33))
@pytest.mark.parametrize("lower_finalist_wins", [False, True])
def test_double_draw_eliminates_everyone_after_two_losses(
    player_count: int, lower_finalist_wins: bool
) -> None:
    draw = build_preview([f"Player {index}" for index in range(player_count)], "Double Elimination")
    losses, played = _play_draw(draw, lower_finalist_wins)

    elimination_losses = 2
    assert (
        sum(losses[player] == elimination_losses for player in range(player_count))
        == player_count - 1
    )
    assert played == 2 * player_count - 2 + int(lower_finalist_wins)


@pytest.mark.parametrize("player_count", [0, 1, 33])
def test_preview_rejects_invalid_player_counts(player_count: int) -> None:
    with pytest.raises(ValueError, match="between 2 and 32"):
        build_preview(["Player"] * player_count, "Single Elimination")


def test_preview_rejects_unknown_format() -> None:
    with pytest.raises(ValueError, match="Unknown tournament format"):
        build_preview(["Alice", "Bob"], "Unknown")


def test_duplicate_names_keep_distinct_player_slots() -> None:
    draw = build_preview(["Alice", "Alice"], "Double Elimination")
    assert draw.matches[0].slots == (Source(player_index=0), Source(player_index=1))


@pytest.mark.parametrize("player_count", range(2, 33))
def test_single_draw_has_one_loss_per_eliminated_player(player_count: int) -> None:
    draw = build_preview([f"Player {index}" for index in range(player_count)], "Single Elimination")
    losses, played = _play_draw(draw, False)

    assert sum(losses[player] == 1 for player in range(player_count)) == player_count - 1
    assert played == player_count - 1
