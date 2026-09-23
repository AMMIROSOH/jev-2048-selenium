from __future__ import annotations

import math
import time
from dataclasses import dataclass
from functools import lru_cache

from .board import Board, Direction, MoveResult, add_tile, board_features, empty_cells, exponents, legal_moves


class SearchTimeout(Exception):
    pass


@dataclass(frozen=True)
class MoveAnalysis:
    direction: Direction
    value: float
    score_gain: int
    after: Board
    features: dict[str, float | int | bool]


@dataclass(frozen=True)
class SearchResult:
    analyses: tuple[MoveAnalysis, ...]
    completed_depth: int
    nodes: int
    elapsed_ms: float


def _snake_patterns() -> tuple[tuple[tuple[int, ...], ...], ...]:
    base = (
        (16, 15, 14, 13),
        (9, 10, 11, 12),
        (8, 7, 6, 5),
        (1, 2, 3, 4),
    )

    def rotate(matrix: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, ...], ...]:
        return tuple(tuple(matrix[3 - row][column] for row in range(4)) for column in range(4))

    patterns: list[tuple[tuple[int, ...], ...]] = []
    current = base
    for _ in range(4):
        patterns.append(current)
        patterns.append(tuple(tuple(reversed(row)) for row in current))
        current = rotate(current)
    return tuple(patterns)


# A fixed corner prevents the policy from undoing its own structure by moving the
# largest tile between otherwise symmetric corners. This pattern anchors at the
# bottom-left and snakes toward the top-left.
ANCHOR_SNAKE = (
    (1, 2, 3, 4),
    (8, 7, 6, 5),
    (9, 10, 11, 12),
    (16, 15, 14, 13),
)


@lru_cache(maxsize=200_000)
def evaluate(board: Board) -> float:
    features = board_features(board)
    logs = exponents(board)
    snake = sum(logs[row][column] * ANCHOR_SNAKE[row][column] for row in range(4) for column in range(4))
    max_exp = int(features["max_exponent"])
    max_positions = [
        (row, column)
        for row in range(4)
        for column in range(4)
        if logs[row][column] == max_exp and max_exp > 0
    ]
    anchor_distance = min((abs(3 - row) + column for row, column in max_positions), default=0)
    anchor_value = max_exp * (180.0 if anchor_distance == 0 else -120.0 * anchor_distance)
    return (
        float(features["empty_cells"]) * 280.0
        + float(features["monotonicity"]) * 47.0
        + float(features["smoothness"]) * 15.0
        + float(features["merge_pairs"]) * 65.0
        + anchor_value
        + snake * 4.0
    )


def normalized_probabilities(analyses: tuple[MoveAnalysis, ...]) -> dict[Direction, float]:
    if not analyses:
        return {}
    values = [item.value for item in analyses]
    spread = max(values) - min(values)
    if spread < 1e-9:
        return {item.direction: 1.0 / len(analyses) for item in analyses}
    temperature = max(spread * 0.30, 1.0)
    weights = [math.exp(max(-50.0, (item.value - max(values)) / temperature)) for item in analyses]
    total = sum(weights)
    return {item.direction: weight / total for item, weight in zip(analyses, weights)}


class ExpectimaxSolver:
    def __init__(self, time_budget_ms: int = 250, max_depth: int | None = None) -> None:
        self.time_budget_ms = max(10, time_budget_ms)
        self.max_depth = max_depth

    def _target_depth(self, board: Board) -> int:
        if self.max_depth is not None:
            return max(1, self.max_depth)
        empty = len(empty_cells(board))
        if empty >= 10:
            return 3
        if empty >= 6:
            return 4
        if empty >= 3:
            return 5
        return 6

    def rank_moves(self, board: Board) -> SearchResult:
        started = time.perf_counter()
        deadline = started + self.time_budget_ms / 1000.0
        root_moves = legal_moves(board)
        if not root_moves:
            return SearchResult(analyses=(), completed_depth=0, nodes=0, elapsed_ms=0.0)

        best_values: dict[Direction, float] = {
            direction: result.score_gain + evaluate(result.board) for direction, result in root_moves.items()
        }
        completed_depth = 0
        total_nodes = 0

        for depth in range(1, self._target_depth(board) + 1):
            nodes = 0

            def check_time() -> None:
                if time.perf_counter() >= deadline:
                    raise SearchTimeout

            @lru_cache(maxsize=None)
            def player_value(state: Board, remaining: int) -> float:
                nonlocal nodes
                nodes += 1
                if nodes & 127 == 0:
                    check_time()
                if remaining <= 0:
                    return evaluate(state)
                moves = legal_moves(state)
                if not moves:
                    return evaluate(state) - 100_000.0
                return max(result.score_gain + chance_value(result.board, remaining - 1) for result in moves.values())

            @lru_cache(maxsize=None)
            def chance_value(state: Board, remaining: int) -> float:
                nonlocal nodes
                nodes += 1
                if nodes & 127 == 0:
                    check_time()
                cells = empty_cells(state)
                if not cells:
                    return player_value(state, remaining)
                probability = 1.0 / len(cells)
                expected = 0.0
                for row, column in cells:
                    expected += probability * (
                        0.9 * player_value(add_tile(state, row, column, 2), remaining)
                        + 0.1 * player_value(add_tile(state, row, column, 4), remaining)
                    )
                return expected

            try:
                iteration = {
                    direction: result.score_gain + chance_value(result.board, depth - 1)
                    for direction, result in root_moves.items()
                }
                check_time()
            except SearchTimeout:
                total_nodes += nodes
                break
            else:
                best_values = iteration
                completed_depth = depth
                total_nodes += nodes

        analyses = tuple(
            sorted(
                (
                    MoveAnalysis(
                        direction=direction,
                        value=best_values[direction],
                        score_gain=result.score_gain,
                        after=result.board,
                        features=board_features(result.board),
                    )
                    for direction, result in root_moves.items()
                ),
                key=lambda item: item.value,
                reverse=True,
            )
        )
        elapsed = (time.perf_counter() - started) * 1000.0
        return SearchResult(analyses=analyses, completed_depth=completed_depth, nodes=total_nodes, elapsed_ms=elapsed)
