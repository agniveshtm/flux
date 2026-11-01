from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
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


def clamp_quality(quality: int | None) -> int:
    """The quality slider's 0-100 value, or 50 when the user never moved it.

    50 is the neutral point the encoder mappings centre on, so "no quality
    chosen" behaves like the middle of the slider rather than an extreme.
    Every encoder maps this one number into its own scale (x264 0-51, VP9
    0-63, LAME 0-9), because the slider means "quality", not a codec value.
    """
    if quality is None:
        return 50
    try:
        return max(0, min(100, int(quality)))
    except (TypeError, ValueError):
        return 50


def reserve_unique_output(
    output_directory: Path, stem: str, target_format: str, used_names: set[str]
) -> Path:
    """Claim a free output name for one file, returning its (reserved) path.

    The name is reserved by *creating* it with O_CREAT|O_EXCL rather than
    probed with exists(): the window between a successful exists() check and
    ffmpeg/Pillow writing the file lets two concurrent conversions of the
    same input both pick "clip.mp4", and the later -y/overwrite would
    silently replace the other job's finished result. O_EXCL makes exactly
    one claim win; the loser sees FileExistsError and takes the next suffix.

    The 0-byte reservation is the output's placeholder - the encoder
    overwrites it in place - so a file whose conversion then fails must
    unlink it; each convert() does that in its except handler, and the
    cancel paths unlink the partial themselves. Other OS errors (a
    permission problem, a full disk) propagate as the conversion error they
    are rather than looping forever.
    """
    counter = 0
    while True:
        name = (
            f"{stem}.{target_format}"
            if counter == 0
            else f"{stem}-{counter}.{target_format}"
        )
        counter += 1
        if name in used_names:
            continue
        path = output_directory / name
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        os.close(fd)
        used_names.add(name)
        return path


def convert_files(
    *,
    input_paths: list[str],
    output_dir: str,
    target_format: str,
    allowed_input_formats: list[str],
    encode_one: Callable[[Path, Path, int, int], tuple[bool, str | None]],
    progress_cb: Callable[[float, float], None],
    cancel_event: Event,
) -> ConversionResult:
    """Convert a batch, one file at a time, through a caller's encoder.

    The loop both ffmpeg converters need: validate the input, claim a unique
    output name, run one encode, and clean up on failure or cancellation. It
    lives here rather than twice in the converters so a file that fails (or
    is cancelled) leaves exactly the same nothing behind, whichever encoder
    produced it.

    ``encode_one(source, output_path, completed_before, total)`` returns
    ``(success, error_message)``; the caller closes over its own options,
    progress callback and cancel event. ``target_format`` is both the
    extension and the reserved name's suffix, normalized once here.
    """
    target = normalize_format(target_format)
    output_directory = Path(output_dir).expanduser()
    if not output_directory.is_dir():
        raise NotADirectoryError(f"Output directory does not exist: {output_directory}")

    result = ConversionResult()
    total = len(input_paths)
    used_names: set[str] = set()

    for index, input_path in enumerate(input_paths, start=1):
        if cancel_event.is_set():
            result.errors.append("Conversion cancelled")
            break

        source = Path(input_path).expanduser()
        cancelled_mid_file = False
        output_path: Path | None = None
        try:
            if not source.is_file():
                raise FileNotFoundError(f"Input file does not exist: {source}")

            input_format = normalize_format(source.suffix)
            if input_format not in allowed_input_formats:
                raise UnsupportedFormatError(
                    f"Unsupported input format: {input_format or 'unknown'}"
                )

            # Claim the name atomically (see reserve_unique_output):
            # exists() alone lets two concurrent jobs pick the same name
            # and let -y replace one finished result with the other's.
            output_path = reserve_unique_output(
                output_directory, source.stem, target, used_names
            )

            ok, error_message = encode_one(
                source, output_path, index - 1, total
            )

            if cancel_event.is_set():
                # The "q" path finalises a playable file, but a cancelled
                # job reports no outputs - leaving the half-length video
                # on disk would look like a conversion that quietly
                # succeeded with the wrong duration. The name was
                # reserved above, so the path is this job's alone and
                # removing it cannot touch anything pre-existing.
                try:
                    output_path.unlink(missing_ok=True)
                except OSError:
                    pass
                cancelled_mid_file = True
                result.errors.append("Conversion cancelled")
            elif not ok:
                raise RuntimeError(error_message or "ffmpeg failed")
            else:
                result.output_paths.append(str(output_path))
                # Reported against the path the caller supplied, because
                # the frontend matches outputs to rows by string equality
                # on the path it sent (same reason as the image converter).
                result.outputs.append((input_path, str(output_path)))
        except Exception as exc:
            # A failed file leaves two things behind: the 0-byte name
            # reserve_unique_output claimed, and any partial ffmpeg
            # wrote over it. Both would outlive the error and look like
            # a finished result, so the claimed path goes away with the
            # failure.
            if output_path is not None:
                try:
                    output_path.unlink(missing_ok=True)
                except OSError:
                    pass
            result.errors.append(f"{source.name}: {exc}")
        finally:
            progress_cb(index, total)

        if cancelled_mid_file:
            break

    return result


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