from jev2048.board import make_board
from jev2048.app import parse_args
from jev2048.jev import JevDecision, fuse_decision
from jev2048.search import ExpectimaxSolver, normalized_probabilities


def sample_result():
    board = make_board(
        [
            [128, 64, 32, 16],
            [8, 4, 2, 0],
            [4, 2, 0, 0],
            [2, 0, 0, 0],
        ]
    )
    return ExpectimaxSolver(time_budget_ms=100, max_depth=2).rank_moves(board)


def test_search_returns_only_legal_moves() -> None:
    result = sample_result()
    assert result.analyses
    assert all(item.direction in {"right", "down", "left"} for item in result.analyses)
    assert result.completed_depth >= 1


def test_local_probabilities_sum_to_one() -> None:
    probabilities = normalized_probabilities(sample_result().analyses)
    assert abs(sum(probabilities.values()) - 1.0) < 1e-9


def test_low_confidence_jev_cannot_overrule_clear_search() -> None:
    analyses = sample_result().analyses
    local_best = analyses[0].direction
    other = analyses[-1].direction
    probabilities = {item.direction: (1.0 if item.direction == other else 0.0) for item in analyses}
    jev = JevDecision(choice=other, probabilities=probabilities, confidence=0.0, model="test")
    assert fuse_decision(analyses, jev, mode="hybrid", jev_weight=1.0).direction == local_best


def test_strict_jev_mode_uses_jev_choice() -> None:
    analyses = sample_result().analyses
    choice = analyses[-1].direction
    probabilities = {item.direction: (1.0 if item.direction == choice else 0.0) for item in analyses}
    jev = JevDecision(choice=choice, probabilities=probabilities, confidence=1.0, model="test")
    assert fuse_decision(analyses, jev, mode="jev").direction == choice


def test_recording_cli_defaults() -> None:
    args = parse_args(["--record", "--mode", "search"])
    assert args.record is True
    assert (args.capture_width, args.capture_height) == (540, 960)
    assert (args.fps, args.crf, args.preset) == (60, 16, "slow")
