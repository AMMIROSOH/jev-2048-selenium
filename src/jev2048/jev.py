from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .board import Board, Direction, board_features
from .search import MoveAnalysis, normalized_probabilities

Mode = Literal["hybrid", "jev", "search"]


@dataclass(frozen=True)
class JevDecision:
    choice: Direction
    probabilities: dict[Direction, float]
    confidence: float
    model: str


@dataclass(frozen=True)
class FinalDecision:
    direction: Direction
    reason: str
    combined_probabilities: dict[Direction, float]


class JevAdvisor:
    def __init__(self, api_key: str, model: str = "jev-latest", timeout: float = 15.0) -> None:
        try:
            from typesafe_sdk import Choice, TypeSafeClient
        except ImportError as error:
            raise RuntimeError("typesafe-sdk is not installed; run: pip install -r requirements.txt") from error
        self._choice_type = Choice
        self._client = TypeSafeClient(api_key=api_key, model=model, timeout=timeout)
        self.model = model

    def close(self) -> None:
        self._client.close()

    def advise(
        self,
        board: Board,
        score: int,
        analyses: tuple[MoveAnalysis, ...],
    ) -> JevDecision:
        local_probabilities = normalized_probabilities(analyses)
        criteria: dict[str, Any] = {}
        candidate_evidence: dict[str, Any] = {}
        for rank, analysis in enumerate(analyses, start=1):
            evidence = {
                "expectimax_rank": rank,
                "search_probability": round(local_probabilities[analysis.direction], 5),
                "immediate_score_gain": analysis.score_gain,
                "board_after_move_before_random_spawn": [list(row) for row in analysis.after],
                **analysis.features,
            }
            candidate_evidence[analysis.direction] = evidence
            criteria[analysis.direction] = {
                "action": f"Slide every tile {analysis.direction.upper()}",
                "evidence": evidence,
            }

        state = {
            "game": "2048 on a 4x4 board",
            "objective": "Maximize long-run score and survival; build 2048 and higher tiles.",
            "rules": [
                "A move slides every tile in one direction.",
                "Equal adjacent tiles merge once per move and add their new value to score.",
                "After each legal move, one random empty cell gets a 2 with probability 0.9 or a 4 with probability 0.1.",
                "The game ends when no legal move remains.",
            ],
            "strategy": [
                "Prefer the expectimax evidence because it already averages all random spawn locations and values.",
                "Preserve empty cells, monotonic order, smooth neighboring values, and the largest tile in a corner.",
                "Immediate merge points are less important than avoiding a future dead board.",
            ],
            "score": score,
            "board_rows_top_to_bottom": [list(row) for row in board],
            "board_features": board_features(board),
            "legal_candidate_evidence": candidate_evidence,
        }
        response = self._client.system_one(
            state=state,
            questions={
                "next_move": self._choice_type(
                    instructions=(
                        "Choose the single best legal next move. Optimize expected long-run survival and score. "
                        "Treat expectimax rank as the strongest evidence and use the strategic features to resolve close alternatives."
                    ),
                    criteria=criteria,
                )
            },
            model=self.model,
        )
        answer = response.answers["next_move"]
        legal = {analysis.direction for analysis in analyses}
        if answer.choice not in legal:
            raise RuntimeError(f"Jev returned non-legal choice: {answer.choice!r}")
        probabilities = {direction: float(answer.probabilities.get(direction, 0.0)) for direction in legal}
        return JevDecision(
            choice=answer.choice,
            probabilities=probabilities,
            confidence=float(answer.confidence),
            model=str(response.model),
        )


def fuse_decision(
    analyses: tuple[MoveAnalysis, ...],
    jev: JevDecision | None,
    mode: Mode = "hybrid",
    jev_weight: float = 0.20,
) -> FinalDecision:
    if not analyses:
        raise ValueError("Cannot choose without legal moves")
    local = normalized_probabilities(analyses)
    local_best = analyses[0].direction
    if mode == "search" or jev is None:
        reason = "expectimax" if mode == "search" else "expectimax fallback (Jev unavailable)"
        return FinalDecision(local_best, reason, local)
    if mode == "jev":
        return FinalDecision(jev.choice, f"Jev {jev.model} strict choice", jev.probabilities)

    weight = min(1.0, max(0.0, jev_weight)) * min(1.0, max(0.0, jev.confidence))
    combined = {
        direction: (1.0 - weight) * local.get(direction, 0.0) + weight * jev.probabilities.get(direction, 0.0)
        for direction in local
    }
    selected = max(combined, key=combined.get)  # type: ignore[arg-type]
    return FinalDecision(
        selected,
        f"confidence-gated fusion (Jev confidence={jev.confidence:.3f}, effective weight={weight:.3f})",
        combined,
    )

