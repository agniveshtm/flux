"""Phase 2.1 video conversion: parsing, capability gating, and the encode loop.

The encode loop is exercised end-to-end against a stand-in ffmpeg (a small
Python script behind a launcher) rather than a real binary, so the suite runs
identically on machines without one - which is the whole capability story:
no ffmpeg means no video formats, and every test here still has to hold. The
fake speaks the two surfaces the converter depends on:

* ``-encoders`` for the capability probe (which codec the build has decides
  both availability and the command line);
* ``-progress pipe:1`` on stdout plus ``Duration:`` on stderr for the bar,
  and stdin ``q`` for cancel.

It writes a large filler line per tick, so a stdout reader that stopped
draining would stall the test instead of hanging silently, and it self-exits
after 15 seconds no matter what, so a broken cancel chain fails rather than
freezes the suite.
"""

from __future__ import annotations

import sys
import tempfile as _tempfile
import time
from pathlib import Path
from threading import Event

import pytest
from PIL import Image

import flux.services.ffmpeg as ffmpeg_module
import flux.services.image_converter as image_converter_module
import flux.services.video_converter as video_converter
from flux.converter import UnsupportedFormatError
from flux.services.ffmpeg import (
    CANCEL_GRACE_SECONDS,
    VIDEO_INPUT_FORMATS,
    error_from_stderr,
    parse_duration,
    parse_out_time,
    video_available,
)
from flux.services.image_converter import PillowImageConverter
from flux.services.video_converter import (
    FFmpegVideoConverter,
    vp9_crf,
    video_encode_args,
    x264_crf,
)

# The fake's encoders listing. Both real preference-table entries appear, in
# the format ffmpeg -encoders prints (the regex in ffmpeg.py keys off it).
_ENCODERS_BOTH = (
    "Encoders:\n"
    " V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC\n"
    " V....D libvpx-vp9           Google VP9\n"
    " A....D aac                  AAC (Advanced Audio Coding)\n"
)
_ENCODERS_VP9_ONLY = (
    "Encoders:\n"
    " V....D libvpx-vp9           Google VP9\n"
    " A....D aac                  AAC (Advanced Audio Coding)\n"
)
_ENCODERS_NEITHER = "Encoders:\n A....D aac   AAC (Advanced Audio Coding)\n"

