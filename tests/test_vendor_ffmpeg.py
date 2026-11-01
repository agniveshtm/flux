"""Real-ffmpeg encodes, run only when a capable binary is actually present.

Every other test here speaks to a stand-in ffmpeg so the suite runs on any
machine; these are the flip side - they drive the real binary (vendored at
vendor/ffmpeg.exe, or whatever locate_ffmpeg resolves to) end to end and
prove the produced files genuinely decode, which a stand-in cannot claim.
A fresh clone without vendor/ and without a system ffmpeg skips them all;
`uv run pytest tests/ -q` stays green either way, and `vendor/README.md`
says how to make them run.

What only a real encode can catch: the Duration line real ffmpeg writes
(but not the stand-in's), a filter chain that syntax-errors, an encoder
that cannot take the flags we pass it, and a file that muxes fine but does
not decode back.
"""

from __future__ import annotations

import base64
import io
import subprocess
from pathlib import Path
from threading import Event

import pytest
from PIL import Image

from flux.services.ffmpeg import (
    AUDIO_OUTPUT_FORMATS,
    AUDIO_OUTPUT_MUXERS,
    VIDEO_OUTPUT_FORMATS,
    VIDEO_OUTPUT_MUXERS,
    audio_encoder_for,
    audio_output_available,
    locate_ffmpeg,
    pick_encoder,
    probe_encoders,
    probe_muxers,
    video_available,
    video_output_available,
)
from flux.services.audio_converter import FFmpegAudioConverter
from flux.services.image_converter import PillowImageConverter
from flux.services.video_converter import FFmpegVideoConverter
from flux.window import FluxAPI

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDORED_FFMPEG = REPO_ROOT / "vendor" / "ffmpeg.exe"


@pytest.fixture(scope="session")
def real_ffmpeg() -> Path:
    """A real, capable ffmpeg binary for the whole module to share."""
    located = locate_ffmpeg()
    if located is None or not video_available():
        pytest.skip(
            "no capable ffmpeg binary - vendor/ is absent and none on PATH"
        )
    return located


