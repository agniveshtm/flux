from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Callable

from PIL import Image, ImageOps, features

from flux.converter import BaseConverter, ConversionResult, UnsupportedFormatError, normalize_format

def _avif_available() -> bool:
    """Whether this Pillow build can encode AVIF.

    Pillow has carried a libavif-backed AVIF plugin since 11.3, so a current
    build encodes it without any extra dependency (and, importantly, without
    growing the installer). Older or trimmed builds do not, and offering AVIF
    in the UI only to fail at save time would be worse than not offering it -
    so the format list itself is capability-driven and the frontend never shows
    a target this build cannot write.
    """
    try:
        return bool(features.check("avif"))
    except Exception:
        return False


# The formats this converter can actually read and write. The frontend derives
# its whole input->target matrix from getSupportedFormats(), so these two tuples
# - not any frontend table - are the single source of truth for what Flux
# supports. Each Phase 1.1 format adds itself here when its encoder lands.
INPUT_FORMATS = ("jpg", "jpeg", "png", "webp", "ico", "gif") + (
    ("avif",) if _avif_available() else ()
)
OUTPUT_FORMATS = ("jpg", "png", "webp", "ico", "gif") + (
    ("avif",) if _avif_available() else ()
)


# GIF marks transparency with a single fully-transparent palette index and has
# no partial alpha, so an edge has to be cut somewhere. Pixels at or below this
# alpha become that index; anything above is flattened opaque.
_GIF_TRANSPARENCY_THRESHOLD = 128

# The alpha -> transparency mask lookup for that threshold, built once at import.
#
# This is deliberately a list rather than a lambda. Pillow's point() is
# overloaded, and a type checker resolves a callable argument against the
# ImagePointTransform protocol overload - so the lambda's parameter is inferred
# as that protocol instead of int, and `value <= threshold` inside it becomes
# "Operator '<=' not supported for types 'ImagePointTransform' and
# 'Literal[128]'". The list selects the sequence overload instead, where the
# element type is plainly int.
_GIF_TRANSPARENT_MASK_LUT = [
    255 if value <= _GIF_TRANSPARENCY_THRESHOLD else 0 for value in range(256)
]


