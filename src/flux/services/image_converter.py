from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Callable

from PIL import Image, ImageOps

from flux.converter import BaseConverter, ConversionResult, UnsupportedFormatError, normalize_format


class PillowImageConverter(BaseConverter):
    @property
    def supported_input_formats(self) -> list[str]:
        return ["jpg", "jpeg", "png", "webp"]

    @property
    def supported_output_formats(self) -> list[str]:
        return ["jpg", "png", "webp"]

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
                while output_name in used_names:
                    output_name = f"{stem}-{counter}.{target}"
                    counter += 1
                used_names.add(output_name)

                output_path = output_directory / output_name
                with Image.open(source) as image:
                    image.load()
                    converted = ImageOps.exif_transpose(image)
                    self._save(converted, output_path, target, conversion_options)

                result.output_paths.append(str(output_path))
            except Exception as exc:
                result.errors.append(f"{source.name}: {exc}")
            finally:
                progress_cb(index, total)

        return result

    @staticmethod
    def _save(image: Image.Image, output_path: Path, target_format: str, options: dict) -> None:
        save_options: dict = {}
        output_format = target_format.upper()

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
        else:
            image = PillowImageConverter._rgb_or_rgba(image)
            save_options.update(
                {
                    "format": "WEBP",
                    "quality": PillowImageConverter._integer_option(options, "quality", 90, 0, 100),
                    "method": PillowImageConverter._integer_option(options, "method", 4, 0, 6),
                }
            )

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

    @staticmethod
    def _integer_option(options: dict, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(options.get(key, default))
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, value))