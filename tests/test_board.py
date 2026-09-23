from jev2048.board import add_tile, empty_cells, legal_moves, make_board, move


def test_merge_once_per_move() -> None:
    board = make_board([[2, 2, 2, 2], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]])
    result = move(board, "left")
    assert result.board[0] == (4, 4, 0, 0)
    assert result.score_gain == 8


def test_newly_merged_tile_does_not_merge_again() -> None:
    board = make_board([[2, 2, 4, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]])
    result = move(board, "left")
    assert result.board[0] == (4, 4, 0, 0)
    assert result.score_gain == 4


def test_vertical_move_and_score() -> None:
    board = make_board([[2, 0, 0, 0], [2, 0, 0, 0], [4, 0, 0, 0], [4, 0, 0, 0]])
    result = move(board, "down")
    assert tuple(row[0] for row in result.board) == (0, 0, 4, 8)
    assert result.score_gain == 12


def test_illegal_move_is_excluded() -> None:
    board = make_board([[2, 4, 8, 16], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]])
    assert "up" not in legal_moves(board)
    assert set(legal_moves(board)) == {"down"}


def test_spawn_helper() -> None:
    board = make_board([[2, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]])
    spawned = add_tile(board, 3, 3, 4)
    assert spawned[3][3] == 4
    assert len(empty_cells(spawned)) == 14
