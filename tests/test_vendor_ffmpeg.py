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

import subprocess
from pathlib import Path
from threading import Event

import pytest
from PIL import Image

from flux.services.ffmpeg import (
    locate_ffmpeg,
    pick_encoder,
    probe_encoders,
    video_available,
)
from flux.services.image_converter import PillowImageConverter
from flux.services.video_converter import FFmpegVideoConverter

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
    """A real H.264 clip synthesised from a test pattern (no binary fixture).

    1.2 seconds of 64x64 testsrc2: long enough that -progress reports at
    least one in-file tick, short enough that every test here stays fast.
    """
    out = tmp_path_factory.mktemp("real-src") / "source.mp4"
    proc = subprocess.run(
        [
            str(real_ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10",
            "-t", "1.2", "-pix_fmt", "yuv420p", str(out),
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
    assert "libx264" in probe_encoders()


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
