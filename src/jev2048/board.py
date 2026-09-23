from __future__ import annotations

from dataclasses import dataclass
from math import log2
from typing import Iterable, Literal

Direction = Literal["up", "right", "down", "left"]
Board = tuple[tuple[int, ...], ...]
DIRECTIONS: tuple[Direction, ...] = ("up", "right", "down", "left")


@dataclass(frozen=True)
class MoveResult:
    board: Board
    score_gain: int
    moved: bool


def make_board(rows: Iterable[Iterable[int]]) -> Board:
    board = tuple(tuple(int(value) for value in row) for row in rows)
    if len(board) != 4 or any(len(row) != 4 for row in board):
        raise ValueError("A 2048 board must be exactly 4x4")
    if any(value < 0 or (value and value & (value - 1)) for row in board for value in row):
        raise ValueError("Tiles must be zero or positive powers of two")
    return board


def _slide_left(line: tuple[int, ...]) -> tuple[tuple[int, ...], int]:
    compact = [value for value in line if value]
    merged: list[int] = []
    gain = 0
    index = 0
    while index < len(compact):
        if index + 1 < len(compact) and compact[index] == compact[index + 1]:
            value = compact[index] * 2
            merged.append(value)
            gain += value
            index += 2
        else:
            merged.append(compact[index])
            index += 1
    merged.extend([0] * (4 - len(merged)))
    return tuple(merged), gain


def _transpose(board: Board) -> Board:
    return tuple(tuple(board[row][column] for row in range(4)) for column in range(4))


def move(board: Board, direction: Direction) -> MoveResult:
    if direction not in DIRECTIONS:
        raise ValueError(f"Unknown direction: {direction}")

    working = board
    reverse = direction in ("right", "down")
    vertical = direction in ("up", "down")
    if vertical:
        working = _transpose(working)

    rows: list[tuple[int, ...]] = []
    gain = 0
    for row in working:
        oriented = tuple(reversed(row)) if reverse else row
        slid, row_gain = _slide_left(oriented)
        rows.append(tuple(reversed(slid)) if reverse else slid)
        gain += row_gain

    result = tuple(rows)
    if vertical:
        result = _transpose(result)
    return MoveResult(board=result, score_gain=gain, moved=result != board)


def legal_moves(board: Board) -> dict[Direction, MoveResult]:
    return {direction: result for direction in DIRECTIONS if (result := move(board, direction)).moved}


def empty_cells(board: Board) -> tuple[tuple[int, int], ...]:
    return tuple((row, column) for row in range(4) for column in range(4) if board[row][column] == 0)


def add_tile(board: Board, row: int, column: int, value: int) -> Board:
    if board[row][column] != 0:
        raise ValueError("Cannot add a tile to an occupied cell")
    rows = [list(line) for line in board]
    rows[row][column] = value
    return make_board(rows)


def exponents(board: Board) -> tuple[tuple[int, ...], ...]:
    return tuple(tuple(0 if value == 0 else int(log2(value)) for value in row) for row in board)


def board_features(board: Board) -> dict[str, float | int | bool]:
    logs = exponents(board)
    empty = sum(value == 0 for row in board for value in row)
    maximum = max(value for row in board for value in row)
    max_exp = 0 if maximum == 0 else int(log2(maximum))
    corners = (board[0][0], board[0][3], board[3][0], board[3][3])

    smoothness = 0.0
    merge_pairs = 0
    for row in range(4):
        for column in range(4):
            if not board[row][column]:
                continue
            for dr, dc in ((1, 0), (0, 1)):
                nr, nc = row + dr, column + dc
                if nr < 4 and nc < 4 and board[nr][nc]:
                    smoothness -= abs(logs[row][column] - logs[nr][nc])
                    if board[row][column] == board[nr][nc]:
                        merge_pairs += 1

    monotonicity = 0.0
    for lines in (logs, _transpose(logs)):
        decreasing = 0.0
        increasing = 0.0
        for line in lines:
            values = [value for value in line if value]
            for first, second in zip(values, values[1:]):
                if first > second:
                    increasing -= first - second
                else:
                    decreasing -= second - first
        monotonicity += max(decreasing, increasing)

    return {
        "empty_cells": empty,
        "max_tile": maximum,
        "max_in_corner": maximum > 0 and maximum in corners,
        "max_in_anchor_corner": maximum > 0 and board[3][0] == maximum,
        "max_exponent": max_exp,
        "smoothness": smoothness,
        "monotonicity": monotonicity,
        "merge_pairs": merge_pairs,
    }


def compact_board(board: Board) -> str:
    return "/".join(",".join(str(value) for value in row) for row in board)
