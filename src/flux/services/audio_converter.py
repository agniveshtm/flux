"""FFmpegAudioConverter: audio extraction from video inputs (MP3, WAV).

The audio half of the video matrix. It reads exactly the containers the
video converter reads (never a still - a photo has no audio stream to
extract) and writes MP3 or WAV through the same shared ffmpeg pump.

Keeping this a separate converter, rather than extra outputs on
FFmpegVideoConverter, is what gives the format donut an honest ``audio``
kind: the registry groups a format under the kind of the converter that
writes it, and an MP3 is neither an image nor a video. The registry also
derives the input->target matrix from the same fact, so "audio targets are
offered only for video inputs" needs no special case anywhere.

The researched commands (research/phase2-video-mobile/REPORT.md, Part 1):

* MP3 - ``-vn -c:a libmp3lame -q:a {0..9}`` with ``-write_xing 0`` and
  ``-id3v2_version 0`` for a clean, player-friendly file.
* WAV - ``-vn -c:a pcm_s16le`` (uncompressed, so the quality slider does
  not apply).

Both are capability-gated on the encoder being present in the -encoders
probe, exactly like the video outputs.
"""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Callable

from flux.converter import (
    BaseConverter,
    ConversionResult,
    UnsupportedFormatError,
    clamp_quality,
    convert_files,
    normalize_format,
)
from flux.services.ffmpeg import (
    AUDIO_OUTPUT_FORMATS,
    VIDEO_INPUT_FORMATS,
    audio_available,
    audio_encoder_for,
    audio_output_available,
    locate_ffmpeg,
    run_ffmpeg,
)

OUTPUT_FORMATS = AUDIO_OUTPUT_FORMATS

# libmp3lame's VBR quality scale is 0-9 and runs the opposite way to the
# video CRFs: 0 is the best/slowest, 9 the smallest/fastest. The untouched
# default is 2 (LAME's "high quality" VBR tier) rather than the middle of
# the slider, because an audio extraction that silently degraded a clip's
# soundtrack would be the wrong default.
MP3_DEFAULT_QUALITY = 2


def mp3_quality(quality: int | None) -> int:
    """Slider value -> libmp3lame ``-q:a`` on its 0-9 scale.

    100 -> 0 (best), 0 -> 9 (smallest), and None -> the high-quality default.
    The integer maths keeps every slider step inside the encoder's range.
    """
    if quality is None:
        return MP3_DEFAULT_QUALITY
    return 9 - (clamp_quality(quality) * 9) // 100


def audio_encode_args(target_format: str, quality: int | None) -> list[str]:
    """The codec half of one audio target's command line."""
    if target_format == "mp3":
        return [
            "-c:a", "libmp3lame",
            "-q:a", str(mp3_quality(quality)),
            # A VBR MP3 with no Xing header and no ID3 tag is the cleanest
            # file for other players and tools to read back.
            "-write_xing", "0",
            "-id3v2_version", "0",
        ]
    if target_format == "wav":
        return ["-c:a", "pcm_s16le"]
    raise UnsupportedFormatError(f"No audio encode arguments for format: {target_format}")


class FFmpegAudioConverter(BaseConverter):
    @property
    def kind(self) -> str:
        return "audio"

    @property
    def supported_input_formats(self) -> list[str]:
        # Only the video containers: extraction needs an audio stream, and a
        # still has none. This is what keeps MP3/WAV off every image row
        # without the matrix needing an exception.
        if not self.supported_output_formats:
            return []
        return list(VIDEO_INPUT_FORMATS)

    @property
    def supported_output_formats(self) -> list[str]:
        if not audio_available():
            return []
        return [fmt for fmt in OUTPUT_FORMATS if audio_output_available(fmt)]

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

        encoder = audio_encoder_for(target)
        ffmpeg = locate_ffmpeg()
        if encoder is None or ffmpeg is None:
            return ConversionResult(
                errors=[
                    "Audio extraction is unavailable: no capable ffmpeg build was found."
                ]
            )

        conversion_options = options if isinstance(options, dict) else {}

        def encode_one(
            source: Path,
            output_path: Path,
            completed_before: int,
            total: float,
        ) -> tuple[bool, str | None]:
            return self._encode_one(
                ffmpeg=ffmpeg,
                target_format=target,
                source=source,
                output_path=output_path,
                options=conversion_options,
                progress_cb=progress_cb,
                completed_before=completed_before,
                total=total,
                cancel_event=cancel_event,
            )

        return convert_files(
            input_paths=input_paths,
            output_dir=output_dir,
            target_format=target,
            allowed_input_formats=self.supported_input_formats,
            encode_one=encode_one,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )

    def _encode_one(
        self,
        ffmpeg: Path,
        target_format: str,
        source: Path,
        output_path: Path,
        options: dict,
        progress_cb: Callable[[float, float], None],
        completed_before: int,
        total: float,
        cancel_event: Event,
    ) -> tuple[bool, str | None]:
        """Run one audio extraction through the shared ffmpeg pump.

        ``-vn`` drops the picture before the codec arguments, so ffmpeg
        never tries to carry a video stream into an audio-only container.
        The codec comes from the same per-target table capability gating
        reads (AUDIO_OUTPUT_ENCODERS), so the check and the command line
        cannot drift apart.
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
            "-vn",
            *audio_encode_args(target_format, options.get("quality")),
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
