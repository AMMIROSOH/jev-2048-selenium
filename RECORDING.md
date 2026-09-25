# Record a YouTube Short with Selenium + FFmpeg

The recorder is integrated into the application. It opens Edge as a clean app window, injects the live Jev/expectimax dashboard, records only the browser client area, and finalizes a **1080 × 1920, 60 fps H.264 MP4** when the game finishes or you press `Ctrl+C`.

No OBS setup is required.

## One-command recording

From this project directory in PowerShell:

```powershell
$env:TYPESAFE_API_KEY = "your-TypeSafe-key"
.\.venv\Scripts\python.exe run.py --record
```

Or use the included launcher:

```powershell
.\record.ps1
```

The finished video is saved under `recordings\jev-2048-<timestamp>.mp4`. The matching `.ffmpeg.log` is useful if FFmpeg reports a capture or encoding problem.

For a slower, easier-to-follow Short that ends when 2048 is reached:

```powershell
.\.venv\Scripts\python.exe run.py --record --move-delay 0.75 --stop-at-2048
```

To test the recording layout without spending Jev API calls:

```powershell
.\.venv\Scripts\python.exe run.py --record --mode search --max-moves 30
```

## What appears in the video

- The real live 2048.org board, without ads, navigation, or browser address bar.
- Score, largest tile, and move number.
- The selected direction with an animated arrow.
- Fused probability bars for UP, RIGHT, DOWN, and LEFT.
- Jev model/confidence or expectimax fallback status.
- Search depth, visited nodes, and search duration.
- A six-move visual history.
- A five-second recorded countdown and a three-second final hold.

The portrait layout leaves clear space above the title for phone camera islands
and below the footer for Shorts playback controls. The score is refreshed from
the live game state after each move.

## Video quality

The default output is:

- Resolution: `1080x1920` (9:16 portrait)
- Frame rate: `60 fps`
- Codec: H.264 High Profile (`libx264`)
- Quality: `CRF 16`
- Encoder preset: `slow`
- Pixel format: `yuv420p` for YouTube compatibility
- Lanczos scaling and `faststart` MP4 metadata

The default on-screen capture window is `540x960`, an exact half-resolution portrait window that fits on a normal 1080p monitor. FFmpeg scales it exactly 2× to the final 1080×1920 frame. On a 4K or portrait monitor, capture natively:

```powershell
.\.venv\Scripts\python.exe run.py --record --capture-width 1080 --capture-height 1920
```

You can choose a destination and tune encoding:

```powershell
.\.venv\Scripts\python.exe run.py --record `
  --output "recordings\my-youtube-short.mp4" `
  --fps 60 `
  --crf 14 `
  --preset slow `
  --countdown 8 `
  --final-hold 4
```

Lower CRF means higher quality and a larger file. Values from 14–18 are appropriate for a high-quality upload master.

## FFmpeg requirement

Confirm that FFmpeg is available before recording:

```powershell
ffmpeg -version
```

The application stops with a clear error if `ffmpeg.exe` is not on `PATH`. This computer already has a compatible FFmpeg build with `gdigrab` and `libx264`.

## Finishing early

Press `Ctrl+C` in the terminal. The application sends FFmpeg its normal `q` command and waits for the MP4 index and `faststart` metadata to be finalized before closing the browser. Do not kill the terminal process if you want the partial recording to remain playable.