_FAKE_FFMPEG = '''\
"""Stand-in ffmpeg for tests: same CLI surface, no codecs. See the module
docstring of tests/test_video_converter.py for the mode table."""
import os
import sys
import threading
import time

args = sys.argv[1:]
mode = os.environ.get("FAKE_FFMPEG_MODE", "normal")

argv_file = os.environ.get("FAKE_ARGV_FILE")
if argv_file:
    with open(argv_file, "w", encoding="utf-8") as fh:
        fh.write("\\n".join(args))

if "-encoders" in args:
    sys.stdout.write(os.environ.get("FAKE_ENCODERS", ""))
    sys.exit(0)

output = args[-1]

if "-frames:v" in args:
    # The image converter's frame-extraction call.
    if mode == "frame_fail":
        print("no such file or directory", file=sys.stderr)
        print(output + ": Invalid data found when processing input", file=sys.stderr)
        sys.exit(1)
    with open(os.environ["FAKE_FRAME_PNG"], "rb") as src, open(output, "wb") as dst:
        dst.write(src.read())
    sys.exit(0)

# The encode call: announce the duration exactly as -loglevel info does, so
# the converter's ffprobe replacement has something to parse.
print("Duration: 00:00:02.00, start: 0.000000, bitrate: 1000 kb/s",
      file=sys.stderr, flush=True)

# A video -> GIF encode: the caller hands a real animated template, so the
# output is a file the test can open and check frame count on. It still
# reports one in-file tick first, so the progress mapping gets exercised.
# The pause stands in for a real encode's startup time - without it the
# tick can reach the pump before the stderr reader has seen Duration, and
# a tick against an unknown duration is deliberately dropped.
if output.endswith(".gif") and os.environ.get("FAKE_GIF_TEMPLATE"):
    time.sleep(0.3)
    sys.stdout.write("out_time=00:00:01.00\\n")
    sys.stdout.flush()
    with open(os.environ["FAKE_GIF_TEMPLATE"], "rb") as src, open(output, "wb") as dst:
        dst.write(src.read())
    sys.exit(0)

if mode == "fail":
    print("[mov,mp4 @ 0x007f] moov atom not found", file=sys.stderr, flush=True)
    print(output + ": Invalid data found when processing input",
          file=sys.stderr, flush=True)
    sys.exit(1)

started = time.time()
saw_quit = threading.Event()


def watch_stdin():
    if sys.stdin.read(1):
        saw_quit.set()


threading.Thread(target=watch_stdin, daemon=True).start()

deadline = started + 15.0
while time.time() < deadline:
    elapsed = min(time.time() - started, 2.0)
    # Filler the size of a pipe buffer on every tick: a reader that stopped
    # draining blocks here, and the loop's deadline turns that into a failed
    # test rather than a hung suite.
    sys.stdout.write("filler=" + "x" * 65536 + "\\n")
    sys.stdout.write("out_time=00:00:%05.2f\\n" % elapsed)
    sys.stdout.flush()
    if mode == "ignore_q":
        if elapsed >= 1.0:
            sys.exit(255)
    elif saw_quit.is_set() or elapsed >= 1.0:
        with open(output, "wb") as fh:
            fh.write(b"ftypisom fake-mp4 payload")
        sys.exit(0)
    time.sleep(0.05)
sys.exit(2)
'''


@pytest.fixture(autouse=True)
def _fresh_probe_cache():
    """No test may inherit -encoders state cached by another one."""
    ffmpeg_module.reset_probe_cache()
    yield
    ffmpeg_module.reset_probe_cache()


