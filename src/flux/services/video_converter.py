"""FFmpegVideoConverter: Phase 2.1 video conversion (MP4 out).

Implements BaseConverter against the bundled ffmpeg sidecar binary. The
ffmpeg process is invoked over argv + pipes (subprocess), never linked -
which is what keeps the LGPL/GPL from reaching Flux's own code (see
research/phase2-video-mobile/REPORT.md 1.2.1: pipes and argv are
communication between two separate programs, not linking).

The researched process behaviours - progress parsing, continuous stdout
drain, the three-rung cancel chain, duration from stderr instead of
ffprobe - now live once in flux.services.ffmpeg.run_ffmpeg, shared with the
image converter's video-to-GIF encode. This module owns what is MP4-specific:
the encoder preference table, the CRF mappings, and the command line.

Inputs cover the video containers plus GIF, which the video converter reads
as an animation source (GIF -> MP4) - GIF is written as an image format by
the image converter, and read as a video by this one.
"""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Callable

from flux.converter import (
    BaseConverter,
    ConversionResult,
    UnsupportedFormatError,
    normalize_format,
    reserve_unique_output,
)
from flux.services.ffmpeg import (
    VIDEO_INPUT_FORMATS,
    locate_ffmpeg,
    pick_encoder,
    run_ffmpeg,
    video_available,
)

# The one output Phase 2.1 ships. Phase 2.2+ append their own rows here and
# in flux.services.ffmpeg.MP4_ENCODERS-style tables, not in the frontend.
OUTPUT_FORMATS = ("mp4",)


def _clamp_quality(quality: int | None) -> int:
    """The slider's 0-100 value, or 50 when the user never moved it.

    50 is the neutral point the mappings below centre on, so "no quality
    chosen" behaves like the middle of the slider rather than an extreme.
    """
    if quality is None:
        return 50
    try:
        return max(0, min(100, int(quality)))
    except (TypeError, ValueError):
        return 50


def x264_crf(quality: int | None) -> int:
    """Slider value -> libx264 CRF on the sane 18-28 window (default 23).

    Lower CRF is better quality: 100 -> 18 (near lossless), 0 -> 28, and
    the untouched default lands on x264's own default of 23.
    """
    if quality is None:
        return 23
    return 28 - (_clamp_quality(quality) * 10) // 100


def vp9_crf(quality: int | None) -> int:
    """Slider value -> libvpx-vp9 CRF (0-63 scale, sane window 10-40).

    Not x264's scale - the two are not interchangeable - and the default
    (None) is libvpx's own recommended 32 with -b:v 0 for quality mode.
    """
    if quality is None:
        return 32
    return 40 - (_clamp_quality(quality) * 30) // 100


def video_encode_args(encoder: str, quality: int | None) -> list[str]:
    """The video-side command line for one encoder.

    One table keyed on encoder name is the whole per-codec divergence: CRF
    ranges differ (x264 0-51, VP9 0-63), VP9 needs -b:v 0 to mean "CRF
    mode", and only x264 has presets. Everything else about MP4 output -
    pixel format, faststart - is identical and lives in _encode_one.
    """
    if encoder == "libx264":
        return [
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(x264_crf(quality)),
            "-pix_fmt", "yuv420p",
        ]
    if encoder == "libvpx-vp9":
        return [
            "-c:v", "libvpx-vp9",
            "-crf", str(vp9_crf(quality)),
            "-b:v", "0",
            "-row-mt", "1",
            "-deadline", "good",
            # Speed tier, fixed rather than slider-driven: the slider means
            # quality, and letting it also change encode speed would make the
            # same number mean two things. 4 is the mid-fast point of 0-5.
            "-cpu-used", "4",
            "-pix_fmt", "yuv420p",
        ]
    raise UnsupportedFormatError(f"No MP4 encode arguments for encoder: {encoder}")


