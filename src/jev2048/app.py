from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .board import Board, compact_board
from .browser import GameBrowser
from .jev import JevAdvisor, JevDecision, Mode, fuse_decision
from .recorder import FFmpegRecorder
from .search import ExpectimaxSolver, MoveAnalysis, SearchResult


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Play 2048.org with Selenium, expectimax, and the Jev API.")
    parser.add_argument("--mode", choices=("hybrid", "jev", "search"), default="hybrid")
    parser.add_argument("--browser", choices=("chrome", "edge", "firefox"), default="edge")
    parser.add_argument("--headless", action="store_true", help="Run the browser without a visible window.")
    parser.add_argument("--resume", action="store_true", help="Resume saved site state instead of clicking New Game.")
    parser.add_argument("--stop-at-2048", action="store_true", help="Stop instead of clicking Keep going after a win.")
    parser.add_argument("--max-moves", type=int, default=10000)
    parser.add_argument("--move-delay", type=float, default=None, help="Pause after each move; recording default is 0.60s.")
    parser.add_argument("--search-ms", type=int, default=250, help="Expectimax time budget per move.")
    parser.add_argument("--search-depth", type=int, default=None, help="Fixed maximum depth; default is adaptive.")
    parser.add_argument("--jev-model", default="jev-latest")
    parser.add_argument("--jev-weight", type=float, default=0.20, help="Maximum Jev probability weight in hybrid mode.")
    parser.add_argument("--api-key", default=None, help="Prefer TYPESAFE_API_KEY instead of putting secrets on the command line.")
    parser.add_argument("--log-dir", type=Path, default=Path("logs"))
    parser.add_argument("--record", action="store_true", help="Record a styled portrait video with FFmpeg.")
    parser.add_argument("--output", type=Path, default=None, help="MP4 path; default: recordings/jev-2048-<time>.mp4")
    parser.add_argument("--capture-width", type=int, default=540, help="On-screen capture width; scaled to 1080.")
    parser.add_argument("--capture-height", type=int, default=960, help="On-screen capture height; scaled to 1920.")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--crf", type=int, default=16, help="H.264 quality: lower is higher quality (default 16).")
    parser.add_argument("--preset", default="slow", help="FFmpeg x264 preset (default: slow).")
    parser.add_argument("--countdown", type=int, default=5, help="Countdown included at the start of a recording.")
    parser.add_argument("--final-hold", type=float, default=3.0, help="Seconds to show final state before finishing video.")
    return parser.parse_args(argv)


def analysis_json(analysis: MoveAnalysis) -> dict[str, Any]:
    return {
        "direction": analysis.direction,
        "value": analysis.value,
        "score_gain": analysis.score_gain,
        "after": analysis.after,
        "features": analysis.features,
    }


