"""Event-driven, equal-duration table dispatch independent of the desktop UI.

Each event gives running matches one remaining unit. Future schedules are
provisional; only ready matches selected for time zero receive physical tables.
"""

from dataclasses import dataclass, replace

from ortools.sat.python import cp_model

from bracket_preview import PreviewMatch
from tournament_state import (
    MatchProgress,
    TournamentState,
    champion_index,
    ready_matches,
    resolved_outcomes,
    validate_tournament,
)

_SOLVER_TIME_LIMIT = 1.0


@dataclass(frozen=True)
class SchedulingResult:
    """Updated assignments and diagnostics for the modeled remaining tournament."""

    state: TournamentState
    algorithm: str
    solver_status: str | None = None
    makespan_units: int | None = None


@dataclass(frozen=True)
class _Task:
    identifier: str
    duration: int
    predecessors: tuple[str, ...]


def _tasks(state: TournamentState) -> tuple[_Task, ...]:
    outcomes = resolved_outcomes(state)
    finished = champion_index(state) is not None
    matches = [
        match
        for match in state.draw.matches
        if match.identifier not in outcomes and not (match.conditional and finished)
    ]
    remaining = {match.identifier for match in matches}
    return tuple(
        _Task(
            match.identifier,
            int(not any(source.empty for source in match.slots)),
            tuple(
                dict.fromkeys(
                    source.match_id for source in match.slots if source.match_id in remaining
                )
            ),
        )
        for match in matches
    )


def _priority(ready: tuple[PreviewMatch, ...], tasks: tuple[_Task, ...]) -> tuple[str, ...]:
    levels = {task.identifier: task.duration for task in tasks}
    for task in reversed(tasks):
        for predecessor in task.predecessors:
            duration = next(item.duration for item in tasks if item.identifier == predecessor)
            levels[predecessor] = max(levels[predecessor], duration + levels[task.identifier])
    return tuple(
        match.identifier for match in sorted(ready, key=lambda match: -levels[match.identifier])
    )


class _CpSchedule:
    def __init__(self, tasks: tuple[_Task, ...]) -> None:
        self.model = cp_model.CpModel()
        self.horizon = max(1, sum(task.duration for task in tasks))
        self.starts: dict[str, cp_model.IntVar] = {}
        self.ends: dict[str, cp_model.IntVar] = {}
        self.intervals: list[cp_model.IntervalVar] = []
        self.demands: list[int] = []
        for task in tasks:
            self._add_task(task)
        for task in tasks:
            for predecessor in task.predecessors:
                self.model.add(self.starts[task.identifier] >= self.ends[predecessor])

    def _add_task(self, task: _Task) -> None:
        start = self.model.new_int_var(0, self.horizon, f"start_{task.identifier}")
        end = self.model.new_int_var(0, self.horizon, f"end_{task.identifier}")
        self.starts[task.identifier] = start
        self.ends[task.identifier] = end
        self.intervals.append(
            self.model.new_interval_var(start, task.duration, end, task.identifier)
        )
        self.demands.append(task.duration)

    def constrain_dispatch(
        self, active: tuple[str, ...], ready: tuple[str, ...], capacity: int
    ) -> None:
        self.model.add_cumulative(self.intervals, self.demands, capacity)
        for identifier in active:
            self.model.add(self.starts[identifier] == 0)
        immediate: list[cp_model.IntVar] = []
        for identifier in ready:
            starts_now = self.model.new_bool_var(f"now_{identifier}")
            self.model.add(self.starts[identifier] == 0).only_enforce_if(starts_now)
            self.model.add(self.starts[identifier] != 0).only_enforce_if(starts_now.Not())
            immediate.append(starts_now)
        self.model.add(sum(immediate) == min(len(ready), capacity - len(active)))

    def solve(self, ready: tuple[str, ...]) -> tuple[str, tuple[str, ...], int | None]:
        makespan = self.model.new_int_var(0, self.horizon, "makespan")
        self.model.add_max_equality(makespan, list(self.ends.values()))
        self.model.minimize(makespan)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = _SOLVER_TIME_LIMIT
        solver.parameters.absolute_gap_limit = 0
        solver.parameters.relative_gap_limit = 0
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0
        status = solver.solve(self.model)
        if status != cp_model.OPTIMAL:
            return solver.status_name(status), (), None
        selected = tuple(
            identifier for identifier in ready if solver.value(self.starts[identifier]) == 0
        )
        return solver.status_name(status), selected, solver.value(makespan)


def _solve_cp(
    state: TournamentState, tasks: tuple[_Task, ...], ready: tuple[PreviewMatch, ...]
) -> tuple[str, tuple[str, ...], int | None]:
    problem = _CpSchedule(tasks)
    active = tuple(item.match_id for item in state.progress if item.status == "in_progress")
    identifiers = tuple(match.identifier for match in ready)
    problem.constrain_dispatch(active, identifiers, min(state.table_count, sum(problem.demands)))
    return problem.solve(identifiers)


def _assign(state: TournamentState, selected: tuple[str, ...]) -> TournamentState:
    occupied = {item.table_number for item in state.progress if item.status == "in_progress"}
    progress = list(state.progress)
    table = 1
    for identifier in selected[: state.table_count - len(occupied)]:
        while table in occupied:
            table += 1
        progress = [item for item in progress if item.match_id != identifier]
        progress.append(MatchProgress(identifier, "in_progress", table_number=table))
        occupied.add(table)
    result = replace(
        state, progress=tuple(progress), draw_locked=state.draw_locked or bool(selected)
    )
    validate_tournament(result)
    return result


def schedule_tables(state: TournamentState) -> SchedulingResult:
    """Fill available tables using Hu or a proven CP-SAT plan, with bounded fallback.

    Existing physical assignments are never moved. Invalid snapshots raise
    ValueError; no future match receives an assignment before both players exist.
    """
    validate_tournament(state)
    ready = ready_matches(state)
    tasks = _tasks(state)
    algorithm = "hu" if state.draw.tournament_format == "Single Elimination" else "cp_sat"
    occupied = sum(item.status == "in_progress" for item in state.progress)
    if not ready or occupied == state.table_count:
        return SchedulingResult(state, algorithm)
    selected = _priority(ready, tasks)
    status: str | None = None
    makespan: int | None = None
    if algorithm == "cp_sat":
        status, optimized, makespan = _solve_cp(state, tasks, ready)
        if status == "OPTIMAL":
            selected = optimized
        else:
            algorithm = "critical_path"
    return SchedulingResult(_assign(state, selected), algorithm, status, makespan)
