"""Locate the bundled ffmpeg binary and probe its capabilities.

This module is the only place that knows where ffmpeg lives, mirroring the
resolve-through-one-helper pattern of flux.main._bundled_path(). Every other
module asks locate_ffmpeg() for the path.

The binary ships as an Inno Setup sibling of flux.exe (not inside the PyInstaller
payload), so in a frozen build it sits beside sys.executable. In a source checkout
it is in vendor/. If neither is found, shutil.which() provides a dev-convenience
fallback.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Thread
from typing import Callable

# MP4 video encoders, in preference order: the first one the shipped ffmpeg
# build provides wins. Both land the same "mp4" target in the matrix - which
# encoder actually runs is a build property, not a frontend one, so swapping
# the order (or dropping an entry) changes nothing the UI has to know.
#
# libx264 is preferred while the maintainer's Phase 2.1 is MP4/H.264; the
# report's patent-safe alternative is libvpx-vp9, which the BtbN LGPL build
# carries (that build has no libx264 at all, so it selects vp9 by absence).
MP4_ENCODERS = ("libx264", "libvpx-vp9")

# Container suffixes ffmpeg decodes. These are converter *input* formats -
# the video converter transcodes them, and the image converter pulls a still
# frame out of them - while "mp4" below is the one *output* Phase 2.1 ships.
VIDEO_INPUT_FORMATS = (
    "mp4", "mov", "mkv", "avi", "webm", "m4v",
    "wmv", "flv", "mpg", "mpeg", "mts", "m2ts", "ts", "3gp", "ogv",
)

# Cached probe result: None = not yet probed, frozenset = encoders found.
_ENCODERS_CACHE: frozenset[str] | None = None

# ffmpeg -encoders output format: "<VAS> <name> <description>"
# e.g. " V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC"
_ENCODER_LINE = re.compile(r"^\s*[VAS][.\w]*\s+(\S+)", re.MULTILINE)


def locate_ffmpeg() -> Path | None:
    """Find the ffmpeg binary, or None if unavailable.

    Resolution order:
    1. Frozen build: ffmpeg.exe beside sys.executable (Inno Setup sibling).
    2. Source checkout: vendor/ffmpeg.exe at the repo root.
    3. PATH (dev convenience only; not a supported deployment).
    """
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).parent / name
        if candidate.is_file():
            return candidate

    # src/flux/services/ffmpeg.py -> repo root is parents[3]
    candidate = Path(__file__).resolve().parents[3] / "vendor" / name
    if candidate.is_file():
        return candidate

    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def probe_encoders(ffmpeg: Path | None = None) -> frozenset[str]:
    """Return the encoder names the ffmpeg build provides, cached after first call.

    A single probe gives both the "is video available at all?" boolean and the
    per-codec set. If ffmpeg is missing or the probe fails, returns an empty
    set - which causes the video converter to register no formats.
    """
    global _ENCODERS_CACHE
    if _ENCODERS_CACHE is not None:
        return _ENCODERS_CACHE

    if ffmpeg is None:
        ffmpeg = locate_ffmpeg()
    if ffmpeg is None:
        _ENCODERS_CACHE = frozenset()
        return _ENCODERS_CACHE

    try:
        result = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        encoders = frozenset(
            match.group(1) for match in _ENCODER_LINE.finditer(result.stdout)
        )
    except (OSError, subprocess.SubprocessError):
        encoders = frozenset()

    _ENCODERS_CACHE = encoders
    return encoders


def has_encoder(name: str) -> bool:
    """Whether the ffmpeg build provides a specific encoder."""
    return name in probe_encoders()


def pick_encoder() -> str | None:
    """The MP4 encoder this build will use, or None if it has none.

    One call answers both questions the converter asks - *whether* video
    conversion exists and *how* the command line is built - off the single
    cached -encoders probe, so every capability check in the app agrees.
    """
    encoders = probe_encoders()
    for name in MP4_ENCODERS:
        if name in encoders:
            return name
    return None


def video_available() -> bool:
    """Whether video conversion is possible on this system at all."""
    return pick_encoder() is not None


def reset_probe_cache() -> None:
    """Forget the cached -encoders result so the next probe re-runs it.

    The probe spawns a subprocess, so it is done once and remembered; tests
    that swap the binary out from under it call this instead of reaching
    into the cache variable themselves.
    """
    global _ENCODERS_CACHE
    _ENCODERS_CACHE = None


# --- running one ffmpeg process ---------------------------------------------

# ffmpeg -progress emits "key=value" lines; only out_time is needed, and only
# in its HH:MM:SS.ffffff form (out_time_ms is a misnomer carrying microseconds).
_PROGRESS_OUT_TIME = re.compile(
    r"^out_time=(-?\d+):(\d{2}):(\d{2}(?:\.\d+)?)$", re.MULTILINE
)

# ffmpeg prints "Duration: HH:MM:SS.ss, start: ..." to stderr at -loglevel
# info; -nostats suppresses the separate human-readable stats line so this
# text stays a small, stable log.
_DURATION = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")

# ffmpeg's graceful-abort code (q on stdin, or CTRL_BREAK handled by its
# Windows console handler). A cancellation, not a failure.
_EXIT_CANCELLED = 255

# How long a cancelled ffmpeg gets to honour "q" before the process tree is
# killed outright. Generous: the stdin check runs at most every 100 ms, so
# anything still alive after this has lost its stdin and is wedged.
CANCEL_GRACE_SECONDS = 10.0


def parse_out_time(block: str) -> float | None:
    """Elapsed encode time in seconds from an -progress line, or None.

    Accepts any key=value block; returns None for N/A, missing or
    unparseable values so a malformed tick is skipped rather than fatal.
    """
    match = _PROGRESS_OUT_TIME.search(block)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_duration(stderr_text: str) -> float | None:
    """Total input duration in seconds from ffmpeg's stderr, or None.

    This is the ffprobe replacement: one regex over the log ffmpeg already
    writes, instead of shipping a second 134 MB binary.
    """
    match = _DURATION.search(stderr_text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def error_from_stderr(stderr_lines: list[str], exit_code: int) -> str:
    """The most useful line of ffmpeg's log for a failed run.

    Prefer a line that reads like a diagnosis (the last one wins, since
    ffmpeg reports the fatal problem after the setup chatter), then fall
    back to the last non-empty line, then to the exit code.
    """
    lines = [line.strip() for line in stderr_lines if line.strip()]
    markers = ("error", "invalid", "no such", "not found", "does not",
               "failed", "unable", "unknown", "denied", "unsupported")
    for line in reversed(lines):
        lowered = line.lower()
        if any(marker in lowered for marker in markers):
            return line
    if lines:
        return lines[-1]
    return f"ffmpeg exited with code {exit_code}"


def write_quit_command(proc: subprocess.Popen) -> bool:
    """Write ffmpeg's quit command to stdin. True if it was delivered.

    The primary cancel path: ffmpeg returns AVERROR_EXIT, so the partial
    file is finalised and playable, and the exit code is 0.
    """
    try:
        if proc.stdin is None:
            return False
        proc.stdin.write(b"q")
        proc.stdin.flush()
        return True
    except (OSError, ValueError):
        # Broken pipe: the process is already gone or its stdin is closed.
        return False


def send_interrupt(proc: subprocess.Popen) -> bool:
    """CTRL_BREAK (Windows) / SIGINT (POSIX) as the cancel fallback.

    CTRL_BREAK only reaches a child created with CREATE_NEW_PROCESS_GROUP
    (see run_ffmpeg), and takes the same graceful path as "q" - exit 255
    with a finalised file. Returns False when nothing could be delivered.
    """
    try:
        if sys.platform == "win32":
            import signal

            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            import signal

            proc.send_signal(signal.SIGINT)
        return True
    except (OSError, ValueError, AttributeError):
        return False


def kill_process_tree(proc: subprocess.Popen) -> None:
    """Last resort: end the process *tree*.

    Popen.kill() on Windows is only terminate() - it stops the direct child
    and leaves anything it spawned behind - so taskkill /F /T is what the
    report verified for the final step of the cancel chain.
    """
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
            )
            return
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run_ffmpeg(
    cmd: list[str],
    *,
    progress_cb: Callable[[float, float], None],
    cancel_event: Event,
    completed_before: float = 0.0,
    total: float = 1.0,
    expected_output: Path | None = None,
) -> tuple[bool, str | None]:
    """Run one ffmpeg process with progress and cancellation. (ok, error).

    The shared engine behind every ffmpeg invocation that has to report a
    moving bar and stop on Cancel - MP4 encodes (video_converter) and
    video-to-GIF encodes (image_converter) both build their command line and
    hand it here, so the researched behaviours live in exactly one place:

    * stdout must be drained continuously or ffmpeg blocks on the write and
      never reaches its keyboard-interaction check - cancel would never fire;
      lines are CR-stripped before matching because a wrapper on Windows may
      emit CRLF where ffmpeg itself writes LF.
    * progress comes from -progress pipe:1 out_time lines as a ratio against
      the Duration parsed from stderr - completed_before + elapsed/duration,
      so a multi-file batch advances monotonically across file boundaries.
    * cancellation runs on three rungs: "q" on stdin (exit 0, primary),
      CTRL_BREAK (exit 255, fallback when stdin is gone), and a process-tree
      kill after CANCEL_GRACE_SECONDS. Exit 0 on the cancel path or 255 from
      ffmpeg both mean "cancelled", never "error" - surfacing 255 as a
      failure shows users a bogus error on Cancel.

    A cancelled run returns (True, None): the caller keys off its own
    cancel_event, which is what distinguishes the two success shapes.
    """
    creationflags = 0
    if sys.platform == "win32":
        # Required for CTRL_BREAK_EVENT delivery (the fallback rung).
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
    except OSError as exc:
        return False, f"Failed to start ffmpeg: {exc}"

    # Shared state between the three helper threads and the wait loop.
    # duration is filled in by the stderr reader as soon as ffmpeg prints
    # the input header; cancelled_at marks when the user asked to stop.
    state: dict[str, object] = {"duration": None, "cancelled_at": None, "done": False}
    stderr_lines: list[str] = []

    def report_progress(elapsed: float | None) -> None:
        duration = state["duration"]
        if elapsed is None or not duration or duration <= 0:
            return
        fraction = min(max(elapsed / float(duration), 0.0), 1.0)
        try:
            progress_cb(completed_before + fraction, total)
        except Exception:
            # A UI callback must never be able to kill a reader thread:
            # a dead stdout reader is exactly the undrained-pipe stall
            # that makes cancel stop working.
            pass

    def read_stdout() -> None:
        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("out_time="):
                    report_progress(parse_out_time(line))
        except (OSError, ValueError):
            pass

    def read_stderr() -> None:
        try:
            assert proc.stderr is not None
            for raw_line in proc.stderr:
                text = raw_line.decode("utf-8", errors="replace")
                stderr_lines.append(text)
                if state["duration"] is None:
                    duration = parse_duration(text)
                    if duration is not None:
                        state["duration"] = duration
        except (OSError, ValueError):
            pass

    stdout_thread = Thread(target=read_stdout, daemon=True)
    stderr_thread = Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    def watch_cancel() -> None:
        while not state["done"]:
            if not cancel_event.wait(0.1):
                continue
            state["cancelled_at"] = time.monotonic()
            if not write_quit_command(proc):
                send_interrupt(proc)
            break

    cancel_thread = Thread(target=watch_cancel, daemon=True)
    cancel_thread.start()

    # Wait with a deadline so a cancel that ffmpeg ignores still ends in
    # a kill instead of a hung job; normal encodes wait indefinitely.
    exit_code: int | None = None
    while exit_code is None:
        try:
            exit_code = proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            cancelled_at = state["cancelled_at"]
            if cancelled_at is not None and (
                time.monotonic() - float(cancelled_at) > CANCEL_GRACE_SECONDS
            ):
                kill_process_tree(proc)
                try:
                    exit_code = proc.wait(timeout=CANCEL_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    # Nothing left to do but report the failure.
                    exit_code = -1

    state["done"] = True
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    try:
        if proc.stdin is not None:
            proc.stdin.close()
    except (OSError, ValueError):
        pass

    if state["cancelled_at"] is not None or exit_code == _EXIT_CANCELLED:
        # Cancelled: either the graceful "q" (0) or CTRL_BREAK (255)
        # path, both of which finalise the file. The caller keys off its
        # own cancel_event and cleans the partial output up.
        return True, None

    if exit_code != 0:
        return False, error_from_stderr(stderr_lines, int(exit_code))

    if expected_output is not None and not expected_output.is_file():
        return False, "ffmpeg reported success but produced no output file."

    return True, None
