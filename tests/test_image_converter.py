"""Converter tests for the image format paths.

Phase 1.1.1 replaced the frontend's hardcoded format matrix with one derived
from the backend, which made image_converter.py the only place that decides
what Flux can convert - so the format behaviour is pinned here rather than
being exercised only through the UI.

Every test drives the real public entry point (convert) rather than the private
_save helper, because the interesting failures live in the code between them:
filename reservation, format validation and the encoder dispatch.
"""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import cast

import pytest
from PIL import Image, ImageCms
from PIL.IcoImagePlugin import IcoImageFile

from flux.converter import UnsupportedFormatError
from flux.services.image_converter import (
    OUTPUT_FORMATS,
    PillowImageConverter,
    _avif_available,
)


@pytest.fixture
def converter() -> PillowImageConverter:
    return PillowImageConverter()


def _convert(
    converter: PillowImageConverter,
    source: Path,
    output_dir: Path,
    target: str,
    options: dict | None = None,
) -> Path:
    result = converter.convert(
        input_paths=[str(source)],
        output_dir=str(output_dir),
        target_format=target,
        options=options or {},
        progress_cb=lambda current, total: None,
        cancel_event=Event(),
    )
    assert not result.errors, result.errors
    assert len(result.output_paths) == 1
    return Path(result.output_paths[0])


def _write(path: Path, image: Image.Image) -> Path:
    image.save(path)
    return path


# --- reading results --------------------------------------------------------
#
# Two helpers exist so the assertions below stay about behaviour rather than
# about Pillow's accessors, both of which are awkward to use directly:
#
# * Image.open() is typed as returning ImageFile, but .ico only exists on the
#   ICO plugin's IcoImageFile, so the attribute is invisible to a type checker.
# * Image.getpixel() is typed by mode (float | int | tuple | None), so every
#   `pixel[:3]` or `r, g, b, _ = pixel` would need narrowing first.


def _rgba_pixel(image: Image.Image, xy: tuple[int, int]) -> tuple[int, int, int, int]:
    """One pixel as RGBA.

    The cast is sound: after convert("RGBA") the runtime value is always a
    four-tuple, whatever the declared union says.
    """
    return cast(
        tuple[int, int, int, int], image.convert("RGBA").getpixel(xy)
    )


def _ico_sizes(path: Path) -> list[tuple[int, int]]:
    """Every frame size embedded in an .ico, sorted."""
    with Image.open(path) as icon:
        assert isinstance(icon, IcoImageFile), "expected an ICO file"
        return sorted(icon.ico.sizes())


def _ico_frame(path: Path, size: tuple[int, int]) -> Image.Image:
    """One embedded frame as RGBA.

    IcoImageFile.getimage() is the supported way to pull a single frame out.
    Selecting a frame by assigning to Image.size - which the tests used to do -
    depends on an implementation detail of the plugin rather than a documented
    operation, and is not something a type checker will accept.
    """
    with Image.open(path) as icon:
        assert isinstance(icon, IcoImageFile), "expected an ICO file"
        return icon.ico.getimage(size).convert("RGBA")


# --- ICO --------------------------------------------------------------------


def test_ico_embeds_every_standard_size(tmp_path: Path, converter: PillowImageConverter) -> None:
    source = _write(tmp_path / "logo.png", Image.new("RGBA", (512, 512), (200, 30, 40, 255)))

    output = _convert(converter, source, tmp_path, "ico")

    assert _ico_sizes(output) == [(16, 16), (32, 32), (48, 48), (256, 256)]


