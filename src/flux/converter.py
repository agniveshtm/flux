from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from threading import Event
from typing import Callable


@dataclass
class ConversionResult:
    output_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # (input, output) pairs for the files that succeeded. output_paths alone
    # cannot be mapped back onto the request: it is shorter than the input
    # list whenever a file failed, so positional matching assigns one file's
    # output to a different (often failed) row.
    outputs: list[tuple[str, str]] = field(default_factory=list)


class UnsupportedFormatError(ValueError):
    pass


def normalize_format(value: str) -> str:
    normalized = str(value).strip().lower().lstrip(".")
    if normalized == "jpeg":
        return "jpg"
    if normalized == "heif":
        return "heic"
    return normalized


class BaseConverter(ABC):
    @property
    @abstractmethod
    def kind(self) -> str:
        """What this converter writes: "image", "video", and so on.

        The UI groups the formats it offers by this - the format picker
        shows image and video formats as separate sets - so it has to come
        from the converter that actually writes the format rather than from
        a list in the frontend.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def supported_input_formats(self) -> list[str]:
        raise NotImplementedError

    @property
    @abstractmethod
    def supported_output_formats(self) -> list[str]:
        raise NotImplementedError

    @property
    def also_video_outputs(self) -> tuple[str, ...]:
        """Outputs of this converter that are also *video* conversions.

        Most formats belong to one ring of the format donut: the ring of the
        converter that writes them. GIF is the exception - written from
        stills by the image converter and from full clips by the same
        converter's palette chain - so the converter that owns it declares
        the extra ring membership here rather than the frontend keeping a
        "gif is also video" special case. Empty for everything else, and
        capability-gated by the implementations (no ffmpeg, no video ring).
        """
        return ()

    @abstractmethod
    def convert(
        self,
        input_paths: list[str],
        output_dir: str,
        target_format: str,
        options: dict,
        # float, not int: image converters report (index, total) at file
        # boundaries, but the video converter also reports fractions within
        # a file (completed_before + elapsed/duration) for a smooth bar.
        progress_cb: Callable[[float, float], None],
        cancel_event: Event,
    ) -> ConversionResult:
        raise NotImplementedError


class ConverterRegistry:
    def __init__(self) -> None:
        self._converters: dict[str, BaseConverter] = {}

    def register(self, converter: BaseConverter) -> BaseConverter:
        if not isinstance(converter, BaseConverter):
            raise TypeError("converter must implement BaseConverter")

        for output_format in converter.supported_output_formats:
            normalized = normalize_format(output_format)
            existing = self._converters.get(normalized)
            if existing is not None and existing is not converter:
                raise ValueError(f"Converter already registered for format: {normalized}")
            self._converters[normalized] = converter

        return converter

    register_converter = register

    def get_converter_for_format(self, target_format: str) -> BaseConverter:
        normalized = normalize_format(target_format)
        try:
            return self._converters[normalized]
        except KeyError as exc:
            raise UnsupportedFormatError(f"Unsupported output format: {target_format}") from exc

    def get_converter(self, target_format: str) -> BaseConverter:
        return self.get_converter_for_format(target_format)

    @property
    def supported_input_formats(self) -> list[str]:
        # Deliberately NOT run through normalize_format: that helper maps
        # "jpeg" to "jpg", which is right for a *target* (one encoder, one
        # canonical name) but wrong for what a converter can *read*. Flux reads
        # both .jpg and .jpeg files, and collapsing them here made
        # getSupportedFormats() - which the frontend treats as the single source
        # of truth - under-report an input every converter accepts.
        formats = {
            str(item).strip().lower().lstrip(".")
            for converter in self._converters.values()
            for item in converter.supported_input_formats
        }
        return sorted(formats)

    @property
    def supported_output_formats(self) -> list[str]:
        return sorted(self._converters)

    @property
    def supported_output_kinds(self) -> dict[str, str]:
        """Which converter writes each output format, as format -> kind.

        Keyed by the same normalized names as supported_output_formats, so
        the UI can group the formats it offers without knowing which
        converter is behind them.
        """
        return {
            fmt: converter.kind
            for fmt, converter in self._converters.items()
        }

    @property
    def supported_targets_by_input(self) -> dict[str, list[str]]:
        """Which target each readable input format may be converted to.

        The input-aware half of the format matrix, derived here rather than
        in the frontend (which must never keep a format table of its own):

        * a format is never a target of itself - re-encoding to the format
          you already have is the no-op the matrix has always excluded; and
        * a target appears only if the converter that *writes* it also
          *reads* this input. That second rule is what keeps offered targets
          honest as converters multiply: images never offer MP4 (the video
          converter does not decode stills - a photo encoded as a video is a
          one-frame clip nobody wants), and a video never offers a target
          whose encoder cannot open it.

        Keys are the raw input names (jpg and jpeg both appear, matching
        supported_input_formats); values are sorted for a stable UI order.
        """
        mapping: dict[str, list[str]] = {}
        for input_format in self.supported_input_formats:
            key = normalize_format(input_format)
            targets = {
                fmt
                for fmt, converter in self._converters.items()
                if fmt != key and input_format in converter.supported_input_formats
            }
            mapping[input_format] = sorted(targets)
        return mapping

    @property
    def supported_output_rings(self) -> dict[str, list[str]]:
        """Which ring of the format donut each output belongs to.

        The donut groups formats by kind, and GIF - written from stills
        (image conversion) *and* from clips (video conversion) - has to
        appear in both rings: an image row's GIF target is an image
        conversion, a video row's is a video one, and the ring is a browse
        surface, not a routing decision. Membership comes from each
        converter's kind plus its declared also_video_outputs, so the
        frontend receives the grouping and never computes it.
        """
        rings: dict[str, list[str]] = {"image": [], "video": []}
        seen_converters: set[int] = set()
        for fmt, converter in self._converters.items():
            rings.setdefault(converter.kind, []).append(fmt)
            if id(converter) in seen_converters:
                continue
            seen_converters.add(id(converter))
            for extra in converter.also_video_outputs:
                normalized = normalize_format(extra)
                if normalized in self._converters and normalized not in rings["video"]:
                    rings["video"].append(normalized)
        return {kind: sorted(formats) for kind, formats in rings.items()}