@pytest.fixture(scope="session")
def real_clip(tmp_path_factory, real_ffmpeg: Path) -> Path:
    """A real H.264 + AAC clip synthesised from test patterns.

    1.2 seconds of 64x64 testsrc2 over a 440 Hz sine: the video half keeps
    the progress/tick tests meaningful, and the audio stream is what the
    extraction targets (MP3/WAV) have to find. Short enough that every test
    here stays fast.
    """
    out = tmp_path_factory.mktemp("real-src") / "source.mp4"
    proc = subprocess.run(
        [
            str(real_ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
            "-t", "1.2", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "64k", "-shortest", str(out),
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"source clip generation failed: {proc.stderr}"
    return out


@pytest.fixture(scope="session")
def real_gif(tmp_path_factory) -> Path:
    """A real 3-frame animated GIF, written by Pillow (the gif writer)."""
    out = tmp_path_factory.mktemp("real-src") / "anim.gif"
    frames = [Image.new("RGB", (48, 48), color) for color in ("red", "green", "blue")]
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=80, loop=0)
    return out


def _assert_decodable(ffmpeg: Path, path: Path) -> None:
    """ffmpeg itself must decode every frame without a single complaint."""
    proc = subprocess.run(
        [str(ffmpeg), "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"decode failed for {path}: {proc.stderr}"
    assert proc.stderr.strip() == "", f"decode errors for {path}: {proc.stderr}"


def _stream_summary(ffmpeg: Path, path: Path) -> str:
    """The 'Stream #...' lines ffmpeg prints for a file, as one string."""
    proc = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    return "\n".join(
        line for line in proc.stderr.splitlines() if "Stream #" in line
    )


def test_the_vendored_build_includes_libx264(real_ffmpeg: Path) -> None:
    # The whole vendoring decision in one assertion: gyan.dev essentials
    # (GPLv3) was chosen over the LGPL builds precisely because it ships
    # libx264, and libx264-first is the Phase 2.1 contract - a build that
    # silently fell back to VP9 would break it.
    if not VENDORED_FFMPEG.exists():
        pytest.skip("vendor/ffmpeg.exe is absent; nothing to pin the build to")

    proc = subprocess.run(
        [str(real_ffmpeg), "-hide_banner", "-encoders"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "libx264" in proc.stdout, "the vendored build lost libx264"
    assert pick_encoder() == "libx264", (
        f"preference table picked {pick_encoder()!r} although libx264 is present"
    )
    assert "libx264" in probe_encoders(), (
        "the vendored build lost libx264"
    )


def test_the_vendored_build_includes_the_phase_2_2_encoders(
    real_ffmpeg: Path,
) -> None:
    """The containers and extractions we advertise need their codecs present.

    Phase 2.2 added WebM/VP9, Opus for WebM/MKV, and MP3/WAV extraction. Each
    target is capability-gated at runtime, so a build missing one would
    simply hide it - but the *vendored* build is the one the installer ships,
    and a silent hide would mean shipping an incomplete matrix. This pins the
    matrix the release is supposed to have, the same way libx264 is pinned.
    """
    if not VENDORED_FFMPEG.exists():
        pytest.skip("vendor/ffmpeg.exe is absent; nothing to pin the build to")

    proc = subprocess.run(
        [str(real_ffmpeg), "-hide_banner", "-encoders"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    for encoder in ("libvpx-vp9", "libopus", "libmp3lame", "pcm_s16le"):
        assert encoder in proc.stdout, f"the vendored build lost {encoder}"
        assert encoder in probe_encoders()

    for target in VIDEO_OUTPUT_FORMATS:
        assert video_output_available(target), (
            f"the vendored build cannot write {target} despite its codecs"
        )
        assert VIDEO_OUTPUT_MUXERS[target] in probe_muxers(), (
            f"the vendored build lost the {VIDEO_OUTPUT_MUXERS[target]} muxer"
        )
    for target in AUDIO_OUTPUT_FORMATS:
        assert audio_output_available(target), (
            f"the vendored build cannot extract {target}"
        )
        assert AUDIO_OUTPUT_MUXERS[target] in probe_muxers(), (
            f"the vendored build lost the {AUDIO_OUTPUT_MUXERS[target]} muxer"
        )


def test_a_real_mp4_transcode_reports_progress_and_decodes(
    real_ffmpeg: Path, real_clip: Path, tmp_path: Path
) -> None:
    outdir = tmp_path / "out"
    outdir.mkdir()
    seen: list[tuple[float, int]] = []

    result = FFmpegVideoConverter().convert(
        input_paths=[str(real_clip)],
        output_dir=str(outdir),
        target_format="mp4",
        options={},
        progress_cb=lambda current, total: seen.append((current, total)),
        cancel_event=Event(),
    )

    assert not result.errors, result.errors
    output = outdir / "source.mp4"
    assert output.is_file() and output.stat().st_size > 0

    # Duration and out_time both come from the *real* streams here: if the
    # stderr header stops parsing, the in-file float never arrives.
    currents = [current for current, _ in seen]
    assert any(isinstance(current, float) for current in currents), (
        f"no in-file progress from the real ffmpeg: {currents}"
    )
    assert all(
        later >= earlier for earlier, later in zip(currents, currents[1:])
    ), f"progress went backwards: {currents}"
    assert seen[-1] == (1, 1)

    _assert_decodable(real_ffmpeg, output)


def test_a_real_video_to_gif_is_a_real_animation(
    real_ffmpeg: Path, real_clip: Path, tmp_path: Path
) -> None:
    outdir = tmp_path / "out"
    outdir.mkdir()

    result = PillowImageConverter().convert(
        input_paths=[str(real_clip)],
        output_dir=str(outdir),
        target_format="gif",
        options={},
        progress_cb=lambda current, total: None,
        cancel_event=Event(),
    )

    assert not result.errors, result.errors
    output = outdir / "source.gif"
    assert output.is_file()

    # The point of the palette chain: every frame of the clip is in the
    # gif, not just the first one a still extraction would have written.
    with Image.open(output) as image:
        assert image.format == "GIF"
        assert image.n_frames > 1, (
            f"the gif has {image.n_frames} frame(s) - the palette chain "
            "wrote a still, not an animation"
        )


def test_a_real_gif_input_converts_to_mp4_and_decodes(
    real_ffmpeg: Path, real_gif: Path, tmp_path: Path
) -> None:
    outdir = tmp_path / "out"
    outdir.mkdir()

    result = FFmpegVideoConverter().convert(
        input_paths=[str(real_gif)],
        output_dir=str(outdir),
        target_format="mp4",
        options={},
        progress_cb=lambda current, total: None,
        cancel_event=Event(),
    )

    assert not result.errors, result.errors
    output = outdir / "anim.mp4"
    assert output.is_file() and output.stat().st_size > 0
    _assert_decodable(real_ffmpeg, output)


@pytest.mark.parametrize("target", VIDEO_OUTPUT_FORMATS)
def test_every_video_container_encodes_and_decodes(
    real_ffmpeg: Path, real_clip: Path, tmp_path: Path, target: str
) -> None:
    """Each advertised container must actually mux and decode end to end.

    A stand-in ffmpeg can prove the argv shape, but only the real binary
    proves the container accepts that encoder pair and the muxer flags -
    VP9-in-WebM, Opus-in-MKV and the AVI index reserve are exactly the kind
    of thing that fails at exec time. The stream check proves the audio half
    is present, not just the picture.
    """
    if not video_output_available(target):
        pytest.skip(f"this build has no encoder pair for {target}")

    outdir = tmp_path / "out"
    outdir.mkdir()

    result = FFmpegVideoConverter().convert(
        input_paths=[str(real_clip)],
        output_dir=str(outdir),
        target_format=target,
        options={"quality": 50},
        progress_cb=lambda current, total: None,
        cancel_event=Event(),
    )

    assert not result.errors, result.errors
    output = outdir / f"source.{target}"
    assert output.is_file() and output.stat().st_size > 0
    streams = _stream_summary(real_ffmpeg, output)
    assert "Video:" in streams, f"{target} lost its video stream: {streams}"
    assert "Audio:" in streams, f"{target} lost its audio stream: {streams}"

    _assert_decodable(real_ffmpeg, output)


@pytest.mark.parametrize("target", AUDIO_OUTPUT_FORMATS)
def test_every_audio_target_extracts_and_decodes(
    real_ffmpeg: Path, real_clip: Path, tmp_path: Path, target: str
) -> None:
    """MP3 and WAV must contain the soundtrack and nothing else.

    ``-vn`` is the flag under test: if it stopped being passed, ffmpeg would
    try to carry the video stream into a container that cannot hold it (or
    silently produce a video-in-WAV oddity). The stream summary pins the
    output to audio only, and the decode proves the codec flags mux.
    """
    if audio_encoder_for(target) is None:
        pytest.skip(f"this build has no encoder for {target}")

    outdir = tmp_path / "out"
    outdir.mkdir()

    result = FFmpegAudioConverter().convert(
        input_paths=[str(real_clip)],
        output_dir=str(outdir),
        target_format=target,
        options={"quality": 50},
        progress_cb=lambda current, total: None,
        cancel_event=Event(),
    )

    assert not result.errors, result.errors
    output = outdir / f"source.{target}"
    assert output.is_file() and output.stat().st_size > 0
    streams = _stream_summary(real_ffmpeg, output)
    assert "Audio:" in streams, f"{target} has no audio stream: {streams}"
    assert "Video:" not in streams, f"{target} kept a video stream: {streams}"
    _assert_decodable(real_ffmpeg, output)


def test_real_stills_never_get_an_audio_target(real_ffmpeg: Path) -> None:
    """The matrix, not just the converter, keeps MP3/WAV off stills."""
    registry = FluxAPI().registry
    audio_targets = {
        target for target in AUDIO_OUTPUT_FORMATS
        if audio_encoder_for(target) is not None
    }
    assert audio_targets, "the vendored build has no audio target to check"
    for still in ("jpg", "png", "webp", "gif", "ico"):
        targets = set(registry.supported_targets_by_input.get(still, []))
        assert audio_targets.isdisjoint(targets), (
            f"a still ({still}) offers audio extraction: "
            f"{sorted(audio_targets & targets)}"
        )

def test_real_video_input_gets_a_poster_frame_preview(real_clip: Path) -> None:
    """A real clip must preview as a real, decodable still.

    The bridge used to answer every video with "Only image files can be
    previewed.", which is what put the "!" in the row. This drives the actual
    ffmpeg frame extraction end to end and decodes the returned JPEG, so a
    broken filter chain or a bad seek fallback fails here rather than in the
    app.
    """
    result = FluxAPI().getFilePreview(str(real_clip), {"maxEdge": 64})

    assert "dataUrl" in result, result
    prefix, _, payload = result["dataUrl"].partition(",")
    assert prefix == "data:image/jpeg;base64", prefix
    frame = Image.open(io.BytesIO(base64.b64decode(payload)))
    assert frame.size[0] <= 64 and frame.size[1] <= 64, frame.size

def test_real_portrait_video_preview_respects_both_dimensions(
    real_ffmpeg: Path, tmp_path: Path
) -> None:
    """A tall clip must fit the edge box, not just the width.

    The first filter capped width only, so 180x320 at maxEdge=100 became
    100x178 and broke the bridge's longest-edge promise. Both dimensions are
    now bounded.
    """
    portrait = tmp_path / "portrait.mp4"
    proc = subprocess.run(
        [
            str(real_ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=180x320:rate=10",
            "-t", "1.2", "-pix_fmt", "yuv420p", str(portrait),
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr

    result = FluxAPI().getFilePreview(str(portrait), {"maxEdge": 100})

    assert "dataUrl" in result, result
    _, _, payload = result["dataUrl"].partition(",")
    frame = Image.open(io.BytesIO(base64.b64decode(payload)))
    assert max(frame.size) <= 100, frame.size
    assert frame.height > frame.width, frame.size
