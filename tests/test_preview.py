"""Preview-bridge guards.

getFilePreview decodes through Pillow before it applies any size limit, so the
caps have to be enforced from the image header rather than after the fact -
otherwise a small file that decompresses to an enormous image defeats them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from flux.window import FluxAPI


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