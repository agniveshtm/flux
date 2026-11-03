"""Preview-bridge guards.

getFilePreview decodes through Pillow before it applies any size limit, so the
caps have to be enforced from the image header rather than after the fact -
otherwise a small file that decompresses to an enormous image defeats them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from flux import window as window_module
from flux.window import FluxAPI

# Not a valid JPEG (the bridge only base64s ffmpeg's stdout), but enough to
# assert the data-URL shape without spawning a real encode.
_FAKE_JPEG = b"\xff\xd8\xff\xe0fake-frame\xff\xd9"


def _completed(
    returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture
def api() -> FluxAPI:
    return FluxAPI()


def _write(path: Path, image: Image.Image) -> Path:
    image.save(path)
    return path


def test_preview_returns_a_data_url(tmp_path: Path, api: FluxAPI) -> None:
    source = _write(tmp_path / "small.png", Image.new("RGB", (64, 64), (10, 120, 200)))

    result = api.getFilePreview(str(source))

    assert "dataUrl" in result, result
    assert result["dataUrl"].startswith("data:image/")


def test_preview_thumbnails_to_the_requested_edge(
    tmp_path: Path, api: FluxAPI
) -> None:
    # Without the thumbnail the base64 payload would be the full-resolution
    # image, which is what made a large batch expensive to list.
    source = _write(tmp_path / "big.png", Image.new("RGB", (1600, 1200), (200, 30, 60)))

    result = api.getFilePreview(str(source), {"maxEdge": 64})

    assert "dataUrl" in result, result


def test_oversized_image_is_rejected_before_decoding(
    tmp_path: Path, api: FluxAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The ceiling is lowered rather than allocating a 40MP image: the guard reads
    # the dimensions from the header, so what is being tested is that it refuses
    # before calling load(), not that Pillow can allocate that much.
    monkeypatch.setattr(FluxAPI, "_PREVIEW_MAX_PIXELS", 100)

    source = _write(tmp_path / "large.png", Image.new("RGB", (200, 200), (5, 5, 5)))

    result = api.getFilePreview(str(source))

    assert "dataUrl" not in result
    assert result.get("code") == "VALIDATION_ERROR"


def test_preview_preserves_transparency_as_png(tmp_path: Path, api: FluxAPI) -> None:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    image.paste((255, 0, 0, 255), (0, 0, 32, 64))
    source = _write(tmp_path / "alpha.png", image)

    result = api.getFilePreview(str(source))

    assert "dataUrl" in result, result
    assert result["dataUrl"].startswith("data:image/png")


def test_video_preview_returns_a_poster_frame_data_url(
    tmp_path: Path, api: FluxAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Video rows used to land on the "!" fallback because the bridge refused
    # every non-image suffix. They now go through ffmpeg for one frame.
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"not a real video, ffmpeg is faked")

    calls: list[list[str]] = []
    kwargs_seen: list[dict[str, object]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(cmd)
        kwargs_seen.append(kwargs)
        return _completed(stdout=_FAKE_JPEG)

    monkeypatch.setattr(window_module, "locate_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(window_module.subprocess, "run", fake_run)

    result = api.getFilePreview(str(source), {"maxEdge": 128})

    assert "dataUrl" in result, result
    assert result["dataUrl"].startswith("data:image/jpeg;base64,")
    assert len(calls) == 1, calls
    cmd = calls[0]
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-ss") + 1] == "1", "the poster frame should seek past the title card"
    scale = cmd[cmd.index("-vf") + 1]
    assert "min(iw,128)" in scale and "min(ih,128)" in scale, scale
    assert "force_original_aspect_ratio=decrease" in scale, scale
    assert "-frames:v" in cmd and cmd[cmd.index("-frames:v") + 1] == "1"
    assert cmd[-1] == "pipe:1"
    # A windowed build has no console, so a console child would flash its own.
    # The preview must spawn ffmpeg with the no-window flag like every other
    # spawn in the app (tests/test_video_converter.py pins the ffmpeg side).
    assert kwargs_seen[0].get("creationflags") == window_module.NO_WINDOW_FLAGS


def test_video_preview_clamps_edges_before_running_ffmpeg(
    tmp_path: Path, api: FluxAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    # maxEdge is bridge input, so an unbounded or nonsensical value must not
    # reach ffmpeg. <=0 follows the image path's "no size chosen" case (a
    # video has no stored still, so it becomes the thumbnail default), and
    # anything larger is held to the modal's 2048 ceiling.
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"not a real video")
    scales: list[str] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        scales.append(cmd[cmd.index("-vf") + 1])
        return _completed(stdout=_FAKE_JPEG)

    monkeypatch.setattr(window_module, "locate_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(window_module.subprocess, "run", fake_run)

    api.getFilePreview(str(source), {"maxEdge": 0})
    api.getFilePreview(str(source), {"maxEdge": -40})
    api.getFilePreview(str(source), {"maxEdge": 100_000})

    assert "min(iw,512)" in scales[0], scales[0]
    assert "min(iw,512)" in scales[1], scales[1]
    assert "min(iw,2048)" in scales[2], scales[2]


def test_video_preview_falls_back_to_the_first_frame(
    tmp_path: Path, api: FluxAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A clip shorter than one second has no frame at 00:01, so the bridge
    # retries from the start rather than showing "!" for a valid file.
    source = tmp_path / "short.webm"
    source.write_bytes(b"not a real video")

    seeks: list[str] = []
    responses = iter(
        [
            _completed(returncode=1, stderr=b"no frame at 1s"),
            _completed(stdout=_FAKE_JPEG),
        ]
    )

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seeks.append(cmd[cmd.index("-ss") + 1])
        return next(responses)

    monkeypatch.setattr(window_module, "locate_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(window_module.subprocess, "run", fake_run)

    result = api.getFilePreview(str(source))

    assert result["dataUrl"].startswith("data:image/jpeg;base64,"), result
    assert seeks == ["1", "0"], seeks


def test_video_preview_needs_ffmpeg(
    tmp_path: Path, api: FluxAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "clip.mkv"
    source.write_bytes(b"not a real video")

    monkeypatch.setattr(window_module, "locate_ffmpeg", lambda: None)

    result = api.getFilePreview(str(source))

    assert "dataUrl" not in result
    assert result.get("code") == "PREVIEW_UNAVAILABLE"


def test_video_preview_reports_ffmpeg_failure(
    tmp_path: Path, api: FluxAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "broken.avi"
    source.write_bytes(b"not a real video")

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=20)

    monkeypatch.setattr(window_module, "locate_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(window_module.subprocess, "run", fake_run)

    result = api.getFilePreview(str(source))

    assert "dataUrl" not in result
    assert result.get("code") == "READ_ERROR"


def test_unknown_suffix_is_not_previewable(tmp_path: Path, api: FluxAPI) -> None:
    # The allowlist is a security boundary: a document must not be handed to
    # ffmpeg (or read) just because the row asked for a thumbnail.
    source = tmp_path / "notes.txt"
    source.write_text("not a media file")

    result = api.getFilePreview(str(source))

    assert "dataUrl" not in result
    assert result.get("code") == "VALIDATION_ERROR"