@pytest.fixture
def fake_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the converter at a fake binary and force video capability on."""
    script = tmp_path / "fake_ffmpeg.py"
    script.write_text(_FAKE_FFMPEG, encoding="utf-8")

    if sys.platform == "win32":
        # Popen runs .cmd through cmd.exe, which forwards %* verbatim.
        launcher = tmp_path / "ffmpeg.cmd"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher = tmp_path / "ffmpeg"
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)

    monkeypatch.setattr(video_converter, "locate_ffmpeg", lambda: launcher)
    monkeypatch.setattr(video_converter, "video_available", lambda: True)
    monkeypatch.setattr(video_converter, "pick_encoder", lambda: "libx264")
    return launcher


def _make_clip(directory: Path, name: str = "clip.mp4") -> Path:
    clip = directory / name
    clip.write_bytes(b"\x00\x00\x00\x18ftypisom fake input, the fake never reads it")
    return clip


def _convert(
    converter: FFmpegVideoConverter,
    input_paths: list[str],
    output_dir: Path,
    progress_cb=None,
    cancel_event: Event | None = None,
    target_format: str = "mp4",
):
    return converter.convert(
        input_paths=input_paths,
        output_dir=str(output_dir),
        target_format=target_format,
        options={},
        progress_cb=progress_cb or (lambda current, total: None),
        cancel_event=cancel_event or Event(),
    )


# --- progress parsing -------------------------------------------------------


def test_parse_out_time_reads_hh_mm_ss_only() -> None:
    # out_time_us and out_time_ms both carry microseconds - parsing the
    # ms-looking one would report progress 1000x too slow, which is why only
    # the plain out_time line is trusted.
    assert parse_out_time("out_time=00:00:01.500000\n") == pytest.approx(1.5)
    assert parse_out_time("frame=10\nout_time=00:01:03.250000\n") == pytest.approx(63.25)
    assert parse_out_time("out_time=01:00:00.000000") == pytest.approx(3600.0)
    # Sign lives on the hours field, so a rewound clock still goes negative.
    assert parse_out_time("out_time=-01:02:03.500000") == pytest.approx(-3476.5)

    assert parse_out_time("out_time=N/A\n") is None
    assert parse_out_time("out_time_us=1500000\nout_time_ms=1500000\n") is None
    assert parse_out_time("progress=end\n") is None


def test_parse_duration_reads_the_stderr_header() -> None:
    assert parse_duration(
        "Duration: 00:00:07.00, start: 0.000000, bitrate: 33 kb/s"
    ) == pytest.approx(7.0)
    assert parse_duration("Duration: 01:02:03.50, start: 0.000000, ...") == pytest.approx(
        3723.5
    )
    assert parse_duration("Input #0, mov,mp4, from 'clip.mp4':") is None
    assert parse_duration("") is None


# --- quality mappings -------------------------------------------------------


def test_x264_crf_maps_the_slider_window() -> None:
    assert x264_crf(None) == 23
    assert x264_crf(0) == 28
    assert x264_crf(50) == 23
    assert x264_crf(100) == 18
    # Out-of-range and nonsense values land on the default rather than
    # producing a CRF ffmpeg would reject.
    assert x264_crf(-20) == 28
    assert x264_crf(500) == 18
    assert x264_crf("fast") == 23


def test_vp9_crf_maps_the_slider_window() -> None:
    # VP9's CRF scale is 0-63, not x264's 0-51: the same slider has to mean
    # "quality", so each encoder gets its own window around its own default.
    assert vp9_crf(None) == 32
    assert vp9_crf(0) == 40
    assert vp9_crf(50) == 25
    assert vp9_crf(100) == 10
    # Nonsense lands mid-slider (the neutral 50), same as x264's default path.
    assert vp9_crf("fast") == 25


def test_video_encode_args_is_one_table_per_encoder() -> None:
    x264 = video_encode_args("libx264", None)
    assert "-c:v" in x264 and x264[x264.index("-c:v") + 1] == "libx264"
    assert x264[x264.index("-crf") + 1] == "23"
    assert "-preset" in x264
    assert x264[x264.index("-pix_fmt") + 1] == "yuv420p"

    # -b:v 0 is how libvpx enters CRF mode; quality 100 must reach each
    # encoder's own best-quality floor, not a shared number.
    assert video_encode_args("libx264", 100)[video_encode_args("libx264", 100).index("-crf") + 1] == "18"
    vp9 = video_encode_args("libvpx-vp9", None)
    assert vp9[vp9.index("-c:v") + 1] == "libvpx-vp9"
    assert vp9[vp9.index("-crf") + 1] == "32"
    assert vp9[vp9.index("-b:v") + 1] == "0"

    with pytest.raises(UnsupportedFormatError):
        video_encode_args("mpeg4", None)


def test_error_from_stderr_prefers_the_diagnosis() -> None:
    lines = [
        "frame=  10 fps=0.0 q=0.0 size=       0kB time=00:00:01",
        "something failed here",
        "trailer written",
    ]
    assert error_from_stderr(lines, 1) == "something failed here"
    assert error_from_stderr(["only chatter", ""], 7) == "only chatter"
    assert error_from_stderr([], 1) == "ffmpeg exited with code 1"


# --- capability gating ------------------------------------------------------


def test_converter_declares_formats_exactly_when_ffmpeg_can_encode() -> None:
    # The whole no-ffmpeg story in one assertion: without a capable build the
    # converter registers nothing, so the registry maps no formats and the UI
    # stays exactly as image-only as it was before Phase 2.1.
    converter = FFmpegVideoConverter()
    if video_available():
        assert converter.supported_output_formats == ["mp4"]
        # GIF rides along as an input - gif -> mp4 is a video conversion -
        # but never as an output: the image converter writes GIF.
        assert set(converter.supported_input_formats) == set(VIDEO_INPUT_FORMATS) | {"gif"}
    else:
        assert converter.supported_output_formats == []
        assert converter.supported_input_formats == []


def test_convert_refuses_targets_it_cannot_write(
    fake_ffmpeg: Path, tmp_path: Path
) -> None:
    # Rejected before a single file is touched: MP4 is the only output Phase
    # 2.1 ships, and a target outside supported_output_formats must not reach
    # the encode loop (where it would fail much later and much less clearly).
    converter = FFmpegVideoConverter()
    with pytest.raises(UnsupportedFormatError):
        _convert(converter, ["clip.mp4"], tmp_path, target_format="webm")


def test_pick_encoder_follows_the_preference_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "fake_ffmpeg.py"
    script.write_text(_FAKE_FFMPEG, encoding="utf-8")
    if sys.platform == "win32":
        launcher = tmp_path / "ffmpeg.cmd"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8"
        )
    else:
        launcher = tmp_path / "ffmpeg"
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8"
        )
        launcher.chmod(0o755)

    monkeypatch.setattr(ffmpeg_module, "locate_ffmpeg", lambda: launcher)

    # Both encoders present: the table's first entry wins, which is the
    # current libx264-first contract of Phase 2.1.
    monkeypatch.setenv("FAKE_ENCODERS", _ENCODERS_BOTH)
    ffmpeg_module.reset_probe_cache()
    assert ffmpeg_module.pick_encoder() == "libx264"
    assert ffmpeg_module.has_encoder("libx264")
    assert ffmpeg_module.video_available()

    # The LGPL build carries no libx264 at all: absence, not a fallback flag,
    # is what selects VP9 - and video still exists.
    monkeypatch.setenv("FAKE_ENCODERS", _ENCODERS_VP9_ONLY)
    ffmpeg_module.reset_probe_cache()
    assert ffmpeg_module.pick_encoder() == "libvpx-vp9"
    assert ffmpeg_module.video_available()

    # No MP4 encoder at all: unavailable, and every capability check agrees.
    # The probe still lists audio encoders - it reports the whole build - but
    # none of them is in the MP4 preference table.
    monkeypatch.setenv("FAKE_ENCODERS", _ENCODERS_NEITHER)
    ffmpeg_module.reset_probe_cache()
    assert ffmpeg_module.pick_encoder() is None
    assert not ffmpeg_module.video_available()
    assert not (set(ffmpeg_module.MP4_ENCODERS) & ffmpeg_module.probe_encoders())


# --- the encode loop --------------------------------------------------------


def test_convert_writes_an_output_and_reports_progress(
    fake_ffmpeg: Path, tmp_path: Path
) -> None:
    clip = _make_clip(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()
    seen: list[tuple[float, int]] = []

    result = _convert(
        FFmpegVideoConverter(),
        [str(clip)],
        outdir,
        progress_cb=lambda current, total: seen.append((current, total)),
    )

    assert not result.errors, result.errors
    assert result.outputs == [(str(clip), str(outdir / "clip.mp4"))]
    assert (outdir / "clip.mp4").is_file()

    # Ticks inside the file are fractional, the file boundary is integral,
    # and the bar never runs backwards.
    currents = [current for current, _ in seen]
    assert currents, "no progress was reported"
    assert all(
        later >= earlier for earlier, later in zip(currents, currents[1:])
    ), f"progress went backwards: {currents}"
    assert any(isinstance(current, float) for current in currents), (
        f"no in-file fraction was reported: {currents}"
    )
    assert seen[-1] == (1, 1)


def test_batch_advances_monotonically_across_files(
    fake_ffmpeg: Path, tmp_path: Path
) -> None:
    alpha = _make_clip(tmp_path, "alpha.mp4")
    beta = _make_clip(tmp_path, "beta.mp4")
    outdir = tmp_path / "out"
    outdir.mkdir()
    seen: list[tuple[float, int]] = []

    result = _convert(
        FFmpegVideoConverter(),
        [str(alpha), str(beta)],
        outdir,
        progress_cb=lambda current, total: seen.append((current, total)),
    )

    assert not result.errors, result.errors
    assert [Path(output).name for output in result.output_paths] == [
        "alpha.mp4",
        "beta.mp4",
    ]
    currents = [current for current, _ in seen]
    assert all(
        later >= earlier for earlier, later in zip(currents, currents[1:])
    ), f"progress went backwards: {currents}"
    assert all(total == 2 for _, total in seen)
    # The second file starts from 1.0 and the batch ends on (2, 2).
    assert currents[-1] == 2


def test_rerun_deduplicates_the_output_name(
    fake_ffmpeg: Path, tmp_path: Path
) -> None:
    clip = _make_clip(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()
    converter = FFmpegVideoConverter()

    first = _convert(converter, [str(clip)], outdir)
    second = _convert(converter, [str(clip)], outdir)

    assert not first.errors and not second.errors
    assert (outdir / "clip.mp4").is_file()
    assert (outdir / "clip-1.mp4").is_file()


def test_cancel_removes_the_partial_output(
    fake_ffmpeg: Path, tmp_path: Path
) -> None:
    clip = _make_clip(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()
    cancel_event = Event()

    def cancel_on_first_tick(current, total) -> None:
        # Ticks inside the file are floats; the (index, total) boundary
        # calls are ints. The first float means the encode really started.
        if isinstance(current, float):
            cancel_event.set()

    result = _convert(
        FFmpegVideoConverter(),
        [str(clip)],
        outdir,
        progress_cb=cancel_on_first_tick,
        cancel_event=cancel_event,
    )

    assert result.errors == ["Conversion cancelled"]
    assert not result.outputs
    # "q" finalises the file on the real ffmpeg, and the converter removes it
    # anyway: a cancelled job must not leave something that looks finished.
    assert not (outdir / "clip.mp4").exists()


def test_exit_255_is_reported_as_a_cancel_not_a_failure(
    fake_ffmpeg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The CTRL_BREAK rung: the fake ignores "q" and leaves with ffmpeg's
    # graceful-abort code. Surfacing that as an error is exactly the bug the
    # report recorded - users pressing Cancel must not see a failure.
    monkeypatch.setenv("FAKE_FFMPEG_MODE", "ignore_q")
    clip = _make_clip(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()
    cancel_event = Event()

    def cancel_on_first_tick(current, total) -> None:
        if isinstance(current, float):
            cancel_event.set()

    started = time.monotonic()
    result = _convert(
        FFmpegVideoConverter(),
        [str(clip)],
        outdir,
        progress_cb=cancel_on_first_tick,
        cancel_event=cancel_event,
    )
    elapsed = time.monotonic() - started

    assert result.errors == ["Conversion cancelled"], result.errors
    assert all("code" not in error for error in result.errors), (
        f"exit 255 leaked into the message: {result.errors}"
    )
    # It exited by itself, so the kill rung of the chain never fired.
    assert elapsed < CANCEL_GRACE_SECONDS


def test_failed_encode_surfaces_the_diagnostic_line(
    fake_ffmpeg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_FFMPEG_MODE", "fail")
    clip = _make_clip(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()

    result = _convert(FFmpegVideoConverter(), [str(clip)], outdir)

    assert not result.outputs
    assert len(result.errors) == 1, result.errors
    assert result.errors[0].startswith("clip.mp4:")
    # The diagnosis, not the stats chatter before it.
    assert "Invalid data found" in result.errors[0]
    assert not (outdir / "clip.mp4").exists()


def test_command_shape_matches_the_reported_flags(
    fake_ffmpeg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv_file = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_ARGV_FILE", str(argv_file))
    clip = _make_clip(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()

    result = _convert(FFmpegVideoConverter(), [str(clip)], outdir)

    assert not result.errors, result.errors
    argv = argv_file.read_text(encoding="utf-8").splitlines()

    for flag in (
        "-hide_banner", "-nostats", "-loglevel", "info", "-stats_period", "0.25",
        "-progress", "pipe:1", "-y", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
    ):
        assert flag in argv, f"missing {flag} in {argv}"

    assert argv[argv.index("-i") + 1] == str(clip)
    assert argv[-1] == str(outdir / "clip.mp4")
    assert argv[argv.index("-c:v") + 1] in ("libx264", "libvpx-vp9")
    assert "-crf" in argv
    assert argv[argv.index("-pix_fmt") + 1] == "yuv420p"


# --- frame extraction (video -> still) --------------------------------------


@pytest.fixture
def fake_frame(tmp_path: Path) -> Path:
    """A real PNG the fake hands to the image converter as 'the first frame'."""
    frame = tmp_path / "frame.png"
    Image.new("RGB", (32, 24), (200, 30, 60)).save(frame)
    return frame


@pytest.fixture
def fake_gif_template(tmp_path: Path) -> Path:
    """A real 2-frame GIF the fake writes in place of its encode output."""
    template = tmp_path / "template.gif"
    frames = [Image.new("RGB", (16, 16), color) for color in ("red", "blue")]
    frames[0].save(
        template,
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    return template


def test_video_input_converts_through_frame_extraction(
    fake_ffmpeg: Path,
    fake_frame: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The frame travels the ordinary Pillow pipeline afterwards, so the whole
    # quality/option machinery applies to a clip's first frame unchanged.
    monkeypatch.setenv("FAKE_FRAME_PNG", str(fake_frame))
    monkeypatch.setattr(image_converter_module, "locate_ffmpeg", lambda: fake_ffmpeg)
    monkeypatch.setattr(image_converter_module, "video_available", lambda: True)

    created: list[Path] = []
    real_named_temporary_file = _tempfile.NamedTemporaryFile

    def recorder(*args, **kwargs):
        handle = real_named_temporary_file(*args, **kwargs)
        created.append(Path(handle.name))
        return handle

    monkeypatch.setattr(_tempfile, "NamedTemporaryFile", recorder)

    clip = _make_clip(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()

    result = PillowImageConverter().convert(
        input_paths=[str(clip)],
        output_dir=str(outdir),
        target_format="jpg",
        options={"quality": 70},
        progress_cb=lambda current, total: None,
        cancel_event=Event(),
    )

    assert not result.errors, result.errors
    output = outdir / "clip.jpg"
    assert output.is_file()
    with Image.open(output) as image:
        assert image.format == "JPEG"
        assert image.size == (32, 24)
    # The intermediate frame never outlives the conversion.
    assert created and not created[0].exists()


def test_failed_frame_extraction_is_reported_and_cleaned_up(
    fake_ffmpeg: Path,
    fake_frame: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_FFMPEG_MODE", "frame_fail")
    monkeypatch.setenv("FAKE_FRAME_PNG", str(fake_frame))
    monkeypatch.setattr(image_converter_module, "locate_ffmpeg", lambda: fake_ffmpeg)
    monkeypatch.setattr(image_converter_module, "video_available", lambda: True)

    created: list[Path] = []
    real_named_temporary_file = _tempfile.NamedTemporaryFile

    def recorder(*args, **kwargs):
        handle = real_named_temporary_file(*args, **kwargs)
        created.append(Path(handle.name))
        return handle

    monkeypatch.setattr(_tempfile, "NamedTemporaryFile", recorder)

    clip = _make_clip(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()

    result = PillowImageConverter().convert(
        input_paths=[str(clip)],
        output_dir=str(outdir),
        target_format="png",
        options={},
        progress_cb=lambda current, total: None,
        cancel_event=Event(),
    )

    assert not result.outputs
    assert len(result.errors) == 1, result.errors
    assert "Invalid data found" in result.errors[0]
    assert created and not created[0].exists(), (
        "a failed extraction left an empty frame behind"
    )


def test_frame_extraction_without_ffmpeg_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Capability gating again, from the image side: the message has to name
    # ffmpeg, because the fix is installing it, not changing a setting.
    monkeypatch.setattr(image_converter_module, "locate_ffmpeg", lambda: None)

    with pytest.raises(UnsupportedFormatError) as excinfo:
        PillowImageConverter._extract_video_frame(Path("clip.mp4"))

    assert "ffmpeg" in str(excinfo.value)


# --- GIF as a video format ---------------------------------------------------


def test_gif_input_converts_to_mp4_through_the_shared_pump(
    fake_ffmpeg: Path, tmp_path: Path
) -> None:
    # GIF is an input of the video converter (and not an output of it): the
    # same capability gate, matrix, and encode loop as any video container.
    # The fake never reads the input, so a bare GIF89a header is enough.
    gif = tmp_path / "anim.gif"
    gif.write_bytes(b"GIF89a fake animation source")
    outdir = tmp_path / "out"
    outdir.mkdir()

    result = _convert(FFmpegVideoConverter(), [str(gif)], outdir)

    assert not result.errors, result.errors
    assert result.outputs == [(str(gif), str(outdir / "anim.mp4"))]
    assert (outdir / "anim.mp4").is_file()


def test_video_to_gif_runs_the_palette_chain_and_writes_an_animation(
    fake_ffmpeg: Path,
    fake_gif_template: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The full video -> GIF path: image converter, ffmpeg branch, shared
    # pump. What makes it an *animation* rather than a first-frame still is
    # the palette chain on -vf - the report's split/palettegen/paletteuse -
    # plus -loop 0, and none of -frames:v (which is the still-frame path).
    monkeypatch.setenv("FAKE_GIF_TEMPLATE", str(fake_gif_template))
    argv_file = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_ARGV_FILE", str(argv_file))
    monkeypatch.setattr(image_converter_module, "locate_ffmpeg", lambda: fake_ffmpeg)
    monkeypatch.setattr(image_converter_module, "video_available", lambda: True)

    clip = _make_clip(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()
    seen: list[tuple[float, int]] = []

    result = PillowImageConverter().convert(
        input_paths=[str(clip)],
        output_dir=str(outdir),
        target_format="gif",
        options={},
        progress_cb=lambda current, total: seen.append((current, total)),
        cancel_event=Event(),
    )

    assert not result.errors, result.errors
    output = outdir / "clip.gif"
    assert output.is_file()
    with Image.open(output) as image:
        assert image.format == "GIF"
        assert getattr(image, "n_frames", 1) > 1

    argv = argv_file.read_text(encoding="utf-8").splitlines()
    assert argv[argv.index("-i") + 1] == str(clip)
    assert argv[-1] == str(output)
    filter_chain = argv[argv.index("-vf") + 1]
    assert "palettegen" in filter_chain and "paletteuse" in filter_chain
    assert "fps=" in filter_chain
    assert argv[argv.index("-loop") + 1] == "0"
    assert "-frames:v" not in argv

    # The pump's in-file tick arrives mapped onto the batch fraction, and
    # the file boundary closes it at (1, 1).
    currents = [current for current, _ in seen]
    assert currents and all(
        later >= earlier for earlier, later in zip(currents, currents[1:])
    ), f"progress went backwards: {currents}"
    assert any(isinstance(current, float) for current in currents)
    assert seen[-1] == (1, 1)


def test_image_converter_advertises_gif_to_the_video_ring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The donut's ring membership is declared by the converter that writes
    # the format - GIF is written here from clips as well as from stills, so
    # it belongs to the video ring too. Gated exactly like everything video.
    monkeypatch.setattr(image_converter_module, "video_available", lambda: True)
    assert PillowImageConverter().also_video_outputs == ("gif",)

    monkeypatch.setattr(image_converter_module, "video_available", lambda: False)
    assert PillowImageConverter().also_video_outputs == ()

    assert FFmpegVideoConverter().also_video_outputs == ()