def append_log(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")


def display_board(board: Board) -> str:
    width = max(4, max(len(str(value)) for row in board for value in row))
    return "\n".join(" ".join((str(value) if value else ".").rjust(width) for value in row) for row in board)


def run(args: argparse.Namespace) -> int:
    api_key = args.api_key or os.environ.get("TYPESAFE_API_KEY")
    if args.mode != "search" and not api_key:
        raise SystemExit(
            "TYPESAFE_API_KEY is required for hybrid/jev mode. Set it in the environment, "
            "or use --mode search for an offline smoke test."
        )

    args.log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = args.log_dir / f"session-{timestamp}.jsonl"
    video_path = args.output or Path("recordings") / f"jev-2048-{timestamp}.mp4"
    move_delay = args.move_delay if args.move_delay is not None else (0.60 if args.record else 0.10)
    solver = ExpectimaxSolver(time_budget_ms=args.search_ms, max_depth=args.search_depth)
    advisor = JevAdvisor(api_key, model=args.jev_model) if api_key and args.mode != "search" else None
    game: GameBrowser | None = None
    recorder: FFmpegRecorder | None = None
    jev_failures = 0
    history: list[str] = []
    last_direction = ""
    moves_played = 0
    recording_finalized = False

    try:
        if args.record and args.headless:
            raise SystemExit("--record needs a visible browser; remove --headless")
        if args.record and args.browser == "firefox":
            raise SystemExit("Automatic clean-window recording supports Edge or Chrome; use --browser edge")
        game = GameBrowser(
            browser=args.browser,
            headless=args.headless,
            window_width=args.capture_width if args.record else 1100,
            window_height=args.capture_height if args.record else 1000,
            app_mode=args.record,
        )
        game.open()
        if args.record:
            game.set_viewport_size(args.capture_width, args.capture_height)
        if not args.resume:
            game.new_game()
        if args.record:
            game.inject_recording_ui(args.mode)
            initial_board = game.read_board()
            game.update_recording_ui(
                {
                    "score": game.read_score(),
                    "max_tile": max(max(row) for row in initial_board),
                    "move_number": 0,
                    "direction": "",
                    "status": "ENGINE READY",
                    "probabilities": {},
                    "history": [],
                }
            )
            recorder = FFmpegRecorder(
                output=video_path,
                fps=args.fps,
                crf=args.crf,
                preset=args.preset,
            )
            region = recorder.start()
            print(
                f"Recording browser source {region.width}x{region.height} at {args.fps} fps; "
                f"final output will be 1080x1920: {video_path}"
            )
            game.recording_countdown(args.countdown)
        print(f"Playing {game.URL} in {args.mode} mode; log: {log_path}")

        for move_number in range(1, args.max_moves + 1):
            status = game.status()
            if status.over:
                break
            if status.won:
                if args.stop_at_2048:
                    break
                game.continue_after_win()

            board = game.read_board()
            score = game.read_score()
            search: SearchResult = solver.rank_moves(board)
            if not search.analyses:
                break

            jev_decision: JevDecision | None = None
            jev_error: str | None = None
            if advisor is not None and jev_failures < 3:
                try:
                    jev_decision = advisor.advise(board, score, search.analyses)
                    jev_failures = 0
                except Exception as error:  # fail open so a network issue cannot throw the game away
                    jev_failures += 1
                    jev_error = f"{type(error).__name__}: {error}"
                    print(f"warning: Jev call failed ({jev_failures}/3); using expectimax: {jev_error}", file=sys.stderr)

            decision = fuse_decision(search.analyses, jev_decision, mode=args.mode, jev_weight=args.jev_weight)
            moves_played = move_number
            last_direction = decision.direction
            history.append(decision.direction)
            history = history[-6:]
            if args.record:
                if jev_decision is not None:
                    overlay_status = f"{jev_decision.model} • CONFIDENCE-GATED FUSION"
                elif jev_error:
                    overlay_status = "JEV UNAVAILABLE • EXPECTIMAX FALLBACK"
                else:
                    overlay_status = "EXPECTIMAX • SEARCH ONLY"
                game.update_recording_ui(
                    {
                        "score": score,
                        "max_tile": max(max(row) for row in board),
                        "move_number": move_number,
                        "direction": decision.direction,
                        "status": overlay_status,
                        "depth": search.completed_depth,
                        "nodes": search.nodes,
                        "search_ms": search.elapsed_ms,
                        "jev_confidence": None if jev_decision is None else jev_decision.confidence,
                        "probabilities": decision.combined_probabilities,
                        "history": history,
                    }
                )
            print(
                f"#{move_number:04d} score={score:<7d} max={max(max(row) for row in board):<6d} "
                f"move={decision.direction:<5s} depth={search.completed_depth} search={search.elapsed_ms:6.1f}ms "
                f"reason={decision.reason}"
            )
            append_log(
                log_path,
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "move_number": move_number,
                    "score_before": score,
                    "board_before": board,
                    "board_compact": compact_board(board),
                    "search_depth": search.completed_depth,
                    "search_nodes": search.nodes,
                    "search_elapsed_ms": search.elapsed_ms,
                    "analyses": [analysis_json(item) for item in search.analyses],
                    "jev": None
                    if jev_decision is None
                    else {
                        "choice": jev_decision.choice,
                        "probabilities": jev_decision.probabilities,
                        "confidence": jev_decision.confidence,
                        "model": jev_decision.model,
                    },
                    "jev_error": jev_error,
                    "selected": decision.direction,
                    "selection_reason": decision.reason,
                    "combined_probabilities": decision.combined_probabilities,
                },
            )
            new_board = game.send_move(decision.direction, board)
            if args.record:
                game.update_recording_board_stats(
                    game.read_score(), max(max(row) for row in new_board)
                )
            game.pause(move_delay)

        final_board = game.read_board()
        final_score = game.read_score()
        final_status = game.status()
        if args.record:
            game.update_recording_ui(
                {
                    "score": final_score,
                    "max_tile": max(max(row) for row in final_board),
                    "move_number": moves_played,
                    "direction": last_direction,
                    "status": "GAME OVER" if final_status.over else ("2048 ACHIEVED" if final_status.won else "RUN COMPLETE"),
                    "probabilities": {},
                    "history": history,
                }
            )
            game.pause(args.final_hold)
            assert recorder is not None
            finished_video = recorder.stop()
            recording_finalized = True
            print(f"Video finalized: {finished_video}")
        print("\nFinal board:\n" + display_board(final_board))
        print(
            f"score={final_score} max_tile={max(max(row) for row in final_board)} "
            f"won={final_status.won} game_over={final_status.over} log={log_path}"
        )
        return 0
    except KeyboardInterrupt:
        print("\nStopped by user; closing browser.")
        return 130
    finally:
        if recorder is not None and not recording_finalized:
            try:
                finished_video = recorder.stop()
                print(f"Partial video finalized: {finished_video}")
            except Exception as error:
                print(f"warning: could not finalize recording: {error}", file=sys.stderr)
        if advisor is not None:
            advisor.close()
        if game is not None:
            game.close()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
