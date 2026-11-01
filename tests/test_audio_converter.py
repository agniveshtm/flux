"""Phase 2.2 audio extraction: MP3/WAV commands, gating, and the encode loop.

Like the video tests, the encode loop is exercised against a stand-in ffmpeg
(a small Python script behind a launcher) rather than a real binary, so the
suite runs identically on machines without one - which is the whole
capability story: no ffmpeg means no audio formats, and every test here still
has to hold. The fake speaks the two surfaces the converter depends on:

* ``-encoders`` for the capability probe (which codecs the build has decides
  which targets are offered);
* ``-progress pipe:1`` on stdout plus ``Duration:`` on stderr for the bar.

What real encodes additionally prove - that the flags mux and decode - lives
in tests/test_vendor_ffmpeg.py, which only runs when a real binary is present.
"""

from __future__ import annotations

import sys
from pathlib import Path
from threading import Event

import pytest

import flux.services.audio_converter as audio_converter
import flux.services.ffmpeg as ffmpeg_module
from flux.converter import UnsupportedFormatError
from flux.services.audio_converter import (
    FFmpegAudioConverter,
    audio_encode_args,
    mp3_quality,
)
from flux.services.ffmpeg import (
    AUDIO_OUTPUT_FORMATS,
    VIDEO_INPUT_FORMATS,
    audio_available,
    audio_encoder_for,
)

# The fake's encoders listing, in the format ffmpeg -encoders prints.
_ENCODERS_AUDIO = (
    "Encoders:\n"
    " A....D aac                  AAC (Advanced Audio Coding)\n"
    " A....D libmp3lame           libmp3lame MP3\n"
    " A....D pcm_s16le            PCM signed 16-bit little-endian\n"
)
_ENCODERS_NO_MP3 = (
    "Encoders:\n"
    " A....D aac                  AAC (Advanced Audio Coding)\n"
    " A....D pcm_s16le            PCM signed 16-bit little-endian\n"
)
_ENCODERS_NEITHER = "Encoders:\n A....D aac   AAC (Advanced Audio Coding)\n"

_FAKE_FFMPEG = '''\
"""Stand-in ffmpeg for the audio tests: same CLI surface, no codecs."""
import os
import sys
import time

args = sys.argv[1:]

argv_file = os.environ.get("FAKE_ARGV_FILE")
if argv_file:
    with open(argv_file, "w", encoding="utf-8") as fh:
        fh.write("\\n".join(args))

if "-encoders" in args:
    sys.stdout.write(os.environ.get("FAKE_ENCODERS", ""))
    sys.exit(0)

output = args[-1]

if os.environ.get("FAKE_FFMPEG_MODE") == "fail":
    print("[mp3 @ 0x007f] Error while opening encoder", file=sys.stderr, flush=True)
    print(output + ": Invalid argument", file=sys.stderr, flush=True)
    sys.exit(1)

# Announce the duration exactly as -loglevel info does, so the converter's
# ffprobe replacement has something to parse. The pause stands in for a real
# encode's startup so the tick below is not dropped against an unknown
# duration.
print("Duration: 00:00:02.00, start: 0.000000, bitrate: 128 kb/s",
      file=sys.stderr, flush=True)
time.sleep(0.2)
sys.stdout.write("out_time=00:00:01.00\\n")
sys.stdout.flush()

with open(output, "wb") as dst:
    dst.write(b"fake audio bytes")
sys.exit(0)
'''


@pytest.fixture(autouse=True)
def _fresh_probe_cache():
    """No test may inherit -encoders state cached by another one."""
    ffmpeg_module.reset_probe_cache()
    yield
    ffmpeg_module.reset_probe_cache()


