# Jev 2048 Selenium Player

This Python application opens [2048.org](https://www.2048.org/) with Selenium and plays automatically. The default `hybrid` mode combines a time-bounded expectimax search with a real TypeSafe Jev `Choice` decision on every move.

It also includes an integrated Selenium + FFmpeg portrait recorder. See [RECORDING.md](RECORDING.md), or run `python run.py --record` to create a high-quality 1080×1920 YouTube Short MP4 automatically.

## Why the hybrid design

Jev 1.13 is a text/JSON decision model, not a vision or game-tree model. The application therefore:

1. Reads the exact 4x4 board from the site's saved game state (with a DOM fallback at game-over).
2. Reproduces the site's merge and scoring rules locally and removes illegal moves.
3. Uses iterative-deepening expectimax over the site's exact 90% `2` / 10% `4` random-spawn distribution.
4. Sends Jev a small structured state and one bounded `Choice` containing only legal moves and their search evidence.
5. Fuses Jev's full probability distribution with the search distribution. Jev's documented confidence controls its effective weight, so an uncertain API answer cannot throw away a clearly superior search move.

This is usually stronger and safer than asking a text classifier to infer a move directly from 16 numbers. `--mode jev` is included when you want Jev to have final authority for experiments.

## Setup (Windows PowerShell)

Python 3.10+ and Chrome, Edge, or Firefox are required. Selenium Manager downloads or locates the matching driver automatically.

```powershell
cd C:\path\to\jev-2048-selenium
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:TYPESAFE_API_KEY = "your-TypeSafe-key"
python run.py
```

Create a key in the [TypeSafe console](https://console.typesafe.ai/). Keep it in the environment; do not commit it or put it in `.env`.

Useful examples:

```powershell
# Default: visible Edge, new game, hybrid search + Jev
python run.py

# Run without a visible window
python run.py --headless

# Do not click New Game after opening the site
python run.py --resume

# Give Jev final authority over the legal move list
python run.py --mode jev

# Offline Selenium/search smoke test (no API key)
python run.py --mode search --headless --max-moves 20

# Use Edge and spend up to 500 ms searching per move
python run.py --browser edge --search-ms 500

# Styled 1080x1920, 60 fps YouTube Short recording
python run.py --record
```

Run tests:

```powershell
python -m pytest
```

## Main options

- `--mode hybrid|jev|search`: confidence-gated fusion (default), strict Jev, or offline expectimax.
- `--jev-weight 0.20`: maximum Jev weight in hybrid mode. Actual weight is this value multiplied by Jev confidence.
- `--search-ms 250`: per-move expectimax budget. Iterative deepening keeps the last fully completed depth.
- `--search-depth N`: override adaptive maximum depth.
- `--stop-at-2048`: otherwise the player clicks **Keep going** and continues.
- `--max-moves N`: safety limit; default 10,000.
- `--move-delay SECONDS`: delay after each move; defaults to 0.10 normally and 0.60 while recording.
- `--record`: inject the portrait dashboard and record/finalize an MP4 with FFmpeg.
- `--output PATH`: choose the output MP4 path.
- `--fps`, `--crf`, `--preset`: control recording quality (defaults: 60, 16, slow).

Every move is recorded as JSON Lines under `logs/`, including the board, all search candidates, Jev choice/probabilities/confidence/model version, final fused probabilities, and any API failure. Network/API errors fail open to expectimax; after three consecutive failures the run stops calling Jev to avoid repeated delays.

## Verified rules and API contract

The implementation was checked against the exact JavaScript served by 2048.org and the original 2048 source. A successful directional move compresses tiles, merges equal pairs once, adds merged values to score, and creates one random tile. A `2` is created with probability 0.9 and a `4` with probability 0.1. Reaching 2048 pauses the game until the player chooses to continue; no available cell and no adjacent equal pair means game over.

Jev integration uses the official `typesafe-sdk`, `TypeSafeClient.system_one`, `jev-latest`, and one `Choice` question. Choice criteria are a map, and the response supplies `choice`, per-option `probabilities`, and `confidence`. The SDK handles documented 429/529 retries with backoff.

Sources:

- [TypeSafe API reference](https://docs.typesafe.ai/api)
- [Official TypeSafe Python SDK](https://github.com/typesafe-ai/typesafe-sdk-python)
- [TypeSafe Choice documentation](https://docs.typesafe.ai/primitives/choice)
- [TypeSafe confidence documentation](https://docs.typesafe.ai/confidence)
- [TypeSafe models and limits](https://docs.typesafe.ai/models)
- [Original 2048 source](https://github.com/gabrielecirulli/2048/blob/master/js/game_manager.js)
- [Target site](https://www.2048.org/)

## Performance notes

2048 contains random spawns, so no run can guarantee a particular tile or score. For stronger play, increase `--search-ms` to 500-1000. The default is intentionally responsive enough for a live browser. Because `jev-latest` is a moving alias, logs record the resolved model version; pin a documented model such as `jev-1.13.0` with `--jev-model` when benchmarking reproducibility.