class FFmpegVideoConverter(BaseConverter):
    @property
    def kind(self) -> str:
        return "video"

    @property
    def supported_input_formats(self) -> list[str]:
        # Capability-gated: with no capable ffmpeg build this returns an
        # empty list, the registry maps no formats to this converter, and
        # the UI never offers video conversion - the same pattern as the
        # AVIF/HEIF gates in image_converter, so a source checkout without
        # vendor/ffmpeg.exe runs exactly as it did before Phase 2.1.
        #
        # GIF joins the containers because ffmpeg reads it as an animation
        # and this converter writes a real MP4 from it - while the image
        # converter keeps reading GIF through Pillow for every still target.
        if not video_available():
            return []
        return [*VIDEO_INPUT_FORMATS, "gif"]

    @property
    def supported_output_formats(self) -> list[str]:
        if not video_available():
            return []
        return list(OUTPUT_FORMATS)

    def convert(
        self,
        input_paths: list[str],
        output_dir: str,
        target_format: str,
        options: dict,
        progress_cb: Callable[[float, float], None],
        cancel_event: Event,
    ) -> ConversionResult:
        target = normalize_format(target_format)
        if target not in self.supported_output_formats:
            raise UnsupportedFormatError(f"Unsupported output format: {target_format}")

        encoder = pick_encoder()
        ffmpeg = locate_ffmpeg()
        if encoder is None or ffmpeg is None:
            return ConversionResult(
                errors=["Video conversion is unavailable: no capable ffmpeg build was found."]
            )

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
            cancelled_mid_file = False
            output_path: Path | None = None
            try:
                if not source.is_file():
                    raise FileNotFoundError(f"Input file does not exist: {source}")

                input_format = normalize_format(source.suffix)
                if input_format not in self.supported_input_formats:
                    raise UnsupportedFormatError(
                        f"Unsupported input format: {input_format or 'unknown'}"
                    )

                # Claim the name atomically (see reserve_unique_output):
                # exists() alone lets two concurrent jobs pick the same name
                # and let -y replace one finished result with the other's.
                output_path = reserve_unique_output(
                    output_directory, source.stem, "mp4", used_names
                )

                ok, error_message = self._encode_one(
                    ffmpeg=ffmpeg,
                    encoder=encoder,
                    source=source,
                    output_path=output_path,
                    options=conversion_options,
                    progress_cb=progress_cb,
                    completed_before=index - 1,
                    total=total,
                    cancel_event=cancel_event,
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

    def _encode_one(
        self,
        ffmpeg: Path,
        encoder: str,
        source: Path,
        output_path: Path,
        options: dict,
        progress_cb: Callable[[float, float], None],
        completed_before: int,
        total: int,
        cancel_event: Event,
    ) -> tuple[bool, str | None]:
        """Run one ffmpeg encode. Returns (success, error_message).

        Command shape (verified against the report's per-phase table):
        -progress pipe:1 puts machine-readable key=value lines on stdout;
        -nostats silences the human-readable stats line so stderr stays a
        small parseable log (where -loglevel info yields the Duration);
        -stats_period 0.25 doubles the tick rate for a smoother bar; -y
        overwrites the 0-byte placeholder reserve_unique_output claimed (the
        claim, not -y, is the race guard).

        Progress, the stdout drain and the three-rung cancel chain are the
        shared engine's job (flux.services.ffmpeg.run_ffmpeg); everything
        MP4-specific stops at the command line below.
        """
        cmd = [
            str(ffmpeg),
            "-hide_banner",
            "-nostats",
            "-loglevel", "info",
            "-stats_period", "0.25",
            "-progress", "pipe:1",
            "-y",
            "-i", str(source),
            *video_encode_args(encoder, options.get("quality")),
            # AAC for every video encoder: AAC-in-MP4 is the universally
            # decodable pairing, unlike the Opus a WebM/VP9 line would use.
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]

        return run_ffmpeg(
            cmd,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
            completed_before=completed_before,
            total=total,
            expected_output=output_path,
        )