@pytest.fixture
def fake_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the converter and the probe at a fake binary."""
    script = tmp_path / "fake_ffmpeg.py"
    script.write_text(_FAKE_FFMPEG, encoding="utf-8")

    if sys.platform == "win32":
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

    monkeypatch.setattr(audio_converter, "locate_ffmpeg", lambda: launcher)
    monkeypatch.setattr(ffmpeg_module, "locate_ffmpeg", lambda: launcher)
    monkeypatch.setenv("FAKE_ENCODERS", _ENCODERS_AUDIO)
    ffmpeg_module.reset_probe_cache()
    return launcher


def _make_clip(directory: Path, name: str = "clip.mp4") -> Path:
    clip = directory / name
    clip.write_bytes(b"\x00\x00\x00\x18ftypisom fake input, the fake never reads it")
    return clip


def _convert(
    converter: FFmpegAudioConverter,
    input_paths: list[str],
    output_dir: Path,
    progress_cb=None,
    cancel_event: Event | None = None,
    target_format: str = "mp3",
    options: dict | None = None,
):
    return converter.convert(
        input_paths=input_paths,
        output_dir=str(output_dir),
        target_format=target_format,
        options=options or {},
        progress_cb=progress_cb or (lambda current, total: None),
        cancel_event=cancel_event or Event(),
    )


# --- quality mapping --------------------------------------------------------


def test_mp3_quality_maps_the_slider_window() -> None:
    # libmp3lame's -q:a runs the opposite way to the video CRFs: 0 is best,
    # 9 is smallest. The untouched default is LAME's high-quality VBR tier,
    # not the middle of the slider.
    assert mp3_quality(None) == 2
    assert mp3_quality(100) == 0
    assert mp3_quality(50) == 5
    assert mp3_quality(0) == 9
    # Out-of-range and nonsense values clamp rather than leaving 0-9.
    assert mp3_quality(-20) == 9
    assert mp3_quality(500) == 0
    assert mp3_quality("fast") == 5


def test_audio_encode_args_are_per_target() -> None:
    mp3 = audio_encode_args("mp3", 100)
    assert mp3[mp3.index("-c:a") + 1] == "libmp3lame"
    assert mp3[mp3.index("-q:a") + 1] == "0"
    assert mp3[mp3.index("-write_xing") + 1] == "0"
    assert mp3[mp3.index("-id3v2_version") + 1] == "0"

    wav = audio_encode_args("wav", 100)
    assert wav == ["-c:a", "pcm_s16le"]
    assert "-q:a" not in wav, "WAV is uncompressed; quality must not apply"

    with pytest.raises(UnsupportedFormatError):
        audio_encode_args("flac", None)


# --- capability gating ------------------------------------------------------


def test_audio_converter_declares_only_video_inputs_and_its_targets(
    fake_ffmpeg: Path,
) -> None:
    converter = FFmpegAudioConverter()
    assert converter.kind == "audio"
    assert converter.supported_output_formats == [
        fmt for fmt in AUDIO_OUTPUT_FORMATS if audio_encoder_for(fmt) is not None
    ]
    # Only the video containers are readable. GIF and stills are absent, which
    # is what keeps MP3/WAV off every image row.
    assert converter.supported_input_formats == list(VIDEO_INPUT_FORMATS)
    assert "gif" not in converter.supported_input_formats
    assert audio_available()


def test_audio_targets_are_gated_per_encoder(
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

    # WAV survives a build without libmp3lame; MP3 does not.
    monkeypatch.setenv("FAKE_ENCODERS", _ENCODERS_NO_MP3)
    ffmpeg_module.reset_probe_cache()
    assert FFmpegAudioConverter().supported_output_formats == ["wav"]
    assert FFmpegAudioConverter().supported_input_formats == list(VIDEO_INPUT_FORMATS)
    assert audio_encoder_for("mp3") is None
    assert audio_encoder_for("wav") == "pcm_s16le"
    assert audio_available()

    # No audio encoder at all: the converter registers nothing and admits
    # no inputs either, so the app stays image-only on that build.
    monkeypatch.setenv("FAKE_ENCODERS", _ENCODERS_NEITHER)
    ffmpeg_module.reset_probe_cache()
    assert FFmpegAudioConverter().supported_output_formats == []
    assert FFmpegAudioConverter().supported_input_formats == []
    assert not audio_available()


def test_convert_refuses_targets_it_cannot_write(
    fake_ffmpeg: Path, tmp_path: Path
) -> None:
    with pytest.raises(UnsupportedFormatError):
        _convert(
            FFmpegAudioConverter(),
            [str(_make_clip(tmp_path))],
            tmp_path,
            target_format="flac",
        )


def test_stills_are_refused_and_leave_nothing_behind(
    fake_ffmpeg: Path, tmp_path: Path
) -> None:
    # Audio extraction reads video containers only. A still is rejected by
    # the shared batch loop, so no MP3/WAV ever appears for a photo even if
    # the frontend somehow asked for one.
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"not really a jpeg, the check is suffix-only")
    outdir = tmp_path / "out"
    outdir.mkdir()

    result = _convert(FFmpegAudioConverter(), [str(photo)], outdir)

    assert not result.outputs
    assert len(result.errors) == 1
    assert "Unsupported input format: jpg" in result.errors[0]
    assert list(outdir.iterdir()) == []


# --- the encode loop --------------------------------------------------------


def test_convert_writes_an_output_and_reports_progress(
    fake_ffmpeg: Path, tmp_path: Path
) -> None:
    clip = _make_clip(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()
    seen: list[tuple[float, int]] = []

    result = _convert(
        FFmpegAudioConverter(),
        [str(clip)],
        outdir,
        progress_cb=lambda current, total: seen.append((current, total)),
    )

    assert not result.errors, result.errors
    assert result.outputs == [(str(clip), str(outdir / "clip.mp3"))]
    assert (outdir / "clip.mp3").read_bytes() == b"fake audio bytes"
    assert any(isinstance(current, float) for current, _ in seen)
    assert seen[-1] == (1, 1)


def test_mp3_command_carries_the_vbr_flags(
    fake_ffmpeg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv_file = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_ARGV_FILE", str(argv_file))
    clip = _make_clip(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()

    result = _convert(
        FFmpegAudioConverter(),
        [str(clip)],
        outdir,
        target_format="mp3",
        options={"quality": 100},
    )

    assert not result.errors, result.errors
    argv = argv_file.read_text(encoding="utf-8").splitlines()

    assert "-vn" in argv, argv
    assert argv[argv.index("-c:a") + 1] == "libmp3lame"
    assert argv[argv.index("-q:a") + 1] == "0"
    assert argv[argv.index("-write_xing") + 1] == "0"
    assert argv[argv.index("-id3v2_version") + 1] == "0"
    assert argv[argv.index("-i") + 1] == str(clip)
    assert argv[-1] == str(outdir / "clip.mp3")


def test_wav_command_drops_the_quality_flags(
    fake_ffmpeg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv_file = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_ARGV_FILE", str(argv_file))
    clip = _make_clip(tmp_path, "clip.mkv")
    outdir = tmp_path / "out"
    outdir.mkdir()

    result = _convert(
        FFmpegAudioConverter(),
        [str(clip)],
        outdir,
        target_format="wav",
        options={"quality": 100},
    )

    assert not result.errors, result.errors
    argv = argv_file.read_text(encoding="utf-8").splitlines()

    assert "-vn" in argv, argv
    assert argv[argv.index("-c:a") + 1] == "pcm_s16le"
    assert "-q:a" not in argv, "WAV is uncompressed; -q:a must not be passed"
    assert "-write_xing" not in argv
    assert "-id3v2_version" not in argv
    assert argv[-1] == str(outdir / "clip.wav")


def test_failed_encode_surfaces_the_diagnostic_line(
    fake_ffmpeg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_FFMPEG_MODE", "fail")
    clip = _make_clip(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()

    result = _convert(FFmpegAudioConverter(), [str(clip)], outdir)

    assert not result.outputs
    assert len(result.errors) == 1, result.errors
    assert result.errors[0].startswith("clip.mp4:")
    assert "Invalid argument" in result.errors[0]
    assert not (outdir / "clip.mp3").exists()