class PillowImageConverter(BaseConverter):
    @property
    def supported_input_formats(self) -> list[str]:
        return list(INPUT_FORMATS)

    @property
    def supported_output_formats(self) -> list[str]:
        return list(OUTPUT_FORMATS)

    def convert(
        self,
        input_paths: list[str],
        output_dir: str,
        target_format: str,
        options: dict,
        progress_cb: Callable[[int, int], None],
        cancel_event: Event,
    ) -> ConversionResult:
        target = normalize_format(target_format)
        if target not in self.supported_output_formats:
            raise UnsupportedFormatError(f"Unsupported output format: {target_format}")

        output_directory = Path(output_dir).expanduser()
        if not output_directory.is_dir():
            raise NotADirectoryError(f"Output directory does not exist: {output_directory}")

        conversion_options = options if isinstance(options, dict) else {}
        result = ConversionResult()
        total = len(input_paths)

        used_names: set[str] = set()

        for index, input_path in enumerate(input_paths, start=1):
            if cancel_event.is_set():
                result.errors.append("Conversion cancelled")
                break

            source = Path(input_path).expanduser()
            try:
                if not source.is_file():
                    raise FileNotFoundError(f"Input file does not exist: {source}")

                input_format = normalize_format(source.suffix)
                if input_format not in self.supported_input_formats:
                    raise UnsupportedFormatError(
                        f"Unsupported input format: {input_format or 'unknown'}"
                    )

                stem = source.stem
                output_name = f"{stem}.{target}"
                counter = 1
                while output_name in used_names or (output_directory / output_name).exists():
                    output_name = f"{stem}-{counter}.{target}"
                    counter += 1
                used_names.add(output_name)

                output_path = output_directory / output_name
                with Image.open(source) as image:
                    image.load()
                    if target == "gif" and self._is_animated(image):
                        self._save_animated_gif(image, output_path, conversion_options)
                    else:
                        # Non-GIF targets keep only the first frame. Image.load()
                        # has already collapsed the sequence, so an animated
                        # source becomes its poster frame - the behaviour every
                        # still-image target wants, and the one Pillow's
                        # save_all would otherwise have to be asked for.
                        self._save(
                            ImageOps.exif_transpose(image),
                            output_path,
                            target,
                            conversion_options,
                        )

                result.output_paths.append(str(output_path))
                result.outputs.append((str(source), str(output_path)))
            except Exception as exc:
                result.errors.append(f"{source.name}: {exc}")
            finally:
                progress_cb(index, total)

        return result

    @staticmethod
    def _save(image: Image.Image, output_path: Path, target_format: str, options: dict) -> None:
        save_options: dict = {}

        if target_format == "jpg":
            image = PillowImageConverter._flatten_transparency(image)
            save_options.update(
                {
                    "format": "JPEG",
                    "quality": PillowImageConverter._integer_option(options, "quality", 90, 1, 100),
                    "optimize": bool(options.get("optimize", False)),
                }
            )
            if "subsampling" in options:
                save_options["subsampling"] = PillowImageConverter._integer_option(
                    options, "subsampling", 2, 0, 4
                )
        elif target_format == "png":
            image = PillowImageConverter._rgb_or_rgba(image)
            save_options.update(
                {
                    "format": "PNG",
                    "optimize": bool(options.get("optimize", True)),
                }
            )
        elif target_format == "webp":
            image = PillowImageConverter._rgb_or_rgba(image)
            save_options.update(
                {
                    "format": "WEBP",
                    "quality": PillowImageConverter._integer_option(options, "quality", 90, 0, 100),
                    "method": PillowImageConverter._integer_option(options, "method", 4, 0, 6),
                }
            )
        elif target_format == "ico":
            image = PillowImageConverter._square_icon_canvas(image)
            save_options.update(
                {
                    "format": "ICO",
                    "sizes": PillowImageConverter._ico_sizes(image, options),
                }
            )
        elif target_format == "gif":
            image = PillowImageConverter._gif_palette_image(image, options)
            save_options.update(
                {
                    "format": "GIF",
                    "optimize": bool(options.get("optimize", True)),
                }
            )
        elif target_format == "avif":
            image = PillowImageConverter._rgb_or_rgba(image)
            save_options.update(
                {
                    "format": "AVIF",
                    # AVIF is far denser than JPEG/WebP at the same visual
                    # quality, so it carries its own default rather than
                    # inheriting the 90 the other lossy formats use - at 90 the
                    # files are visibly larger for no perceptible gain.
                    "quality": PillowImageConverter._integer_option(options, "quality", 80, 0, 100),
                    # 6 is Pillow's default; 0 is the slowest and best, which
                    # would stall a batch on large photos.
                    "speed": PillowImageConverter._integer_option(options, "speed", 6, 0, 10),
                }
            )
            # Pillow's AVIF writer reads icc_profile and xmp straight off
            # image.info, which is how a wide-gamut or HDR-tagged source keeps
            # its colour profile instead of being silently reinterpreted as
            # sRGB. There is nothing to pass here - carrying image.info through
            # the conversion is the whole mechanism.
        else:
            # An explicit reject, so a format added to OUTPUT_FORMATS without an
            # encoder fails loudly instead of silently writing the previous
            # branch's bytes under the new extension (a PNG named .avif).
            raise UnsupportedFormatError(f"No encoder for output format: {target_format}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, **save_options)

    @staticmethod
    def _flatten_transparency(image: Image.Image) -> Image.Image:
        if image.mode == "RGB":
            return image

        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background

    @staticmethod
    def _rgb_or_rgba(image: Image.Image) -> Image.Image:
        if image.mode in {"RGB", "RGBA"}:
            return image
        if "transparency" in image.info or image.mode in {"LA", "PA"}:
            return image.convert("RGBA")
        return image.convert("RGB")

    # Timing used for frames whose source carries no duration metadata. A 0ms
    # frame never advances, so an animation of these would render as a single
    # still image; 100ms is the 10fps GIF default.
    _DEFAULT_FRAME_DURATION_MS = 100

    # "Do not dispose" - the frame is left on screen and the next one is drawn
    # over it. Every frame written here is fully composited by Pillow's seek(),
    # so nothing needs the canvas cleared between frames and this avoids the
    # flicker that disposing to background would introduce.
    _DEFAULT_FRAME_DISPOSAL = 1

    @staticmethod
    def _is_animated(image: Image.Image) -> bool:
        """Whether the source carries more than one frame."""
        if getattr(image, "is_animated", False):
            return True
        try:
            return int(getattr(image, "n_frames", 1)) > 1
        except (TypeError, ValueError, EOFError):
            return False

    @staticmethod
    def _frame_duration_ms(image: Image.Image) -> int:
        """A frame's display time, from whichever key the source plugin sets."""
        for key in ("duration", "frame_duration"):
            try:
                value = int(image.info.get(key, 0))
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return PillowImageConverter._DEFAULT_FRAME_DURATION_MS

    @staticmethod
    def _frame_disposal(image: Image.Image) -> int:
        """A frame's disposal method, clamped to the four values GIF defines."""
        try:
            value = int(getattr(image, "disposal_method", 0))
        except (TypeError, ValueError):
            return PillowImageConverter._DEFAULT_FRAME_DISPOSAL
        return value if 0 <= value <= 3 else PillowImageConverter._DEFAULT_FRAME_DISPOSAL

    @staticmethod
    def _loop_count(image: Image.Image) -> int:
        """How many times the animation repeats; 0 means forever, the GIF default."""
        try:
            value = int(image.info.get("loop", 0))
        except (TypeError, ValueError):
            return 0
        return value if value >= 0 else 0

    @classmethod
    def _save_animated_gif(
        cls, image: Image.Image, output_path: Path, options: dict
    ) -> None:
        """Write every frame of an animated source as an animated GIF.

        Each frame is seeked to and re-quantized through the same palette path
        as the static encoder, so dithering and transparency behave identically
        however many frames there are. Pillow's seek() composites each frame
        against the ones before it, so what is written here is full frames
        rather than the source's delta rectangles.

        Frame durations and disposal methods are carried across per frame -
        Pillow accepts both as lists - because losing them is what makes a
        converted animation stutter or freeze.
        """
        total = int(getattr(image, "n_frames", 1) or 1)
        frames: list[Image.Image] = []
        durations: list[int] = []
        disposals: list[int] = []

        for index in range(total):
            image.seek(index)
            durations.append(cls._frame_duration_ms(image))
            disposals.append(cls._frame_disposal(image))
            frames.append(cls._gif_palette_image(ImageOps.exif_transpose(image), options))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        frames[0].save(
            output_path,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            disposal=disposals,
            loop=cls._loop_count(image),
            optimize=bool(options.get("optimize", True)),
        )

    # GIF marks transparency with a single fully-transparent palette index and has
    # no partial alpha, so an edge has to be cut somewhere. The threshold itself
    # and the lookup derived from it are module-level constants above.
    # One of the 256 palette entries is reserved for transparency, leaving 255
    # for actual colour.
    _GIF_COLORS = 255

    # Palette entry reserved for the transparent pixels.
    _GIF_TRANSPARENT_INDEX = 255

    @staticmethod
    def _dither_option(options: dict) -> Image.Dither:
        """The dithering method requested for palette reduction.

        Accepts a bool or a name, because it arrives from the bridge as JSON
        and from the UI as a checkbox.
        """
        raw = options.get("dither", True)
        if isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized in {"none", "off", "false", "0"}:
                return Image.Dither.NONE
            return Image.Dither.FLOYDSTEINBERG
        return Image.Dither.NONE if not raw else Image.Dither.FLOYDSTEINBERG

    @classmethod
    def _gif_palette_image(cls, image: Image.Image, options: dict) -> Image.Image:
        """Reduce an image to a palette image carrying a transparent index.

        Two Pillow details make this less obvious than it looks:

        * Pillow's own GIF writer calls ``convert("P", palette=ADAPTIVE)``
          with no dither argument, so the dithering control this format is
          supposed to expose would be unreachable through the default path.
        * ``Image.quantize(colors=..., dither=...)`` *silently ignores*
          ``dither`` unless a reference ``palette`` is supplied - without one it
          calls ``self.im.quantize(colors, method, kmeans)`` and drops the
          argument. Passing it twice changes nothing; the dither only applies
          on the second pass, against the palette the first pass built.

        So the palette is built first and, when dithering is on, the image is
        requantized against that fixed palette - which is also the only case
        where dithering is meaningful at all.

        The result reserves one palette entry for transparency: the colour pass
        is limited to 255 colours, and the alpha mask is pasted in afterwards as
        a hard index, because GIF cannot represent partial alpha.
        """
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        transparent_mask = alpha.point(_GIF_TRANSPARENT_MASK_LUT, mode="1")

        # Composite onto white before quantizing so the transparent regions
        # pick up sensible neighbouring colours instead of black, which would
        # fringe the artwork if a viewer ignored the transparency index.
        flattened = Image.new("RGB", rgba.size, (255, 255, 255))
        flattened.paste(rgba, mask=alpha)

        paletted = flattened.quantize(
            colors=cls._GIF_COLORS, method=Image.Quantize.MEDIANCUT
        )
        dither = cls._dither_option(options)
        if dither is not Image.Dither.NONE:
            paletted = flattened.quantize(palette=paletted, dither=dither)

        paletted.info["transparency"] = cls._GIF_TRANSPARENT_INDEX
        paletted.paste(cls._GIF_TRANSPARENT_INDEX, mask=transparent_mask)
        return paletted

    # Icon sizes generated for ICO output. These are the sizes Windows asks for
    # across the shell, taskbar, Alt-Tab and Explorer thumbnail paths, so a
    # single file satisfies every consumer instead of the user re-exporting per
    # size.
    _ICO_DEFAULT_SIZES = (16, 32, 48, 256)

    @staticmethod
    def _square_icon_canvas(image: Image.Image) -> Image.Image:
        """Centre the image on a transparent square canvas.

        Pillow's ICO writer builds each frame with Image.thumbnail(), which
        preserves aspect ratio - handing it a 300x200 photo yields 256x170
        frames, and Windows renders non-square icon frames stretched or
        letterboxed depending on the shell. Icons are square by convention, so
        the padding is applied here, before Pillow's resize.

        The canvas is always RGBA even for an opaque source, so a non-square
        image is padded with real transparency rather than black.
        """
        rgba = image.convert("RGBA")
        side = max(rgba.size)
        if rgba.size == (side, side):
            return rgba

        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(rgba, ((side - rgba.width) // 2, (side - rgba.height) // 2))
        return canvas

    @classmethod
    def _ico_sizes(cls, image: Image.Image, options: dict) -> list[tuple[int, int]]:
        """The square sizes to embed, clamped to what the source can supply.

        Pillow silently skips any requested size larger than the source
        (IcoImagePlugin._save: "if size[0] > width ... continue"). A source
        smaller than every default size - a 10x10 favicon - would therefore
        skip all of them and write an ICO header declaring zero images, i.e. a
        corrupt file that Windows shows as a blank icon. Filtering here, and
        keeping the largest requested size when none fit, keeps the output
        always valid. Upscaling a small source to 256x256 would invent detail
        rather than preserve it, so it is not done.
        """
        # Annotated because the default is a fixed 4-tuple while the parsed
        # override is a variable-length one.
        requested: tuple[int, ...] = cls._ICO_DEFAULT_SIZES

        raw = options.get("icoSizes", options.get("ico_sizes"))
        if isinstance(raw, (list, tuple)) and raw:
            parsed: list[int] = []
            for item in raw:
                try:
                    value = int(item)
                except (TypeError, ValueError):
                    continue
                if 1 <= value <= 256:
                    parsed.append(value)
            if parsed:
                requested = tuple(sorted(set(parsed)))

        side = min(image.size)
        usable = [size for size in requested if size <= side]
        if not usable:
            # Nothing requested fits - a 10x10 favicon is smaller than every
            # standard icon size. Emitting the source's own size keeps the file
            # valid; emitting the smallest *requested* size would be skipped by
            # Pillow above and produce the same zero-image header.
            usable = [side]

        return [(size, size) for size in usable]

    @staticmethod
    def _integer_option(options: dict, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(options.get(key, default))
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, value))