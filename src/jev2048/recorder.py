from __future__ import annotations

import ctypes
import shutil
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CaptureRegion:
    x: int
    y: int
    width: int
    height: int
    title: str


def find_window_client_region(title_fragment: str, timeout: float = 10.0) -> CaptureRegion:
    """Find the largest visible Windows client area whose title contains a fragment."""
    if not hasattr(ctypes, "windll"):
        raise RuntimeError("Automatic FFmpeg window capture currently requires Windows")

    user32 = ctypes.windll.user32
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches: list[tuple[int, int, str, int, int, int, int]] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
            if title_fragment.casefold() not in title.casefold():
                return True

            rect = wintypes.RECT()
            if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
                return True
            origin = wintypes.POINT(0, 0)
            if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
                return True
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width > 0 and height > 0:
                matches.append((width * height, hwnd, title, origin.x, origin.y, width, height))
            return True

        user32.EnumWindows(callback, 0)
        if matches:
            _, _, title, x, y, width, height = max(matches, key=lambda item: item[0])
            return CaptureRegion(x=x, y=y, width=width, height=height, title=title)
        time.sleep(0.2)
    raise RuntimeError(f"Could not find a visible browser window containing title {title_fragment!r}")


class FFmpegRecorder:
    def __init__(
        self,
        output: Path,
        fps: int = 60,
        crf: int = 16,
        preset: str = "slow",
        output_width: int = 1080,
        output_height: int = 1920,
    ) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg was not found on PATH. Install FFmpeg and reopen the terminal.")
        self.ffmpeg = ffmpeg
        self.output = output.resolve()
        self.fps = max(1, fps)
        self.crf = min(51, max(0, crf))
        self.preset = preset
        self.output_width = output_width
        self.output_height = output_height
        self.process: subprocess.Popen[bytes] | None = None
        self.log_handle = None
        self.region: CaptureRegion | None = None

    def start(self, title_fragment: str = "Jev 2048") -> CaptureRegion:
        if self.process is not None:
            raise RuntimeError("Recorder is already running")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.region = find_window_client_region(title_fragment)
        log_path = self.output.with_suffix(".ffmpeg.log")
        self.log_handle = log_path.open("wb")
        # Chromium's app title bar is part of the captured window. Keep the
        # bottom-aligned 9:16 content area, which removes that bar without
        # relying on DPI-dependent pixel offsets, then scale to the master size.
        video_filter = (
            "crop=iw:iw*16/9:0:ih-iw*16/9,"
            f"scale={self.output_width}:{self.output_height}:flags=lanczos,"
            "format=yuv420p"
        )
        command = [
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "gdigrab",
            "-framerate",
            str(self.fps),
            "-draw_mouse",
            "0",
            "-i",
            f"title={self.region.title}",
            "-an",
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-preset",
            self.preset,
            "-crf",
            str(self.crf),
            "-profile:v",
            "high",
            "-level",
            "4.2",
            "-r",
            str(self.fps),
            "-movflags",
            "+faststart",
            str(self.output),
        ]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        time.sleep(0.8)
        if self.process.poll() is not None:
            self._close_log()
            raise RuntimeError(f"FFmpeg exited during startup. See {log_path}")
        return self.region

    def stop(self, timeout: float = 30.0) -> Path:
        if self.process is None:
            return self.output
        process = self.process
        if process.poll() is None and process.stdin is not None:
            try:
                process.stdin.write(b"q\n")
                process.stdin.flush()
                process.wait(timeout=timeout)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        return_code = process.returncode
        self.process = None
        self._close_log()
        if return_code not in (0, 255):
            raise RuntimeError(f"FFmpeg exited with code {return_code}; see {self.output.with_suffix('.ffmpeg.log')}")
        if not self.output.exists() or self.output.stat().st_size == 0:
            raise RuntimeError("FFmpeg did not produce a video file")
        return self.output

    def _close_log(self) -> None:
        if self.log_handle is not None:
            self.log_handle.close()
            self.log_handle = None