def test_ico_frames_are_square_for_non_square_sources(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    # Pillow derives frames with Image.thumbnail(), which keeps the aspect
    # ratio, so a 300x200 source would otherwise produce 256x170 frames.
    source = _write(tmp_path / "wide.png", Image.new("RGBA", (300, 200), (10, 20, 30, 255)))

    output = _convert(converter, source, tmp_path, "ico")

    sizes = _ico_sizes(output)
    assert sizes
    assert all(width == height for width, height in sizes)


def test_ico_padding_is_transparent_not_black(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    # An opaque non-square source still has to pad with real alpha, or the
    # letterbox shows up as black bars in the shell.
    source = _write(tmp_path / "wide.png", Image.new("RGB", (300, 200), (255, 0, 0)))

    output = _convert(converter, source, tmp_path, "ico")

    frame = _ico_frame(output, (256, 256))
    assert _rgba_pixel(frame, (2, 2))[3] == 0, "padding must be transparent"
    assert _rgba_pixel(frame, (128, 128))[:3] == (255, 0, 0), "artwork must be centred"


def test_ico_preserves_source_transparency(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    source_image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    source_image.paste((0, 0, 255, 255), (0, 0, 64, 64))
    source = _write(tmp_path / "alpha.png", source_image)

    output = _convert(converter, source, tmp_path, "ico")

    frame = _ico_frame(output, (32, 32))
    assert _rgba_pixel(frame, (2, 2)) == (0, 0, 255, 255), "opaque quadrant must survive"
    assert _rgba_pixel(frame, (28, 28))[3] == 0, "transparent quadrant must survive"


def test_ico_from_source_smaller_than_every_standard_size(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    # Pillow skips any requested size larger than the source, so a 10x10
    # favicon skipped all four defaults and wrote an ICO header declaring zero
    # images - a corrupt file Windows renders as a blank icon.
    source = _write(tmp_path / "favicon.png", Image.new("RGBA", (10, 10), (0, 255, 0, 255)))

    output = _convert(converter, source, tmp_path, "ico")

    sizes = _ico_sizes(output)
    assert sizes, "ICO must contain at least one image"
    assert max(sizes)[0] <= 10


def test_ico_honours_custom_sizes(tmp_path: Path, converter: PillowImageConverter) -> None:
    source = _write(tmp_path / "logo.png", Image.new("RGBA", (256, 256), (1, 2, 3, 255)))

    output = _convert(converter, source, tmp_path, "ico", {"icoSizes": [64, 128]})

    assert _ico_sizes(output) == [(64, 64), (128, 128)]


def test_ico_ignores_unusable_custom_sizes(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    # Out-of-range and non-numeric entries fall back to the defaults rather
    # than producing an icon with no frames.
    source = _write(tmp_path / "logo.png", Image.new("RGBA", (256, 256), (1, 2, 3, 255)))

    output = _convert(converter, source, tmp_path, "ico", {"icoSizes": ["x", 300, -4]})

    assert _ico_sizes(output) == [(16, 16), (32, 32), (48, 48), (256, 256)]


def test_ico_is_readable_as_a_conversion_input(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    source = _write(tmp_path / "logo.png", Image.new("RGBA", (512, 512), (9, 9, 9, 255)))
    icon = _convert(converter, source, tmp_path, "ico")

    output = _convert(converter, icon, tmp_path, "png")

    with Image.open(output) as result:
        assert result.size == (256, 256), "the largest embedded frame is read back"


# --- GIF --------------------------------------------------------------------


def _half_opaque() -> Image.Image:
    """Left half opaque red, right half fully transparent."""
    image = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
    image.paste((255, 0, 0, 255), (0, 0, 32, 32))
    return image


def test_gif_is_a_single_frame_palette_image(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    source = _write(tmp_path / "in.png", _half_opaque())

    output = _convert(converter, source, tmp_path, "gif")

    with Image.open(output) as result:
        assert result.format == "GIF"
        assert result.mode == "P"
        assert getattr(result, "n_frames", 1) == 1


def test_gif_preserves_transparency(tmp_path: Path, converter: PillowImageConverter) -> None:
    source = _write(tmp_path / "alpha.png", _half_opaque())

    output = _convert(converter, source, tmp_path, "gif")

    with Image.open(output) as result:
        assert "transparency" in result.info, "GIF must declare a transparent index"
        assert _rgba_pixel(result, (8, 8))[:3] == (255, 0, 0), "opaque half keeps its colour"
        assert _rgba_pixel(result, (48, 8))[3] == 0, "transparent half stays transparent"


def test_gif_cuts_partial_alpha_to_binary(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    # GIF has no partial alpha, so a 50%-opaque pixel must land on one side of
    # the threshold rather than silently becoming opaque.
    image = Image.new("RGBA", (16, 16), (0, 0, 255, 127))
    image.paste((0, 0, 255, 129), (0, 0, 8, 16))
    source = _write(tmp_path / "soft.png", image)

    output = _convert(converter, source, tmp_path, "gif")

    with Image.open(output) as result:
        # The alpha-129 patch covers x=0..7, so x=4 is above the threshold and
        # x=12 is below it.
        assert _rgba_pixel(result, (4, 8))[3] == 255, "alpha above threshold stays opaque"
        assert _rgba_pixel(result, (12, 8))[3] == 0, "alpha below threshold becomes transparent"


def test_gif_dither_option_changes_palette_reduction(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    # A smooth gradient is the case where dithering actually does something;
    # a two-colour image would pass either way.
    gradient = Image.new("RGB", (256, 8))
    for x in range(256):
        for y in range(8):
            gradient.putpixel((x, y), (x, 40, 255 - x))
    source = _write(tmp_path / "grad.png", gradient)

    on = _convert(converter, source, tmp_path, "gif", {"dither": True})
    off = _convert(converter, source, tmp_path, "gif", {"dither": False})

    assert on.read_bytes() != off.read_bytes(), "the dither setting must affect output"


def test_gif_dither_accepts_names(tmp_path: Path, converter: PillowImageConverter) -> None:
    gradient = Image.new("RGB", (128, 8))
    for x in range(128):
        for y in range(8):
            gradient.putpixel((x, y), (x, 40, 255 - x))
    source = _write(tmp_path / "grad.png", gradient)

    named_off = _convert(converter, source, tmp_path, "gif", {"dither": "none"})
    bool_off = _convert(converter, source, tmp_path, "gif", {"dither": False})
    floyd = _convert(converter, source, tmp_path, "gif", {"dither": "floyd"})

    assert named_off.read_bytes() == bool_off.read_bytes()
    assert floyd.read_bytes() != bool_off.read_bytes()


def test_gif_from_opaque_source_has_transparent_index_available(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    # Nothing to make transparent, but the reserved entry must not corrupt the
    # colours that are there.
    source = _write(tmp_path / "opaque.png", Image.new("RGB", (64, 64), (12, 200, 90)))

    output = _convert(converter, source, tmp_path, "gif")

    with Image.open(output) as result:
        assert _rgba_pixel(result, (32, 32))[:3] == (12, 200, 90)


# --- animated GIF -----------------------------------------------------------


def _write_animation(
    path: Path,
    colors: list[str],
    durations: list[int],
    disposal: int = 2,
) -> Path:
    frames = [
        Image.new("RGBA", (64, 64), color).convert("P", palette=Image.Palette.ADAPTIVE)
        for color in colors
    ]
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        disposal=disposal,
        loop=0,
    )
    return path


def _frame_timings(path: Path) -> tuple[list[int | None], list[int | None]]:
    with Image.open(path) as image:
        durations: list[int | None] = []
        disposals: list[int | None] = []
        for index in range(getattr(image, "n_frames", 1)):
            image.seek(index)
            durations.append(image.info.get("duration"))
            disposals.append(getattr(image, "disposal_method", None))
        return durations, disposals


def test_animated_gif_keeps_every_frame(tmp_path: Path, converter: PillowImageConverter) -> None:
    source = _write_animation(
        tmp_path / "anim.gif", ["red", "green", "blue", "yellow"], [120, 80, 200, 40]
    )

    output = _convert(converter, source, tmp_path, "gif")

    with Image.open(output) as result:
        assert getattr(result, "n_frames", 1) == 4


def test_animated_gif_preserves_frame_durations(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    # Dropping per-frame timing is what makes a converted animation stutter.
    source = _write_animation(
        tmp_path / "anim.gif", ["red", "green", "blue", "yellow"], [120, 80, 200, 40]
    )

    output = _convert(converter, source, tmp_path, "gif")

    durations, _ = _frame_timings(output)
    assert durations == [120, 80, 200, 40]


def test_animated_gif_preserves_disposal_methods(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    source = _write_animation(
        tmp_path / "anim.gif", ["red", "green", "blue", "yellow"], [100] * 4, disposal=1
    )

    output = _convert(converter, source, tmp_path, "gif")

    _, disposals = _frame_timings(output)
    assert disposals == [1, 1, 1, 1]


def test_animated_gif_loops_forever_by_default(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    source = _write_animation(tmp_path / "anim.gif", ["red", "green"], [100, 100])

    output = _convert(converter, source, tmp_path, "gif")

    with Image.open(output) as result:
        assert result.info.get("loop") == 0


def test_animated_source_to_still_target_uses_poster_frame(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    # Non-GIF targets are single images, so an animation collapses to its first
    # frame rather than failing or writing a broken multi-frame target.
    source = _write_animation(tmp_path / "anim.gif", ["red", "green"], [100, 100])

    output = _convert(converter, source, tmp_path, "png")

    with Image.open(output) as result:
        assert result.format == "PNG"
        assert getattr(result, "n_frames", 1) == 1
        assert _rgba_pixel(result, (32, 32))[:3] == (255, 0, 0)


def test_static_gif_does_not_gain_frames(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    source = _write(tmp_path / "still.png", _half_opaque())

    output = _convert(converter, source, tmp_path, "gif")

    with Image.open(output) as result:
        assert getattr(result, "n_frames", 1) == 1


# --- AVIF -------------------------------------------------------------------

requires_avif = pytest.mark.skipif(
    not _avif_available(), reason="this Pillow build has no AVIF encoder"
)


def _noise_image(width: int = 400, height: int = 300) -> Image.Image:
    """Detail-rich enough that quality settings produce measurably different files."""
    image = Image.new("RGB", (width, height))
    for x in range(width):
        for y in range(0, height, 3):
            image.putpixel((x, y), (x % 256, (x * 7) % 256, (x * 13) % 256))
    return image


@requires_avif
def test_avif_quality_option_changes_output_size(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    source = _write(tmp_path / "noise.png", _noise_image())

    low = _convert(converter, source, tmp_path, "avif", {"quality": 20})
    high = _convert(converter, source, tmp_path, "avif", {"quality": 90})

    assert low.stat().st_size < high.stat().st_size


@requires_avif
def test_avif_quality_is_clamped(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    source = _write(tmp_path / "noise.png", _noise_image())

    over = _convert(converter, source, tmp_path, "avif", {"quality": 999})
    at_max = _convert(converter, source, tmp_path, "avif", {"quality": 100})
    under = _convert(converter, source, tmp_path, "avif", {"quality": -5})
    at_min = _convert(converter, source, tmp_path, "avif", {"quality": 0})

    assert over.read_bytes() == at_max.read_bytes()
    assert under.read_bytes() == at_min.read_bytes()


@requires_avif
def test_avif_preserves_transparency(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    source = _write(tmp_path / "alpha.png", _half_opaque())

    output = _convert(converter, source, tmp_path, "avif")

    with Image.open(output) as result:
        assert result.format == "AVIF"
        # Alpha is exact - it is not a quantised channel. Colour is lossy, so it
        # is compared loosely rather than byte-for-byte.
        assert _rgba_pixel(result, (8, 8))[3] == 255
        assert _rgba_pixel(result, (48, 8))[3] == 0
        red, green, blue, _ = _rgba_pixel(result, (8, 8))
        assert red > 240 and green < 12 and blue < 12


@requires_avif
def test_avif_preserves_icc_colour_profile(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    # An untagged output would be read as sRGB, which shifts a wide-gamut or
    # HDR-tagged source. Pillow's AVIF writer takes the profile off image.info,
    # so the test is that nothing in the conversion drops it.
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    source = tmp_path / "tagged.jpg"
    Image.new("RGB", (32, 32), (10, 120, 200)).save(source, icc_profile=profile)

    result = converter.convert(
        input_paths=[str(source)],
        output_dir=str(tmp_path),
        target_format="avif",
        options={},
        progress_cb=lambda current, total: None,
        cancel_event=Event(),
    )
    assert not result.errors, result.errors

    with Image.open(result.output_paths[0]) as image:
        assert image.info.get("icc_profile") == profile


@requires_avif
@pytest.mark.parametrize("target", OUTPUT_FORMATS)
def test_avif_is_readable_as_a_conversion_input(
    tmp_path: Path, converter: PillowImageConverter, target: str
) -> None:
    # 256px, so the ICO branch can embed its full 256x256 frame and every
    # target agrees on the dimensions.
    source = _write(tmp_path / "in.png", Image.new("RGBA", (256, 256), (30, 140, 90, 255)))
    avif_file = _convert(converter, source, tmp_path, "avif")

    output = _convert(converter, avif_file, tmp_path, target)

    with Image.open(output) as result:
        assert result.size == (256, 256)


def test_avif_is_absent_from_the_matrix_without_an_encoder() -> None:
    # Deliberately NOT guarded by requires_avif: that skip fires exactly when
    # there is no encoder, which is the only case this test exists to cover.
    # The assertion holds either way, so it must run unconditionally.
    assert ("avif" in OUTPUT_FORMATS) is _avif_available()


# --- shared behaviour -------------------------------------------------------


# Pillow's own format identifiers, which are not always the extension:
# a .jpg file reports itself as "JPEG".
_EXPECTED_CONTAINER = {"jpg": "JPEG"}


@pytest.mark.parametrize("target", OUTPUT_FORMATS)
def test_every_declared_output_format_has_an_encoder(
    tmp_path: Path, converter: PillowImageConverter, target: str
) -> None:
    # A format listed in OUTPUT_FORMATS but missing from _save used to fall
    # through to the WebP branch and write WebP bytes under the new extension.
    source = _write(tmp_path / "in.png", Image.new("RGBA", (64, 64), (120, 30, 90, 255)))

    output = _convert(converter, source, tmp_path, target)

    expected = _EXPECTED_CONTAINER.get(target, target.upper())
    with Image.open(output) as result:
        assert result.format == expected


def test_outputs_report_the_caller_supplied_path(
    tmp_path: Path, converter: PillowImageConverter, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The frontend matches outputs to rows by string equality against the path
    # it sent, so the converter must echo that verbatim rather than the expanded
    # path it resolved for I/O. Pointing HOME at tmp_path makes "~/in.png"
    # expand to a file that really exists, so the conversion succeeds and the
    # reported key is actually checked.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _write(tmp_path / "in.png", Image.new("RGB", (32, 32), (4, 5, 6)))

    result = converter.convert(
        input_paths=["~/in.png"],
        output_dir=str(tmp_path),
        target_format="png",
        options={},
        progress_cb=lambda current, total: None,
        cancel_event=Event(),
    )

    assert not result.errors, result.errors
    assert result.outputs[0][0] == "~/in.png"
    assert Path(result.outputs[0][1]).is_file()


def test_unknown_output_format_is_rejected(
    tmp_path: Path, converter: PillowImageConverter
) -> None:
    source = _write(tmp_path / "in.png", Image.new("RGB", (16, 16), (0, 0, 0)))

    with pytest.raises(UnsupportedFormatError):
        _convert(converter, source, tmp_path, "tiff")
